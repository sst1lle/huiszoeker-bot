"""
PDOK-geocoding voor Nederlandse adressen.

Hot path: in-memory cache + coalescing + PDOK (max concurrency).
Supabase: batch flush met backpressure, periodic daemon en retry-queue.

Publieke API:
    ensure_geocode_flush_daemon()  # eenmalig bij process start
    begin_geocode_run()
    result = await geocode("Zeesluisweg 50A, Den Haag")
    await flush_geocode_cache()
"""
from __future__ import annotations

import os
import re
import time
import asyncio
import logging
import threading
from collections.abc import Iterable

import httpx

from db import get_db

logger = logging.getLogger(__name__)

PDOK_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
_HTTP_TIMEOUT = 10.0
_USER_AGENT = "huiszoeker-geocoder/1.0"
_PDOK_CONCURRENCY = 6
_FLUSH_CHUNK = 50
_PENDING_MAX = 500
_FLUSH_INTERVAL_SEC = 45
_FLUSH_RETRY_ATTEMPTS = 3
MAX_INFLIGHT_SIZE = int(os.getenv("GEOCODE_MAX_INFLIGHT", "500"))
INFLIGHT_STALE_SEC = int(os.getenv("GEOCODE_INFLIGHT_STALE_SEC", "600"))

_RESULT_FIELDS = ("straat", "huisnummer", "postcode", "wijk", "buurt", "stad", "lat", "lng")

_POSTCODE_RE = re.compile(r"\b(\d{4})\s*([A-Za-z]{2})\b")
_HUISNR_RE = re.compile(r"\b(\d{1,5})\s*([A-Za-z]?)\b")
_POINT_RE = re.compile(r"POINT\(\s*([\d.]+)\s+([\d.]+)\s*\)")

_lock = threading.Lock()
_pdok_sem: asyncio.Semaphore | None = None
_memory: dict[str, dict | None] = {}
_pending_rows: dict[str, dict] = {}
_retry_rows: list[dict] = []
_inflight: dict[str, dict] = {}
_cycle_started_ts: float = 0.0
_stats = {
    "memory_hit": 0,
    "pdok_calls": 0,
    "coalesced": 0,
    "buffered_writes": 0,
    "flush_ok": 0,
    "flush_fail": 0,
    "flush_backpressure": 0,
    "flush_periodic": 0,
    "retry_requeued": 0,
}
_MISS = object()

_daemon_stop = threading.Event()
_daemon_started = False


def ensure_geocode_flush_daemon() -> None:
    """Start achtergrond-flush (periodiek + retry drain). Idempotent."""
    global _daemon_started
    if _daemon_started:
        return
    _daemon_started = True
    threading.Thread(
        target=_flush_daemon_loop,
        name="geocode-flush",
        daemon=True,
    ).start()


def _cancel_inflight_entry(entry: dict | None) -> None:
    if not entry:
        return
    task = entry.get("task")
    if task and not task.done():
        task.cancel()


def _inflight_safety_prune() -> None:
    """Trim inflight bij overschrijding: eerst vorige cycle, anders oudste 50%."""
    with _lock:
        size = len(_inflight)
        if size <= MAX_INFLIGHT_SIZE:
            return
        logger.warning(f"[geocode] inflight_safety_trigger size={size}")

        for key in list(_inflight):
            if _inflight[key]["ts"] < _cycle_started_ts:
                _cancel_inflight_entry(_inflight.pop(key, None))

        if len(_inflight) <= MAX_INFLIGHT_SIZE:
            return

        sorted_keys = sorted(_inflight, key=lambda k: _inflight[k]["ts"])
        drop_n = max(1, len(sorted_keys) // 2)
        for key in sorted_keys[:drop_n]:
            _cancel_inflight_entry(_inflight.pop(key, None))
        logger.warning(
            f"[geocode] inflight_safety_prune dropped={drop_n} remaining={len(_inflight)}",
        )


async def cleanup_stale_inflight(max_age_seconds: int = 600) -> int:
    """Verwijder inflight entries ouder dan max_age_seconds (default 10 min)."""
    now = time.time()
    with _lock:
        stale_keys = [
            k for k, e in _inflight.items()
            if now - e["ts"] > max_age_seconds
        ]

    removed = 0
    for key in stale_keys:
        with _lock:
            entry = _inflight.pop(key, None)
        if entry:
            _cancel_inflight_entry(entry)
            removed += 1

    if removed:
        logger.info(f"[geocode] stale_inflight_cleanup removed={removed}", flush=True)
    return removed


def log_geocode_metrics() -> None:
    """Lichte observability aan einde van een main cycle."""
    with _lock:
        cache_size = len(_memory)
        inflight_n = len(_inflight)
        hits = _stats["memory_hit"]
        pdok = _stats["pdok_calls"]
        coalesced = _stats["coalesced"]

    lookups = hits + pdok + coalesced
    cache_hit_ratio = round(hits / lookups, 3) if lookups else 0.0
    logger.info(
        f"[geocode-metrics] cache_size={cache_size} inflight={inflight_n} "
        f"pdok_calls={pdok} cache_hit_ratio={cache_hit_ratio}",
        flush=True,
    )


def begin_geocode_run() -> None:
    """Reset per-run statistieken (geheugen-cache + inflight blijven tussen cycles)."""
    global _cycle_started_ts
    _cycle_started_ts = time.time()
    for k in _stats:
        _stats[k] = 0
    _inflight_safety_prune()


def _norm_adres(adres: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", adres.lower()).split())


def _pc_hnr_key(postcode: str | None, huisnummer: str | None) -> str | None:
    if not postcode or not huisnummer:
        return None
    return f"{postcode.replace(' ', '')} {huisnummer}".lower().strip()


def _pc_hnr_key_from_input(adres: str) -> str | None:
    pc = _POSTCODE_RE.search(adres)
    if not pc:
        return None
    hnr = _HUISNR_RE.search(adres.replace(pc.group(0), " "))
    if not hnr:
        return None
    huisnummer = f"{hnr.group(1)}{hnr.group(2)}"
    return _pc_hnr_key(f"{pc.group(1)}{pc.group(2)}", huisnummer)


def _lookup_keys(adres: str) -> tuple[str, str | None]:
    norm_key = _norm_adres(adres)
    input_pc_hnr = _pc_hnr_key_from_input(adres)
    return norm_key, input_pc_hnr


def _keys_for_result(norm_key: str, result: dict | None) -> list[str]:
    if not result:
        return [norm_key]
    canonical = _pc_hnr_key(result.get("postcode"), result.get("huisnummer")) or norm_key
    if canonical == norm_key:
        return [norm_key]
    return [canonical, norm_key]


def _row_for_cache(key: str, adres: str, result: dict | None) -> dict:
    row = {"cache_key": key, "query": adres.strip(), "found": result is not None}
    if result:
        row.update(result)
    return row


def _memory_get(keys: Iterable[str]):
    for key in keys:
        if key in _memory:
            return _memory[key]
    return _MISS


def _store_in_memory(keys: list[str], adres: str, result: dict | None) -> bool:
    """Returns True if pending buffer hit backpressure threshold."""
    overflow = False
    for key in keys:
        _memory[key] = result
        _pending_rows[key] = _row_for_cache(key, adres, result)
        _stats["buffered_writes"] += 1
    if len(_pending_rows) >= _PENDING_MAX:
        overflow = True
    return overflow


def _take_flush_batch() -> list[dict]:
    """Retry-WAL eerst, daarna pending (dedupe op cache_key)."""
    with _lock:
        merged: dict[str, dict] = {}
        for row in _retry_rows:
            merged[row["cache_key"]] = row
        _retry_rows.clear()
        for row in _pending_rows.values():
            merged[row["cache_key"]] = row
        _pending_rows.clear()
        return list(merged.values())


def _requeue_failed(rows: list[dict]) -> None:
    if not rows:
        return
    with _lock:
        _retry_rows.extend(rows)
    _stats["retry_requeued"] += len(rows)


def _parse_doc(doc: dict) -> dict:
    lat = lng = None
    m = _POINT_RE.search(doc.get("centroide_ll") or "")
    if m:
        lng, lat = float(m.group(1)), float(m.group(2))

    huisnummer = doc.get("huis_nlt")
    if not huisnummer and doc.get("huisnummer") is not None:
        huisnummer = str(doc["huisnummer"])

    return {
        "straat": doc.get("straatnaam"),
        "huisnummer": huisnummer,
        "postcode": doc.get("postcode"),
        "wijk": doc.get("wijknaam"),
        "buurt": doc.get("buurtnaam"),
        "stad": doc.get("woonplaatsnaam"),
        "lat": lat,
        "lng": lng,
    }


async def _pdok_lookup(adres: str) -> dict | None:
    global _pdok_sem
    if _pdok_sem is None:
        _pdok_sem = asyncio.Semaphore(_PDOK_CONCURRENCY)
    async with _pdok_sem:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            r = await client.get(PDOK_URL, params={"q": adres, "rows": 1, "fq": "type:adres"})
            r.raise_for_status()
            docs = (r.json().get("response") or {}).get("docs") or []
    return _parse_doc(docs[0]) if docs else None


def _flush_chunk_sync(rows: list[dict]) -> None:
    get_db().table("geocode_cache").upsert(rows, on_conflict="cache_key").execute()


def _flush_rows_sync(rows: list[dict], *, reason: str) -> tuple[int, int]:
    if not rows:
        return 0, 0

    ok = fail = 0
    for i in range(0, len(rows), _FLUSH_CHUNK):
        chunk = rows[i : i + _FLUSH_CHUNK]
        last_err: Exception | None = None
        for attempt in range(_FLUSH_RETRY_ATTEMPTS):
            try:
                _flush_chunk_sync(chunk)
                ok += len(chunk)
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt + 1 < _FLUSH_RETRY_ATTEMPTS:
                    time.sleep(min(2 ** attempt, 8))
        if last_err is not None:
            fail += len(chunk)
            logger.warning(
                f"[geocode] flush chunk mislukt ({len(chunk)} rijen, {reason}): {last_err}"
            )
            _requeue_failed(chunk)

    if reason == "backpressure":
        _stats["flush_backpressure"] += ok
    elif reason == "periodic":
        _stats["flush_periodic"] += ok

    return ok, fail


def _flush_daemon_loop() -> None:
    while not _daemon_stop.wait(_FLUSH_INTERVAL_SEC):
        rows = _take_flush_batch()
        if not rows:
            continue
        ok, fail = _flush_rows_sync(rows, reason="periodic")
        if ok or fail:
            logger.info(
                f"[geocode] periodic flush ok={ok} fail={fail} retry_pending={_pending_retry_len()}",
                flush=True,
            )


def _pending_retry_len() -> int:
    with _lock:
        return len(_retry_rows) + len(_pending_rows)


async def _resolve_uncached(adres: str, norm_key: str) -> dict | None:
    _stats["pdok_calls"] += 1
    try:
        result = await _pdok_lookup(adres)
    except Exception as e:
        logger.warning(f"[geocode] PDOK-fout voor {adres!r}: {e}")
        return None

    keys = _keys_for_result(norm_key, result)
    overflow = False
    with _lock:
        overflow = _store_in_memory(keys, adres, result)

    if overflow:
        await _schedule_backpressure_flush()
    return result


def _flush_pending_sync(reason: str) -> None:
    rows = _take_flush_batch()
    if not rows:
        return
    ok, fail = _flush_rows_sync(rows, reason=reason)
    if ok or fail:
        logger.info(
            f"[geocode] {reason} flush ok={ok} fail={fail} retry_pending={_pending_retry_len()}",
            flush=True,
        )


async def _schedule_backpressure_flush() -> None:
    await asyncio.to_thread(_flush_pending_sync, "backpressure")


async def geocode(adres: str) -> dict | None:
    """
    Geocode via in-memory cache + PDOK. Supabase niet per aanroep.
    Gelijktijdige aanroepen voor hetzelfde adres delen één PDOK-call.
    """
    if not adres or not adres.strip():
        return None

    norm_key, input_pc_hnr = _lookup_keys(adres)
    keys = list(dict.fromkeys(k for k in (input_pc_hnr, norm_key) if k))

    task: asyncio.Task | None = None
    with _lock:
        hit = _memory_get(keys)
        if hit is not _MISS:
            _stats["memory_hit"] += 1
            return hit

        now = time.time()
        entry = _inflight.get(norm_key)
        if entry and now - entry["ts"] > INFLIGHT_STALE_SEC:
            _cancel_inflight_entry(_inflight.pop(norm_key, None))
            entry = None

        if entry:
            _stats["coalesced"] += 1
            task = entry["task"]
        else:
            _inflight_safety_prune()
            task = asyncio.create_task(_resolve_uncached(adres, norm_key))
            _inflight[norm_key] = {"task": task, "ts": now}

    try:
        return await task
    finally:
        with _lock:
            _inflight.pop(norm_key, None)


async def flush_geocode_cache() -> None:
    """Flush retry-queue + pending naar Supabase (einde run of vóór nieuwe run)."""
    rows = await asyncio.to_thread(_take_flush_batch)
    if not rows:
        logger.info(
            "[geocode] cache_hit=%s pdok_calls=%s coalesced=%s buffered=0 flush=0 retry_pending=0",
            _stats["memory_hit"],
            _stats["pdok_calls"],
            _stats["coalesced"],
            flush=True,
        )
        return

    ok, fail = await asyncio.to_thread(_flush_rows_sync, rows, reason="run_end")
    _stats["flush_ok"] = ok
    _stats["flush_fail"] = fail
    logger.info(
        "[geocode] cache_hit=%s pdok_calls=%s coalesced=%s flush_ok=%s flush_fail=%s "
        "retry_requeued=%s backpressure=%s periodic=%s retry_pending=%s",
        _stats["memory_hit"],
        _stats["pdok_calls"],
        _stats["coalesced"],
        ok,
        fail,
        _stats["retry_requeued"],
        _stats["flush_backpressure"],
        _stats["flush_periodic"],
        await asyncio.to_thread(_pending_retry_len),
        flush=True,
    )
