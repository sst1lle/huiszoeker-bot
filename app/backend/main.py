"""Huiszoeker bot — async entrypoint."""
import asyncio
import os

from dotenv import load_dotenv

from shared.geocoder import ensure_geocode_flush_daemon
from storage import ListingStorage
from validation import valideer_schema
from pipeline import (
    INTERVAL,
    SCHEDULER_POLL_SEC,
    load_scrapers,
    registreer_scrapers,
    scheduler_loop,
    verrijk_met_geocoding,
)

os.environ["PYTHONUNBUFFERED"] = "1"
load_dotenv()

# Backward compat (admin.py: from main import ...)
__all__ = [
    "INTERVAL",
    "SCHEDULER_POLL_SEC",
    "load_scrapers",
    "registreer_scrapers",
    "verrijk_met_geocoding",
    "scheduler_loop",
]


if __name__ == "__main__":
    print("🏠 Huiszoekerbot gestart", flush=True)
    ensure_geocode_flush_daemon()
    valideer_schema()

    alle_scrapers = load_scrapers()
    if not alle_scrapers:
        print("[main] ❌ Geen scrapers gevonden — stop.", flush=True)
        raise SystemExit(1)

    registreer_scrapers(alle_scrapers)
    storage = ListingStorage()
    nieuwbouw_scrapers = [
        s for s in alle_scrapers if getattr(s, "category", "") == "nieuwbouw"
    ]
    print(
        f"[main] Scheduler-gateway actief — nieuwbouw: {[s.name for s in nieuwbouw_scrapers]}, "
        f"realtime: {[s.name for s in alle_scrapers if s not in nieuwbouw_scrapers]}",
        flush=True,
    )
    print(
        f"[main] Async daemon loop (poll elke {SCHEDULER_POLL_SEC}s, "
        f"scrape-interval {INTERVAL // 60}m via next_run_at)",
        flush=True,
    )

    asyncio.run(scheduler_loop(alle_scrapers, nieuwbouw_scrapers, storage))
