"""Listing URL-validatie + scraper_config schema/migratie checks."""
import asyncio
import requests
from datetime import datetime, timezone, timedelta

from db import get_db
from listings_db import UPSERT_BATCH

VALIDATIE_INTERVAL_UREN = 6
_VALIDATIE_CONCURRENCY = 15
_VALIDATIE_UPSERT_BATCH = 100

_MIGRATION_WARNED = False
_SCRAPER_CONFIG_NEW_COLS = {"category", "status", "error_message"}
_MIGRATION_FILE = "supabase/migrations/003_scraper_categories.sql"


def log_migration_warning() -> None:
    global _MIGRATION_WARNED
    if not _MIGRATION_WARNED:
        print(
            f"[schema] ⚠️  scraper_config mist kolommen — voer uit in Supabase SQL Editor:\n"
            f"[schema]    {_MIGRATION_FILE}",
            flush=True,
        )
        _MIGRATION_WARNED = True


def safe_scraper_update(db, name: str, data: dict) -> None:
    """
    Update scraper_config row. Bij PGRST204 (ontbrekende kolommen): val terug op
    alleen last_run/last_count zodat de bot blijft draaien vóór de migratie.
    """
    try:
        db.table("scraper_config").update(data).eq("name", name).execute()
    except Exception as e:
        if "PGRST204" in str(e):
            log_migration_warning()
            safe = {k: v for k, v in data.items() if k in ("last_run", "last_count", "enabled")}
            if safe:
                try:
                    db.table("scraper_config").update(safe).eq("name", name).execute()
                except Exception:
                    pass
        else:
            raise


def valideer_schema() -> None:
    """
    Controleert of scraper_config de verwachte kolommen heeft.
    Logt een duidelijke migratie-waarschuwing als dat niet zo is.
    Crasht nooit — louter informatief.
    """
    try:
        db = get_db()
        rows = db.table("scraper_config").select("*").limit(1).execute().data
        if rows:
            aanwezig = set(rows[0].keys())
            ontbrekend = _SCRAPER_CONFIG_NEW_COLS - aanwezig
            if ontbrekend:
                print(
                    f"[schema] ⚠️  Ontbrekende kolommen in scraper_config: {sorted(ontbrekend)}\n"
                    f"[schema]    Voer uit in Supabase SQL Editor: {_MIGRATION_FILE}",
                    flush=True,
                )
        else:
            print("[schema] scraper_config leeg — scrapers worden bij botstart geregistreerd", flush=True)
    except Exception as e:
        print(f"[schema] Kon schema niet valideren: {e}", flush=True)


def _url_nog_online(url: str) -> bool:
    """True = listing nog beschikbaar (geen 404). Netwerkfout → niet als vervallen markeren."""
    try:
        r = requests.get(
            url, timeout=10, allow_redirects=True, stream=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        return r.status_code != 404
    except Exception:
        return True


def _valideer_listings_sync(listings: list[dict], nu: str) -> tuple[int, int]:
    """Fallback zonder event loop: sequentiële HTTP-checks + batch upsert op id."""
    db = get_db()
    vervallen = 0
    checks = [(lst["id"], _url_nog_online(lst["url"])) for lst in listings]
    return _valideer_listings_persist(db, listings, checks, nu, vervallen)


def _valideer_listings_persist(
    db, listings: list[dict], checks: list[tuple], nu: str, vervallen: int,
) -> tuple[int, int]:
    ids = [lst["id"] for lst in listings]
    by_id: dict = {}
    for i in range(0, len(ids), UPSERT_BATCH):
        chunk = ids[i : i + UPSERT_BATCH]
        for row in db.table("listings").select("*").in_("id", chunk).execute().data or []:
            by_id[row["id"]] = row

    rows = []
    for lid, nog_online in checks:
        row = dict(by_id[lid])
        row["laatst_gevalideerd"] = nu
        if not nog_online:
            row["beschikbaar"] = False
            vervallen += 1
        rows.append(row)

    for i in range(0, len(rows), _VALIDATIE_UPSERT_BATCH):
        db.table("listings").upsert(
            rows[i : i + _VALIDATIE_UPSERT_BATCH], on_conflict="id",
        ).execute()

    print(
        f"[validatie] {vervallen} vervallen, {len(listings) - vervallen} nog online",
        flush=True,
    )
    return len(listings), vervallen


async def valideer_listings():
    """Check listings die lang niet gevalideerd zijn. Markeert 404's als beschikbaar=False."""
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=VALIDATIE_INTERVAL_UREN)).isoformat()

    result = (
        db.table("listings")
        .select("id, url")
        .eq("beschikbaar", True)
        .lt("laatst_gevalideerd", cutoff)
        .execute()
    )
    listings = result.data or []

    if not listings:
        return 0, 0

    print(f"[validatie] {len(listings)} listings te valideren", flush=True)
    nu = datetime.now(timezone.utc).isoformat()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _valideer_listings_sync(listings, nu)

    sem = asyncio.Semaphore(_VALIDATIE_CONCURRENCY)

    async def _check_one(lst: dict) -> tuple:
        async with sem:
            ok = await asyncio.to_thread(_url_nog_online, lst["url"])
        return lst["id"], ok

    checks = await asyncio.gather(*(_check_one(lst) for lst in listings))
    return _valideer_listings_persist(db, listings, checks, nu, 0)
