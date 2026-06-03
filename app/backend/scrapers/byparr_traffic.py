"""
Byparr traffic controller — enige entrypoint voor scrapers.

Load shaping: queue, concurrency caps, min gap, backpressure, circuit breakers.
HTTP/health/retry: delegeert naar byparr_client.fetch() (geen dubbele retry in queue).
"""
from __future__ import annotations

import os
import re
import time
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from queue import Queue, Empty
from urllib.parse import urlparse

from .byparr_client import (
    ByparrError,
    ByparrFailureKind,
    ByparrUnavailable,
    byparr_health_check,
    fetch as _client_fetch,
)

logger = logging.getLogger(__name__)

BYPARR_MAX_INFLIGHT = int(os.getenv("BYPARR_MAX_INFLIGHT", "1"))
BYPARR_QUEUE_WORKERS = int(os.getenv("BYPARR_QUEUE_WORKERS", "1"))
BYPARR_MIN_GAP_SEC = float(os.getenv("BYPARR_MIN_GAP_SEC", "3"))
BYPARR_500_BACKOFF_SEC = float(os.getenv("BYPARR_500_BACKOFF_SEC", "20"))
BYPARR_QUEUE_HIGH_WATER = int(os.getenv("BYPARR_QUEUE_HIGH_WATER", "10"))
BYPARR_QUEUE_HIGH_SLEEP = float(os.getenv("BYPARR_QUEUE_HIGH_SLEEP", "2"))
BYPARR_CIRCUIT_FAILURES = int(os.getenv("BYPARR_CIRCUIT_FAILURES", "5"))
BYPARR_CIRCUIT_OPEN_SEC = int(os.getenv("BYPARR_CIRCUIT_OPEN_SEC", "60"))
BYPARR_DEGRADED_MAX_PAGES = int(os.getenv("BYPARR_DEGRADED_MAX_PAGES", "1"))
BYPARR_JOB_TIMEOUT_SEC = float(os.getenv("BYPARR_JOB_TIMEOUT_SEC", "120"))

_SCRAPER_CAPS: dict[str, int] = {
    "funda": int(os.getenv("BYPARR_CAP_FUNDA", "1")),
    "pararius": int(os.getenv("BYPARR_CAP_PARARIUS", "1")),
    "kamernet": int(os.getenv("BYPARR_CAP_KAMERNET", "2")),
    "nieuwbouw_nederland": int(os.getenv("BYPARR_CAP_NIEUWBOUW", "1")),
    "nieuwbouw_nl": int(os.getenv("BYPARR_CAP_NIEUWBOUW", "1")),
}


@dataclass
class _Job:
    target_url: str
    scraper: str
    route: str
    page_hint: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    result: str | None = None
    error: ByparrError | None = None


class _Circuit:
    failures: int = 0
    open_until: float = 0.0


_lock = threading.Lock()
_queue: Queue[_Job] = Queue()
_global_sem = threading.Semaphore(BYPARR_MAX_INFLIGHT)
_scraper_sems: dict[str, threading.Semaphore] = {}
_scraper_circuits: dict[str, _Circuit] = defaultdict(_Circuit)
_route_circuits: dict[str, _Circuit] = defaultdict(_Circuit)
_backpressure_until: float = 0.0
_last_request_end: float = 0.0
_workers_started = False


def route_key(scraper: str, url: str) -> str:
    path = urlparse(url).path.strip("/")
    parts = [p for p in path.split("/") if p]
    if scraper == "pararius" and len(parts) >= 2 and parts[0] == "huurwoningen":
        stad = parts[1]
        if re.fullmatch(r"page-\d+", stad) and len(parts) > 2:
            stad = parts[2]
        return f"pararius:huurwoningen:{stad.lower()}"
    if scraper == "funda" and "huur" in parts:
        return "funda:zoeken:huur"
    if parts:
        return f"{scraper}:{':'.join(parts[:3]).lower()}"
    return f"{scraper}:root"


def is_scraper_degraded(scraper: str) -> bool:
    c = _scraper_circuits[scraper]
    with _lock:
        return time.monotonic() < c.open_until


def is_route_blocked(scraper: str, url: str) -> bool:
    with _lock:
        return time.monotonic() < _route_circuits[route_key(scraper, url)].open_until


def effective_max_pages(scraper: str, default_max: int) -> int:
    if is_scraper_degraded(scraper):
        return min(default_max, BYPARR_DEGRADED_MAX_PAGES)
    return default_max


def _scraper_sem(scraper: str) -> threading.Semaphore:
    cap = _SCRAPER_CAPS.get(scraper, int(os.getenv("BYPARR_CAP_DEFAULT", "1")))
    with _lock:
        if scraper not in _scraper_sems:
            _scraper_sems[scraper] = threading.Semaphore(cap)
        return _scraper_sems[scraper]


def _backpressure_active() -> bool:
    with _lock:
        return time.monotonic() < _backpressure_until


def _ensure_workers() -> None:
    global _workers_started
    with _lock:
        if _workers_started:
            return
        _workers_started = True
        for i in range(BYPARR_QUEUE_WORKERS):
            threading.Thread(target=_worker_loop, name=f"byparr-queue-{i}", daemon=True).start()
        logger.info(
            f"[byparr-tc] started workers={BYPARR_QUEUE_WORKERS} "
            f"max_inflight={BYPARR_MAX_INFLIGHT} min_gap={BYPARR_MIN_GAP_SEC}s",
        )


def _wait_shaping() -> None:
    global _last_request_end
    while _queue.qsize() > BYPARR_QUEUE_HIGH_WATER:
        logger.info(
            f"[byparr-tc] queue_size={_queue.qsize()} backpressure_active=true "
            f"shaping sleep={BYPARR_QUEUE_HIGH_SLEEP}s",
        )
        time.sleep(BYPARR_QUEUE_HIGH_SLEEP)

    now = time.monotonic()
    with _lock:
        wait_until = max(_backpressure_until, _last_request_end + BYPARR_MIN_GAP_SEC)
    delay = wait_until - now
    if delay > 0:
        logger.info(
            f"[byparr-tc] shaping sleep={delay:.1f}s backpressure_active={_backpressure_active()}",
        )
        time.sleep(delay)


def _trigger_backpressure(reason: str) -> None:
    global _backpressure_until
    with _lock:
        _backpressure_until = max(_backpressure_until, time.monotonic() + BYPARR_500_BACKOFF_SEC)
    logger.warning(f"[byparr-tc] global cooldown {BYPARR_500_BACKOFF_SEC}s — {reason}")


def _preflight(scraper: str, url: str) -> str:
    rk = route_key(scraper, url)
    if is_scraper_degraded(scraper):
        raise ByparrError(ByparrFailureKind.DEGRADED, f"{scraper} degraded (circuit)")
    with _lock:
        if time.monotonic() < _route_circuits[rk].open_until:
            raise ByparrError(
                ByparrFailureKind.ROUTE_BLOCKED,
                f"route {rk} paused",
            )
        if time.monotonic() < _scraper_circuits[scraper].open_until:
            raise ByparrError(
                ByparrFailureKind.CIRCUIT_OPEN,
                f"{scraper} circuit open",
            )
    return rk


def _circuit_ok(scraper: str, route: str) -> None:
    with _lock:
        _scraper_circuits[scraper].failures = 0
        _route_circuits[route].failures = 0


def _circuit_fail(scraper: str, route: str) -> None:
    now = time.monotonic()
    with _lock:
        for key, store in ((scraper, _scraper_circuits), (route, _route_circuits)):
            c = store[key]
            c.failures += 1
            if c.failures >= BYPARR_CIRCUIT_FAILURES:
                c.open_until = now + BYPARR_CIRCUIT_OPEN_SEC
                logger.warning(
                    f"[byparr-tc] circuit open key={key} failures={c.failures} "
                    f"pause={BYPARR_CIRCUIT_OPEN_SEC}s",
                )


def _tc_log(
    *,
    scraper: str,
    route: str,
    outcome: str,
    latency_ms: int,
    queue_size: int,
    retry_in_client: bool,
    backpressure_active: bool,
    page_hint: str = "",
    extra: str = "",
) -> None:
    msg = (
        f"[byparr-tc] scraper={scraper} route={route} outcome={outcome} "
        f"latency_ms={latency_ms} queue_size={queue_size} "
        f"retry_in_client={retry_in_client} backpressure_active={backpressure_active}"
    )
    if page_hint:
        msg += f" page={page_hint}"
    if extra:
        msg += f" {extra}"
    if outcome == "ok":
        logger.info(msg)
    else:
        logger.warning(msg)


def _execute_job(job: _Job) -> None:
    """Eén client.fetch() per job — alle retries zitten in de client."""
    global _last_request_end
    scraper, route = job.scraper, job.route
    qs = _queue.qsize()

    _wait_shaping()
    t0 = time.monotonic()
    bp = _backpressure_active()

    with _global_sem:
        with _scraper_sem(scraper):
            try:
                html = _client_fetch(job.target_url, scraper=scraper)
                latency_ms = int((time.monotonic() - t0) * 1000)
                _circuit_ok(scraper, route)
                _tc_log(
                    scraper=scraper,
                    route=route,
                    outcome="ok",
                    latency_ms=latency_ms,
                    queue_size=qs,
                    retry_in_client=True,
                    backpressure_active=bp,
                    page_hint=job.page_hint,
                )
                job.result = html
                return
            except ByparrError as e:
                job.error = e
            except Exception as e:
                job.error = ByparrError(ByparrFailureKind.UNKNOWN, str(e))

    _last_request_end = time.monotonic()
    latency_ms = int((time.monotonic() - t0) * 1000)
    err = job.error
    outcome = err.kind.value if err else "unknown"

    if err and err.kind == ByparrFailureKind.UPSTREAM_HTTP:
        _trigger_backpressure(f"HTTP {err.status} scraper={scraper}")
    if err and err.kind != ByparrFailureKind.UNAVAILABLE:
        _circuit_fail(scraper, route)

    _tc_log(
        scraper=scraper,
        route=route,
        outcome=outcome,
        latency_ms=latency_ms,
        queue_size=qs,
        retry_in_client=True,
        backpressure_active=_backpressure_active(),
        page_hint=job.page_hint,
        extra=f"msg={err}",
    )
    logger.warning(
        f"[byparr-tc] failed_job scraper={scraper} route={route} "
        f"page={job.page_hint or job.target_url[:80]} reason={outcome}",
    )


def _worker_loop() -> None:
    while True:
        try:
            job = _queue.get(timeout=1.0)
        except Empty:
            continue
        try:
            _execute_job(job)
        finally:
            job.done.set()
            _queue.task_done()


def submit(
    target_url: str,
    *,
    scraper: str = "unknown",
    page_hint: str = "",
    queue_timeout: float | None = None,
) -> str:
    """
    Enige publieke entrypoint: enqueue → shape → client.fetch().
    """
    route = _preflight(scraper, target_url)
    _ensure_workers()

    job = _Job(
        target_url=target_url,
        scraper=scraper,
        route=route,
        page_hint=page_hint,
    )
    _queue.put(job)

    timeout = queue_timeout if queue_timeout is not None else BYPARR_JOB_TIMEOUT_SEC
    if not job.done.wait(timeout=timeout):
        raise ByparrError(ByparrFailureKind.TIMEOUT, f"queue job timeout ({timeout}s)")

    if job.error:
        raise job.error
    if job.result is None:
        raise ByparrError(ByparrFailureKind.UNKNOWN, "geen resultaat")
    return job.result


# Backwards-compatible alias
fetch = submit


__all__ = [
    "ByparrError",
    "ByparrFailureKind",
    "ByparrUnavailable",
    "byparr_health_check",
    "submit",
    "fetch",
    "route_key",
    "is_scraper_degraded",
    "is_route_blocked",
    "effective_max_pages",
]
