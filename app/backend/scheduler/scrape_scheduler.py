"""
Centrale scraper-scheduler — single source of truth = next_run_at (UTC).

Twee tiers:
  - nieuwbouw (heavy):  1x per week, anker maandag 05:00 Europe/Amsterdam (als UTC opgeslagen)
  - realtime (light):   minimaal elke 7 minuten

Regels:
  should_run(name)  → True alleen als geen actieve lock én now_utc >= next_run_at
  run_scraper(name, execute_fn) → enige ingang: gate → TTL-lock → execute_fn → record uitkomst
  record_run(name, status, run_id) → success = +interval (anchor-based), failure = +backoff
  acquire_lock/release_lock → TTL-locks in scrape_locks (crash-safe via expiry)

Crash-safe: locks vervallen vanzelf (TTL). Geen pg advisory locks (Supabase is REST).
Alle tijden in UTC; alleen het maandag-05:00 anker wordt lokaal (Amsterdam) berekend.
"""
import os
import uuid
import sys
import logging
import contextvars
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from db import get_db

logger = logging.getLogger(__name__)
# Scheduler-beslissingen moeten zichtbaar zijn in docker logs (de rest van de app print
# naar stdout en er is geen globale logging-config). Eigen stdout-handler op INFO.
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False

_AMS = ZoneInfo("Europe/Amsterdam")

# Scraper-tiers
NIEUWBOUW_SCRAPERS = {"nieuwbouw_nederland", "nieuwbouw_nl"}

# Intervallen / backoff / lock-TTL per tier
REALTIME_INTERVAL = timedelta(minutes=7)
REALTIME_BACKOFF  = timedelta(minutes=30)
REALTIME_LOCK_TTL = timedelta(minutes=20)
NIEUWBOUW_INTERVAL = timedelta(days=7)
NIEUWBOUW_BACKOFF  = timedelta(hours=2)
NIEUWBOUW_LOCK_TTL = timedelta(hours=6)

# Context-flag: True binnen run_scraper → publieke scrape() mag draaien (zie BaseScraper-guard)
_SCHED_CTX: contextvars.ContextVar = contextvars.ContextVar("scheduler_active", default=False)


def in_scheduler_context() -> bool:
    return _SCHED_CTX.get()


def is_nieuwbouw(name: str) -> bool:
    return name in NIEUWBOUW_SCRAPERS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _maandag_0500_utc(na: datetime | None = None) -> datetime:
    """Eerstvolgende maandag 05:00 Europe/Amsterdam ná `na`, teruggegeven als UTC."""
    base = (na or _now()).astimezone(_AMS)
    anchor = base.replace(hour=5, minute=0, second=0, microsecond=0)
    days_ahead = (0 - anchor.weekday()) % 7  # 0 = maandag
    cand = anchor + timedelta(days=days_ahead)
    if cand <= base:
        cand += timedelta(days=7)
    return cand.astimezone(timezone.utc)


def _initial_next(name: str) -> datetime:
    return _maandag_0500_utc() if is_nieuwbouw(name) else _now()


def _get_run(name: str) -> dict | None:
    try:
        rows = get_db().table("scrape_runs").select("*").eq("scraper_name", name).limit(1).execute().data
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"[SCHEDULER] scrape_runs lees-fout voor {name} ({e})")
        return None


def _lock_until(name: str) -> datetime | None:
    rows = get_db().table("scrape_locks").select("lock_until").eq("scraper_name", name).limit(1).execute().data
    return _parse(rows[0]["lock_until"]) if rows else None


def _lock_actief(name: str) -> bool:
    try:
        lu = _lock_until(name)
        return bool(lu and lu > _now())
    except Exception as e:
        logger.warning(f"[SCHEDULER] scrape_locks lees-fout voor {name} ({e})")
        return True  # fail-closed: bij twijfel niet draaien (voorkomt storm)


def _upsert_run(name: str, fields: dict) -> None:
    try:
        row = {"scraper_name": name, "updated_at": _now().isoformat(), **fields}
        get_db().table("scrape_runs").upsert(row, on_conflict="scraper_name").execute()
    except Exception as e:
        logger.warning(f"[SCHEDULER] scrape_runs schrijf-fout voor {name} ({e})")


def should_run(name: str) -> bool:
    """True alleen als er geen actieve lock is én now_utc >= next_run_at."""
    if _lock_actief(name):
        logger.info(f"[SCHEDULER] Skipped scraper={name} reason=lock_active")
        return False

    run = _get_run(name)
    nxt = _parse(run.get("next_run_at")) if run else None
    if nxt is None:
        nxt = _initial_next(name)
        _upsert_run(name, {"next_run_at": nxt.isoformat()})  # initialiseer schedule

    if _now() >= nxt:
        logger.info(f"[SCHEDULER] Allowed scraper={name} (next_run_at={nxt.isoformat()})")
        return True
    logger.info(f"[SCHEDULER] Skipped scraper={name} reason=not_due (next_run_at={nxt.isoformat()})")
    return False


def record_run(name: str, status: str, run_id: str | None = None) -> None:
    """
    Leg de run vast en bepaal next_run_at, gesplitst op uitkomst:
      success → +interval (nieuwbouw anchor-based +7d, realtime now+15m)
      failure → +backoff  (nieuwbouw +2u, realtime +30m)
    """
    now = _now()
    run = _get_run(name) or {}
    old_next = _parse(run.get("next_run_at"))

    if status == "ok":
        if is_nieuwbouw(name):
            base = old_next or _maandag_0500_utc(now)
            nxt = base + NIEUWBOUW_INTERVAL
            while nxt <= now:                      # gemiste runs doorschuiven, anker behouden
                nxt += NIEUWBOUW_INTERVAL
        else:
            nxt = now + REALTIME_INTERVAL
    else:  # failure → backoff (geen schedule-verlies, geen retry-storm)
        nxt = now + (NIEUWBOUW_BACKOFF if is_nieuwbouw(name) else REALTIME_BACKOFF)

    _upsert_run(name, {
        "last_run_at": now.isoformat(),
        "next_run_at": nxt.isoformat(),
        "status": status,
        "run_id": run_id or str(uuid.uuid4()),
    })
    logger.info(f"[SCHEDULER] recorded scraper={name} status={status} next_run_at={nxt.isoformat()}")


def acquire_lock(name: str) -> bool:
    """
    Atomaire TTL-lock: neem een verlopen lock over (UPDATE … WHERE lock_until < now),
    anders INSERT een nieuwe; een unique-violation betekent een actieve lock → False.
    """
    now = _now()
    ttl = NIEUWBOUW_LOCK_TTL if is_nieuwbouw(name) else REALTIME_LOCK_TTL
    until = (now + ttl).isoformat()
    db = get_db()
    try:
        taken = db.table("scrape_locks").update({"lock_until": until}) \
                  .eq("scraper_name", name).lt("lock_until", now.isoformat()).execute()
        if taken.data:
            return True  # verlopen lock overgenomen
        db.table("scrape_locks").insert({"scraper_name": name, "lock_until": until}).execute()
        return True      # nieuwe lock
    except Exception:
        return False     # actieve lock (unique violation) of DB-fout → niet draaien


def release_lock(name: str) -> None:
    try:
        get_db().table("scrape_locks").delete().eq("scraper_name", name).execute()
    except Exception as e:
        logger.warning(f"[SCHEDULER] release_lock-fout voor {name} ({e}); TTL ruimt op")


@contextmanager
def scraper_lock(name: str):
    got = acquire_lock(name)
    try:
        yield got
    finally:
        if got:
            release_lock(name)


def run_scraper(name: str, execute_fn):
    """
    Enige ingang om een scraper te draaien. Gate → TTL-lock → execute_fn() → record.
    execute_fn() voert het echte werk uit (scraper._scrape_impl + verwerking) en geeft
    een resultaat terug dat hier wordt doorgegeven (of None bij skip/fout).
    """
    forced = os.getenv("FORCE_SCRAPE") == "true"
    if not forced and not should_run(name):
        return None  # should_run logt de reden al

    with scraper_lock(name) as got:
        if not got:
            logger.info(f"[SCHEDULER] Skipped scraper={name} reason=lock_active")
            return None
        run_id = str(uuid.uuid4())
        logger.info(f"[SCHEDULER] Running scraper={name} run_id={run_id}")
        token = _SCHED_CTX.set(True)
        try:
            result = execute_fn()
            record_run(name, "ok", run_id)
            return result
        except Exception as e:
            logger.error(f"[SCHEDULER] scraper={name} fout: {e}")
            record_run(name, "failed", run_id)
            return None
        finally:
            _SCHED_CTX.reset(token)


def status_info(name: str, enabled: bool = True) -> dict:
    """Status + reden voor /scheduler/status."""
    run = _get_run(name) or {}
    now = _now()
    try:
        lock = _lock_until(name)
    except Exception:
        lock = None
    lock_active = bool(lock and lock > now)
    nxt = _parse(run.get("next_run_at"))

    if not enabled:
        state, reason = "blocked", "forced_disabled"
    elif lock_active:
        state, reason = "blocked", "lock_active"
    elif nxt and now < nxt:
        state, reason = "blocked", "not_due"
    else:
        state, reason = "due", None

    return {
        "scraper_name": name,
        "last_run_at": run.get("last_run_at"),
        "next_run_at": run.get("next_run_at"),
        "lock_until": lock.isoformat() if lock else None,
        "status": run.get("status"),
        "state": state,
        "reason": reason,
    }
