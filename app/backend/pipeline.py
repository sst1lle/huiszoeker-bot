"""Scrape-orchestratie, geocoding glue en run_cycle."""
import asyncio
import importlib
import inspect
import pkgutil
from datetime import datetime, timezone

from db import get_db
from deduplicator import Deduplicator
from listings_db import upsert_listings_batch
from notifications import stuur_warning, verwerk_notificaties
from scrape_plan import bouw_scrape_taken, taken_per_scraper
from scheduler.scrape_scheduler import run_scraper
from scrapers.base import BaseScraper
from shared.cities import stad_voor_db
from shared.geocoder import (
    geocode,
    begin_geocode_run,
    flush_geocode_cache,
    cleanup_stale_inflight,
    log_geocode_metrics,
)
from storage import ListingStorage
from validation import log_migration_warning, safe_scraper_update, valideer_listings

INTERVAL = 7 * 60


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


async def verrijk_met_geocoding(listings: list[dict]) -> None:
    """
    Vul postcode/wijk/buurt/lat/lng per listing via PDOK.
    Cache: in-memory + batch flush (backpressure, periodic daemon, retry-queue).
    """
    await flush_geocode_cache()  # retry WAL + resterende pending van vorige run
    await cleanup_stale_inflight()
    begin_geocode_run()
    sem = asyncio.Semaphore(8)

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
            c = stad_voor_db(geo.get("stad"))
            if c:
                lst["stad"] = c

    await asyncio.gather(*(_verrijk(lst) for lst in listings))
    await flush_geocode_cache()


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
                        log_migration_warning()
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
            safe_scraper_update(db, name, {
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
    safe_scraper_update(db, scraper.name, {
        "last_run":      nu,
        "last_count":    geslaagd,
        "status":        "actief",
        "error_message": None,
    })
    return scraped_urls


async def run_cycle(alle_scrapers: list, nieuwbouw_scrapers: list, storage: ListingStorage) -> None:
    """Eén scrape + geocode + notificatie-ronde (sync scrape, async enrich/notify)."""
    try:
        # ── 1. VALIDATIE ──────────────────────────────────────────────────
        gecheckt, vervallen = await valideer_listings()

        # ── 2. SCRAPEN ────────────────────────────────────────────────────
        db = get_db()
        prefs = db.table("user_preferences").select("*").execute().data or []

        if not prefs:
            print("[main] Geen gebruikers gevonden, wacht...", flush=True)
            return

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
        if enabled_nieuwbouw and nb_ran == len(enabled_nieuwbouw):
            _update_nieuwbouw_lifecycle(get_db(), nieuwbouw_urls)

        update_scraper_stats(counts_per_scraper, {})

        _cs = BaseScraper._stats
        print(
            f"[cache] Direct: {_cs['direct']}, Byparr: {_cs['flare']}, "
            f"Cache hits: {_cs['cache']} (bespaard)",
            flush=True,
        )

        uniek = Deduplicator().deduplicate(alle_woningen)
        duplicaten = len(alle_woningen) - len(uniek)
        if duplicaten:
            print(f"[main] {duplicaten} cross-site duplicaat/duplicaten verwijderd", flush=True)

        await verrijk_met_geocoding(uniek)

        storage.save_listings(uniek)

        totaal = upsert_listings_batch(uniek)

        print(
            f"[main] {totaal} listings verwerkt "
            f"({len(alle_woningen)} gevonden, {duplicaten} duplicaten)",
            flush=True,
        )

        gestuurd = await verwerk_notificaties(prefs)

        print(
            f"[main] ✅ Loop klaar — "
            f"gevalideerd: {gecheckt}, vervallen: {vervallen}, "
            f"gevonden: {totaal}, notificaties: {gestuurd}. "
            f"Volgende check over 7 minuten...",
            flush=True,
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
            await stuur_warning(warning)
        except Exception:
            pass
    finally:
        await cleanup_stale_inflight()
        log_geocode_metrics()


async def scheduler_loop(alle_scrapers: list, nieuwbouw_scrapers: list, storage: ListingStorage) -> None:
    """Long-running daemon: één event loop voor geocode semaphores + inflight coalescing."""
    while True:
        await run_cycle(alle_scrapers, nieuwbouw_scrapers, storage)
        await asyncio.sleep(INTERVAL)
