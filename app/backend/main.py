import os
import time
import asyncio
import importlib
import inspect
import pkgutil
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from telegram import Bot
from db import get_db
from crypto import safe_decrypt  # PRIVACY-FIX: decrypt PII fields before use
from scrapers.base import BaseScraper
from deduplicator import Deduplicator
from storage import ListingStorage
from shared.geocoder import geocode
from shared.cities import normalize_city_name, stad_voor_db, stad_slugs_uit_pref
from shared.wijken import stad_db_variants
from scrape_plan import bouw_scrape_taken, taken_per_scraper
from scheduler.scrape_scheduler import run_scraper

os.environ['PYTHONUNBUFFERED'] = '1'
load_dotenv()

INTERVAL = 7 * 60
VALIDATIE_INTERVAL_UREN = 6

# Eenmalige waarschuwing zodat migratie-berichten het log niet overspoelen
_MIGRATION_WARNED = False
# Kolommen die aanwezig moeten zijn in scraper_config na migratie 003
_SCRAPER_CONFIG_NEW_COLS = {"category", "status", "error_message"}
_MIGRATION_FILE = "supabase/migrations/003_scraper_categories.sql"


def _log_migration_warning() -> None:
    global _MIGRATION_WARNED
    if not _MIGRATION_WARNED:
        print(
            f"[schema] ⚠️  scraper_config mist kolommen — voer uit in Supabase SQL Editor:\n"
            f"[schema]    {_MIGRATION_FILE}",
            flush=True,
        )
        _MIGRATION_WARNED = True


def _safe_scraper_update(db, name: str, data: dict) -> None:
    """
    Update scraper_config row. Bij PGRST204 (ontbrekende kolommen): val terug op
    alleen last_run/last_count zodat de bot blijft draaien vóór de migratie.
    """
    try:
        db.table("scraper_config").update(data).eq("name", name).execute()
    except Exception as e:
        if "PGRST204" in str(e):
            _log_migration_warning()
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


def load_scrapers() -> list:
    """
    Auto-discover alle BaseScraper subklassen in app/scrapers/.

    Nieuwe scraper toevoegen = nieuw bestand droppen in app/scrapers/ met een
    klasse die BaseScraper erft. main.py hoeft nooit gewijzigd te worden.

    base.py wordt overgeslagen. Laadfouten worden gelogd maar stoppen de bot niet.
    """
    import scrapers as scrapers_pkg

    gevonden = []
    for _, module_name, _ in pkgutil.iter_modules(scrapers_pkg.__path__):
        if module_name == "base":
            continue
        try:
            module = importlib.import_module(f"scrapers.{module_name}")
        except Exception as e:
            print(f"[scrapers] Kon '{module_name}' niet laden: {e}", flush=True)
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, BaseScraper) and cls is not BaseScraper:
                gevonden.append(cls())

    print(f"[scrapers] {len(gevonden)} scraper(s) geladen: {[s.name for s in gevonden]}", flush=True)
    return gevonden


async def stuur_telegram(chat_id: str, bericht: str):
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    try:
        await bot.send_message(chat_id=chat_id, text=bericht)
    except Exception as e:
        print(f"[telegram] Fout voor {chat_id}: {e}", flush=True)


async def stuur_warning(bericht: str):
    chat_id = os.getenv('ADMIN_CHAT_ID', '').strip()
    if not chat_id:
        return
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    try:
        await bot.send_message(chat_id=chat_id, text=bericht)
    except Exception as e:
        print(f"[telegram] Warning fout: {e}", flush=True)


def valideer_listings():
    """Check listings die lang niet gevalideerd zijn. Markeert 404's als beschikbaar=False."""
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=VALIDATIE_INTERVAL_UREN)).isoformat()

    result = db.table("listings").select("id, url").eq("beschikbaar", True).lt("laatst_gevalideerd", cutoff).execute()
    listings = result.data or []

    if not listings:
        return 0, 0

    print(f"[validatie] {len(listings)} listings te valideren", flush=True)
    vervallen = 0
    nu = datetime.now(timezone.utc).isoformat()

    for listing in listings:
        try:
            r = requests.get(listing["url"], timeout=10, allow_redirects=True, stream=True,
                             headers={"User-Agent": "Mozilla/5.0"})
            beschikbaar = r.status_code != 404
        except Exception:
            beschikbaar = True  # netwerk fout: niet als vervallen markeren

        update = {"laatst_gevalideerd": nu}
        if not beschikbaar:
            update["beschikbaar"] = False
            vervallen += 1

        db.table("listings").update(update).eq("id", listing["id"]).execute()

    print(f"[validatie] {vervallen} vervallen, {len(listings) - vervallen} nog online", flush=True)
    return len(listings), vervallen


# Kolommen die bestaan in de Supabase listings tabel.
# Scraper-output kan extra velden bevatten (omschrijving, rating, scraped_at, ...)
# die alleen naar de Parquet datalake gaan. Deze whitelist voorkomt dat nieuwe
# scraper-velden de Supabase insert breken.
_SUPABASE_LISTING_FIELDS = {
    "source", "external_id", "url", "adres", "stad",
    "prijs", "oppervlakte", "type_woning", "foto_url", "beschikbaar",
    "postcode", "wijk", "buurt", "lat", "lng",
}


def upsert_listing(listing: dict) -> str | None:
    """Insert nieuwe listing of update bestaande als hij onvolledig is (migratiestub). Geeft UUID terug."""
    if not listing.get("prijs"):
        return None  # listing zonder prijs is niet bruikbaar voor matching

    db = get_db()

    bestaand = (db.table("listings")
                .select("id, beschikbaar, prijs, postcode, wijk, buurt, lat, lng")
                .eq("url", listing["url"]).execute())

    if bestaand.data:
        record = bestaand.data[0]
        nu = datetime.now(timezone.utc).isoformat()
        scrape_beschikbaar = listing.get("beschikbaar", True)
        updates = {"laatst_gevalideerd": nu, "beschikbaar": scrape_beschikbaar}
        # Vul ontbrekende velden in — migratiestubs hebben prijs/stad/adres=None
        if not record.get("prijs"):
            for field in ("adres", "prijs", "oppervlakte", "type_woning", "foto_url"):
                if listing.get(field) is not None:
                    updates[field] = listing[field]
            if listing.get("stad") is not None:
                updates["stad"] = stad_voor_db(listing["stad"]) or listing["stad"]
        # Geo-velden + stad verversen zodra deze listing dit run succesvol gegeocode is.
        # NB: street-level matches (bv. "Straat, Delft" zonder huisnummer) hebben géén postcode
        # maar wél stad/wijk/coördinaten → die willen we óók verwerken; daarom NIET op postcode gaten.
        if any(listing.get(f) is not None for f in ("wijk", "lat", "lng", "postcode")):
            for field in ("postcode", "wijk", "buurt", "lat", "lng"):
                if listing.get(field) is not None:
                    updates[field] = listing[field]
            if listing.get("stad") is not None:
                updates["stad"] = stad_voor_db(listing["stad"]) or listing["stad"]
        db.table("listings").update(updates).eq("id", record["id"]).execute()
        return record["id"]

    nu = datetime.now(timezone.utc).isoformat()
    supabase_data = {k: v for k, v in listing.items() if k in _SUPABASE_LISTING_FIELDS}
    if supabase_data.get("stad"):
        supabase_data["stad"] = stad_voor_db(supabase_data["stad"]) or supabase_data["stad"]
    nieuw = {**supabase_data, "eerste_gezien": nu, "created_at": nu, "laatst_gevalideerd": nu}
    result = db.table("listings").insert(nieuw).execute()
    return result.data[0]["id"] if result.data else None


async def verrijk_met_geocoding(listings: list[dict]) -> None:
    """
    Vul postcode/wijk/buurt/lat/lng per listing via PDOK (gecachet in geocode_cache).
    Muteert de listing-dicts in-place. PDOK-fouten/missers laten de listing ongemoeid.
    """
    sem = asyncio.Semaphore(8)  # vriendelijk voor PDOK; cache-hits zijn snel

    async def _verrijk(lst: dict) -> None:
        adres = (lst.get("adres") or "").strip()
        if not adres:
            return
        stad = (lst.get("stad") or "").strip()
        # Bevat het adres al een stad (bv. Kamernet "Straat, Delft")? Dan NIET de scraper-stad
        # aanhangen — "Delft den-haag" verwart PDOK. Anders helpt de scraper-stad de match.
        # GEEN gemeente-constraint: PDOK mag de echte stad teruggeven.
        query = adres if "," in adres else f"{adres} {stad}".strip()
        async with sem:
            geo = await geocode(query)
        if geo:
            for field in ("postcode", "wijk", "buurt", "lat", "lng"):
                lst[field] = geo.get(field)
            # PDOK-stad is de waarheid (niet de stad uit de scraper-URL)
            if geo.get("stad"):
                lst["stad"] = stad_voor_db(geo["stad"]) or geo["stad"]

    await asyncio.gather(*(_verrijk(lst) for lst in listings))


def registreer_scrapers(scrapers: list) -> None:
    """
    Registreer ontdekte scrapers in scraper_config als ze er nog niet instaan.
    Verwijdert de verouderde aggregatie-entry "nieuwbouw".
    Val terug op minimale insert als nieuwe kolommen nog niet bestaan (pre-migratie).
    """
    try:
        db = get_db()
        try:
            db.table("scraper_config").delete().eq("name", "nieuwbouw").execute()
        except Exception:
            pass

        bestaand = {c["name"] for c in (db.table("scraper_config").select("name").execute().data or [])}
        for s in scrapers:
            if s.name not in bestaand:
                try:
                    db.table("scraper_config").insert({
                        "name":     s.name,
                        "enabled":  True,
                        "category": getattr(s, "category", "huurwoningen"),
                        "status":   "onbekend",
                    }).execute()
                except Exception as e:
                    if "PGRST204" in str(e):
                        _log_migration_warning()
                        db.table("scraper_config").insert({
                            "name":    s.name,
                            "enabled": True,
                        }).execute()
                    else:
                        raise
                print(f"[scrapers] Geregistreerd in scraper_config: {s.name}", flush=True)
    except Exception as e:
        print(f"[scrapers] Kon scrapers niet registreren: {e}", flush=True)


def update_scraper_stats(counts: dict, errors: dict | None = None) -> None:
    """
    Schrijf last_run, last_count, status en error_message terug naar scraper_config.
    counts: {scraper_name: total_listings_found}
    errors: {scraper_name: error_message_str}  — optioneel
    """
    if not counts and not errors:
        return
    nu = datetime.now(timezone.utc).isoformat()
    errors = errors or {}
    try:
        db = get_db()
        alle_namen = set(counts) | set(errors)
        for name in alle_namen:
            count = counts.get(name, 0)
            err = errors.get(name)
            _safe_scraper_update(db, name, {
                "last_run":      nu,
                "last_count":    count,
                "status":        "fout" if err else "actief",
                "error_message": err,
            })
    except Exception as e:
        print(f"[scrapers] Kon scraper stats niet opslaan: {e}", flush=True)


def get_enabled_scrapers(all_scrapers: list) -> list:
    """
    Filtert scrapers op basis van scraper_config in Supabase.
    Wordt elke loop aangeroepen zodat toggles zonder herstart ingaan.
    Bij DB-fout: alle scrapers actief (fail-open).
    """
    try:
        db = get_db()
        configs = db.table("scraper_config").select("name, enabled").execute().data or []
        config_map = {c["name"]: c["enabled"] for c in configs}
        enabled = [s for s in all_scrapers if config_map.get(s.name, True)]
        uitgeschakeld = [s.name for s in all_scrapers if not config_map.get(s.name, True)]
        if uitgeschakeld:
            print(f"[scrapers] Uitgeschakeld via config: {uitgeschakeld}", flush=True)
        return enabled
    except Exception as e:
        print(f"[scrapers] Fout bij laden scraper_config: {e} — alle scrapers actief", flush=True)
        return all_scrapers


_SKIP_TYPE_CHECK = {"funda", "pararius"}
_NOTIFICATIE_LIMIT = 1000
_PARKING_MARKERS = (
    "parkeergelegenheid",
    "parkeerplaats",
    "parking",
    "garage",
)


def _stad_filter_values(pref: dict) -> list[str]:
    """
    Waarden voor listings.stad in SQL (.in_): genormaliseerde slug + legacy varianten
    (PDOK/CBS-namen uit oudere records).
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in (pref.get("stad") or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        slug = normalize_city_name(raw)
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
        for v in stad_db_variants(raw):
            if v and v not in seen:
                seen.add(v)
                out.append(v)
    return out


def get_listings_for_user(pref: dict) -> list:
    """
    Listings voor notificaties: primaire filter in SQL (stad, prijs, beschikbaar).
    Python alleen voor ranking-light (volgorde uit SQL), wijk/type en al-verstuurd.
    """
    db = get_db()
    user_id = pref.get("user_id")
    min_prijs = pref.get("min_prijs") or 0
    max_prijs = pref.get("max_prijs") or 9999
    types = pref.get("type_woning") or []

    steden_values = _stad_filter_values(pref)
    if not steden_values:
        return []

    gewenste_wijken = pref.get("gewenste_wijken") or []
    wijk_filter = {w.strip().lower() for w in gewenste_wijken if w and w.strip()}

    sent = db.table("sent_notifications").select("listing_id").eq("user_id", user_id).execute()
    al_gestuurd = {row["listing_id"] for row in (sent.data or [])}

    listings = (
        db.table("listings")
        .select("*")
        .in_("stad", steden_values)
        .eq("beschikbaar", True)
        .gte("prijs", min_prijs)
        .lte("prijs", max_prijs)
        .order("created_at", desc=True)
        .limit(_NOTIFICATIE_LIMIT)
        .execute()
        .data
        or []
    )

    steden_log = ",".join(stad_slugs_uit_pref(pref.get("stad") or ""))
    print(
        f"[notificaties] Filtered listings via SQL: stad={steden_log} count={len(listings)}",
        flush=True,
    )

    nieuw = []
    for listing in listings:
        if listing["id"] in al_gestuurd:
            continue
        if _is_parking_listing(listing):
            continue

        source = listing.get("source", "")
        if source not in _SKIP_TYPE_CHECK:
            listing_type = listing.get("type_woning")
            if listing_type and types and listing_type not in types:
                continue

        if wijk_filter:
            listing_wijk = (listing.get("wijk") or "").strip().lower()
            if listing_wijk not in wijk_filter:
                continue

        nieuw.append(listing)

    if nieuw:
        print(
            f"[notificaties] Matches for user={user_id}: count={len(nieuw)}",
            flush=True,
        )

    return nieuw


def _is_parking_listing(listing: dict) -> bool:
    """Voorkom dat parkeerplaatsen/garages als woning-notificatie worden aangeboden."""
    url = (listing.get("url") or "").lower()
    woning_type = (listing.get("type_woning") or "").lower()
    adres = (listing.get("adres") or "").lower()
    haystack = " ".join((url, woning_type, adres))
    return any(marker in haystack for marker in _PARKING_MARKERS)


def maak_bericht(listing: dict) -> str:
    adres = listing.get("adres") or "Onbekend adres"
    stad = listing.get("stad") or ""
    prijs = listing.get("prijs")
    oppervlakte = listing.get("oppervlakte")
    type_woning = listing.get("type_woning")
    url = listing.get("url", "")

    regels = ["🏠 Nieuwe woning gevonden!\n"]
    regels.append(f"📍 {adres}{', ' + stad if stad else ''}")
    if prijs:
        regels.append(f"💶 €{prijs}/maand")
    if oppervlakte:
        regels.append(f"📐 {oppervlakte}m²")
    if type_woning:
        regels.append(f"🏷️ {type_woning}")
    regels.append(f"\n🔗 {url}")

    return "\n".join(regels)


async def verwerk_notificaties(prefs: list) -> int:
    db = get_db()
    gestuurd = 0

    for pref in prefs:
        user_id = pref.get("user_id")
        # PRIVACY-FIX: decrypt encrypted PII fields before use
        chat_id = (safe_decrypt(pref.get("telegram_chat_id")) or "").strip()
        naam = safe_decrypt(pref.get("naam")) or user_id

        if not chat_id or not user_id:
            continue

        nieuwe_listings = get_listings_for_user(pref)

        for listing in nieuwe_listings:
            await stuur_telegram(chat_id, maak_bericht(listing))
            try:
                db.table("sent_notifications").insert({
                    "user_id": user_id,
                    "listing_id": listing["id"]
                }).execute()
            except Exception:
                pass  # UNIQUE constraint — dubbel versturen is onmogelijk
            gestuurd += 1
            print(f"[notificaties] → {naam}: {listing.get('url')}", flush=True)

    return gestuurd


def _update_nieuwbouw_lifecycle(db, scraped_urls: set) -> None:
    """
    Na elke scrape: increment consecutive_missing voor projecten die niet gezien zijn.
    Na 3 opeenvolgende missende scrapes → is_active = False.
    Projecten die herVerschijnen na inactiviteit → log heractivering (upsert reset al de velden).
    """
    from collections import defaultdict
    try:
        existing = (
            db.table("nieuwbouw_projects")
              .select("url, is_active, consecutive_missing, status")
              .execute()
              .data or []
        )

        reactivated: list[str] = []
        missing_increment: dict[str, int] = {}
        to_deactivate: list[str] = []

        for row in existing:
            url = row["url"]
            is_active = row.get("is_active", True)
            missing = row.get("consecutive_missing") or 0

            if url in scraped_urls:
                if not is_active:
                    reactivated.append(url)
                    # is_active + consecutive_missing al gereset via upsert
            else:
                new_count = missing + 1
                missing_increment[url] = new_count
                if new_count >= 3 and is_active:
                    to_deactivate.append(url)
                    print(
                        f"[nieuwbouw] Project inactief na {new_count}x niet gezien: "
                        f"{url} (status: {row.get('status')})",
                        flush=True,
                    )

        for url in reactivated:
            print(f"[nieuwbouw] Project heractiveerd: {url}", flush=True)

        if to_deactivate:
            db.table("nieuwbouw_projects").update({"is_active": False}).in_("url", to_deactivate).execute()

        # Batch per unieke teller om N queries te beperken
        by_count: dict[int, list] = defaultdict(list)
        for url, count in missing_increment.items():
            by_count[count].append(url)
        for count, urls in by_count.items():
            db.table("nieuwbouw_projects").update({"consecutive_missing": count}).in_("url", urls).execute()

        print(
            f"[nieuwbouw] Lifecycle: {len(reactivated)} heractiveerd, "
            f"{len(to_deactivate)} inactief, "
            f"{len(missing_increment)} niet gezien deze scrape",
            flush=True,
        )
    except Exception as e:
        print(f"[nieuwbouw] Lifecycle update fout: {e}", flush=True)


def _scrape_een_nieuwbouw(db, scraper) -> set:
    """
    Scrape één nieuwbouwbron en upsert de projecten. Geeft de gescrapete URLs terug.
    Wordt uitsluitend via de scheduler-gateway (run_scraper) aangeroepen.
    """
    nu = datetime.now(timezone.utc).isoformat()
    scraped_urls: set = set()
    print(f"[nieuwbouw] === Start {scraper.name} ===", flush=True)
    projecten = scraper.scrape_projecten()

    geslaagd = mislukt = hidden = 0
    for project in projecten:
        try:
            db.table("nieuwbouw_projects").upsert(project, on_conflict="url").execute()
            scraped_urls.add(project["url"])
            geslaagd += 1
            if project.get("status") in ("sold_out", "rented_out", "under_option", "registration_closed"):
                hidden += 1
        except Exception as e:
            print(f"[nieuwbouw] Upsert mislukt voor {project.get('url')}: {e}", flush=True)
            mislukt += 1

    print(
        f"[nieuwbouw] {scraper.name}: {geslaagd} opgeslagen "
        f"({hidden} verborgen status), {mislukt} mislukt",
        flush=True,
    )
    _safe_scraper_update(db, scraper.name, {
        "last_run":      nu,
        "last_count":    geslaagd,
        "status":        "actief",
        "error_message": None,
    })
    return scraped_urls


if __name__ == '__main__':
    print("🏠 Huiszoekerbot gestart", flush=True)
    valideer_schema()

    alle_scrapers = load_scrapers()
    if not alle_scrapers:
        print("[main] ❌ Geen scrapers gevonden — stop.", flush=True)
        exit(1)

    registreer_scrapers(alle_scrapers)
    storage = ListingStorage()

    # Nieuwbouw draait via dezelfde loop + scheduler-gateway (geen APScheduler meer,
    # dus géén scrape bij container-start). Tier-timing zit in scheduler.scrape_scheduler.
    nieuwbouw_scrapers = [s for s in alle_scrapers if getattr(s, "category", "") == "nieuwbouw"]
    print(
        f"[main] Scheduler-gateway actief — nieuwbouw: {[s.name for s in nieuwbouw_scrapers]}, "
        f"realtime: {[s.name for s in alle_scrapers if s not in nieuwbouw_scrapers]}",
        flush=True,
    )

    while True:
        try:
            # ── 1. VALIDATIE ──────────────────────────────────────────────────
            gecheckt, vervallen = valideer_listings()

            # ── 2. SCRAPEN ────────────────────────────────────────────────────
            db = get_db()
            prefs = db.table("user_preferences").select("*").execute().data or []

            if not prefs:
                print("[main] Geen gebruikers gevonden, wacht...", flush=True)
                time.sleep(INTERVAL)
                continue

            print(f"[main] {len(prefs)} gebruiker(s) actief", flush=True)

            scrapers = get_enabled_scrapers(alle_scrapers)
            if not scrapers:
                print("[main] Alle scrapers uitgeschakeld — notificaties worden nog wel verwerkt.", flush=True)

            BaseScraper.clear_cache()
            scrape_taken = bouw_scrape_taken(scrapers, prefs)
            taken_by_scraper = taken_per_scraper(scrape_taken)
            enabled_names = {s.name for s in scrapers}

            if scrape_taken:
                unieke_steden = sorted({t["stad"] for t in scrape_taken})
                print(
                    f"[scrape] Plan: {len(scrape_taken)} taken "
                    f"({len(taken_by_scraper)} scrapers, steden={','.join(unieke_steden)})",
                    flush=True,
                )

            alle_woningen = []
            counts_per_scraper: dict = {}

            # ── REALTIME scrapers — 1× per (site, stad), scheduler-lock per site ──
            for scraper in scrapers:
                if getattr(scraper, "excluded_from_main_loop", False):
                    continue
                params_list = taken_by_scraper.get(scraper.name, [])
                if not params_list:
                    continue

                def _run_realtime(sc=scraper, pl=params_list):
                    out = []
                    for p in pl:
                        prijs_log = (
                            f"prijs={p['min_prijs']}-{p['max_prijs']}"
                            if getattr(sc, "uses_price_filter", True)
                            else "prijs=SQL-filter"
                        )
                        print(
                            f"[scrape] {sc.name} stad={p['stad']} {prijs_log}",
                            flush=True,
                        )
                        gevonden = sc._scrape_impl(
                            stad=p["stad"], min_prijs=p["min_prijs"],
                            max_prijs=p["max_prijs"], types=p["types"],
                        )
                        print(
                            f"[scrape] {sc.name} stad={p['stad']} klaar: {len(gevonden)} listings",
                            flush=True,
                        )
                        out += gevonden
                    return out

                woningen = run_scraper(scraper.name, _run_realtime)
                if woningen:
                    alle_woningen.extend(woningen)
                    counts_per_scraper[scraper.name] = len(woningen)

            # ── NIEUWBOUW scrapers — via scheduler (maandag 05:00, 1x/week, 6u-lock) ──────
            enabled_nieuwbouw = [s for s in nieuwbouw_scrapers if s.name in enabled_names]
            nieuwbouw_urls: set = set()
            nb_ran = 0
            for ns in enabled_nieuwbouw:
                res = run_scraper(ns.name, lambda sc=ns: _scrape_een_nieuwbouw(get_db(), sc))
                if res is not None:
                    nieuwbouw_urls |= res
                    nb_ran += 1
            # Lifecycle alleen als álle ingeschakelde nieuwbouwbronnen deze ronde liepen
            # (anders zou de niet-gedraaide bron onterecht als 'missing' gemarkeerd worden).
            if enabled_nieuwbouw and nb_ran == len(enabled_nieuwbouw):
                _update_nieuwbouw_lifecycle(get_db(), nieuwbouw_urls)

            update_scraper_stats(counts_per_scraper, {})

            _cs = BaseScraper._stats
            print(
                f"[cache] Direct: {_cs['direct']}, Byparr: {_cs['flare']}, "
                f"Cache hits: {_cs['cache']} (bespaard)",
                flush=True
            )

            uniek = Deduplicator().deduplicate(alle_woningen)
            duplicaten = len(alle_woningen) - len(uniek)
            if duplicaten:
                print(f"[main] {duplicaten} cross-site duplicaat/duplicaten verwijderd", flush=True)

            # Verrijk met PDOK-geocoding (postcode/wijk/buurt/lat/lng) vóór opslag
            asyncio.run(verrijk_met_geocoding(uniek))

            # Sla snapshot op in Parquet (historische data / DuckDB queries)
            storage.save_listings(uniek)

            # Upsert in Supabase (notificaties en gebruikersmatching)
            totaal = sum(1 for w in uniek if upsert_listing(w))

            print(
                f"[main] {totaal} listings verwerkt "
                f"({len(alle_woningen)} gevonden, {duplicaten} duplicaten)",
                flush=True
            )

            # ── 3. NOTIFICATIES ───────────────────────────────────────────────
            gestuurd = asyncio.run(verwerk_notificaties(prefs))

            # ── 4. LOGGING ────────────────────────────────────────────────────
            print(
                f"[main] ✅ Loop klaar — "
                f"gevalideerd: {gecheckt}, vervallen: {vervallen}, "
                f"gevonden: {totaal}, notificaties: {gestuurd}. "
                f"Volgende check over 7 minuten...",
                flush=True
            )

        except Exception as e:
            print(f"[main] ❌ Fout in loop: {e}", flush=True)
            import traceback
            traceback.print_exc()
            try:
                err = str(e)
                _TRANSIENT = {"502", "503", "504", "520", "521", "522", "524"}
                if any(code in err for code in _TRANSIENT) or "bad gateway" in err.lower() or "JSON could not be generated" in err:
                    warning = f"⚠️ Supabase tijdelijk onbereikbaar. Loop hervat automatisch.\n{err[:200]}"
                else:
                    warning = f"❌ Fout in loop:\n{err[:300]}"
                asyncio.run(stuur_warning(warning))
            except Exception:
                pass

        time.sleep(INTERVAL)
