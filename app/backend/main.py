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
from apscheduler.schedulers.background import BackgroundScheduler

from db import get_db
from scrapers.base import BaseScraper
from deduplicator import Deduplicator
from storage import ListingStorage

os.environ['PYTHONUNBUFFERED'] = '1'
load_dotenv()

INTERVAL = 15 * 60
VALIDATIE_INTERVAL_UREN = 6


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
}


def upsert_listing(listing: dict) -> str | None:
    """Insert nieuwe listing of update bestaande als hij onvolledig is (migratiestub). Geeft UUID terug."""
    if not listing.get("prijs"):
        return None  # listing zonder prijs is niet bruikbaar voor matching

    db = get_db()

    bestaand = db.table("listings").select("id, beschikbaar, prijs").eq("url", listing["url"]).execute()

    if bestaand.data:
        record = bestaand.data[0]
        nu = datetime.now(timezone.utc).isoformat()
        scrape_beschikbaar = listing.get("beschikbaar", True)
        updates = {"laatst_gevalideerd": nu, "beschikbaar": scrape_beschikbaar}
        # Vul ontbrekende velden in — migratiestubs hebben prijs/stad/adres=None
        if not record.get("prijs"):
            for field in ("adres", "stad", "prijs", "oppervlakte", "type_woning", "foto_url"):
                if listing.get(field) is not None:
                    updates[field] = listing[field]
        db.table("listings").update(updates).eq("id", record["id"]).execute()
        return record["id"]

    nu = datetime.now(timezone.utc).isoformat()
    supabase_data = {k: v for k, v in listing.items() if k in _SUPABASE_LISTING_FIELDS}
    nieuw = {**supabase_data, "eerste_gezien": nu, "created_at": nu, "laatst_gevalideerd": nu}
    result = db.table("listings").insert(nieuw).execute()
    return result.data[0]["id"] if result.data else None


def registreer_scrapers(scrapers: list) -> None:
    """
    Registreer ontdekte scrapers in scraper_config als ze er nog niet instaan.
    Verwijdert ook de verouderde aggregatie-entry "nieuwbouw" die vervangen is
    door aparte "nieuwbouw_nederland" en "nieuwbouw_nl" entries.
    """
    try:
        db = get_db()
        # Verwijder verouderd aggregatie-entry
        db.table("scraper_config").delete().eq("name", "nieuwbouw").execute()

        bestaand = {c["name"] for c in (db.table("scraper_config").select("name").execute().data or [])}
        for s in scrapers:
            if s.name not in bestaand:
                db.table("scraper_config").insert({
                    "name":     s.name,
                    "enabled":  True,
                    "category": getattr(s, "category", "huurwoningen"),
                    "status":   "onbekend",
                }).execute()
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
            db.table("scraper_config").update({
                "last_run":      nu,
                "last_count":    count,
                "status":        "fout" if err else "actief",
                "error_message": err,
            }).eq("name", name).execute()
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


def bouw_combis(scrapers: list, prefs: list) -> dict:
    """
    Bouw unieke parameter-combinaties per scraper op basis van gebruikersvoorkeuren.

    Sleutel: {scraper.name}-{stad}-{min}-{max}-{types}-r{radius}
    Als scraper.uses_types=False wordt het types-deel weggelaten — de scraper
    retourneert toch altijd alle typen (bijv. Pararius).

    Toevoegen van een nieuwe scraper vereist geen aanpassing hier.
    """
    combis = {}
    for scraper in [s for s in scrapers if not getattr(s, "excluded_from_main_loop", False)]:
        for pref in prefs:
            stad = (pref.get("stad") or "").strip()
            if not stad:
                continue
            min_p = pref.get("min_prijs") or 0
            max_p = pref.get("max_prijs") or 1500
            types = pref.get("type_woning") or []
            radius = pref.get("radius_km") or None

            types_deel = "" if not scraper.uses_types else ",".join(sorted(types))
            key = f"{scraper.name}-{stad}-{min_p}-{max_p}-{types_deel}-r{radius}"

            if key not in combis:
                combis[key] = {
                    "scraper": scraper,
                    "stad": stad,
                    "min_prijs": min_p,
                    "max_prijs": max_p,
                    "types": types,
                    "radius_km": radius,
                }
    return combis


def zoek_nieuwe_voor_user(pref: dict) -> list:
    """Haal listings op die matchen met de voorkeur en nog niet verstuurd zijn."""
    db = get_db()
    user_id = pref.get("user_id")
    stad = pref.get("stad", "")
    min_prijs = pref.get("min_prijs") or 0
    max_prijs = pref.get("max_prijs") or 9999
    types = pref.get("type_woning") or []

    # Al-verstuurde listing IDs voor deze user
    sent = db.table("sent_notifications").select("listing_id").eq("user_id", user_id).execute()
    al_gestuurd = {row["listing_id"] for row in (sent.data or [])}

    # Listings ophalen op stad + prijsrange
    listings = (db.table("listings")
                .select("*")
                .eq("stad", stad)
                .eq("beschikbaar", True)
                .gte("prijs", min_prijs)
                .lte("prijs", max_prijs)
                .execute()
                .data or [])

    # Bronnen waarbij type_woning niet betrouwbaar is → altijd tonen
    _SKIP_TYPE_CHECK = {"funda", "pararius"}

    nieuw = []
    for listing in listings:
        if listing["id"] in al_gestuurd:
            continue
        if "parkeergelegenheid" in (listing.get("url") or ""):
            continue
        source = listing.get("source", "")
        if source not in _SKIP_TYPE_CHECK:
            listing_type = listing.get("type_woning")
            if listing_type and types and listing_type not in types:
                continue
        nieuw.append(listing)

    return nieuw


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
        chat_id = (pref.get("telegram_chat_id") or "").strip()
        naam = pref.get("naam") or user_id

        if not chat_id or not user_id:
            continue

        nieuwe_listings = zoek_nieuwe_voor_user(pref)

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


def scrape_nieuwbouw_job(nieuwbouw_scrapers: list) -> None:
    """
    Wekelijkse job: scrapet elke nieuwbouwbron afzonderlijk.
    Elke scraper heeft zijn eigen enabled-toggle, last_run en status in scraper_config.
    """
    print("[nieuwbouw] Wekelijkse scrape gestart", flush=True)
    try:
        db = get_db()
        nu = datetime.now(timezone.utc).isoformat()
        configs = {c["name"]: c["enabled"] for c in (
            db.table("scraper_config").select("name, enabled").execute().data or []
        )}

        all_scraped_urls: set = set()

        for scraper in nieuwbouw_scrapers:
            if not configs.get(scraper.name, True):
                print(f"[nieuwbouw] {scraper.name} uitgeschakeld — overgeslagen", flush=True)
                continue

            print(f"[nieuwbouw] === Start {scraper.name} ===", flush=True)
            try:
                projecten = scraper.scrape_projecten()

                geslaagd = mislukt = hidden = 0
                for project in projecten:
                    try:
                        db.table("nieuwbouw_projects").upsert(project, on_conflict="url").execute()
                        all_scraped_urls.add(project["url"])
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
                db.table("scraper_config").update({
                    "last_run":      nu,
                    "last_count":    geslaagd,
                    "status":        "actief",
                    "error_message": None,
                }).eq("name", scraper.name).execute()

            except Exception as e:
                print(f"[nieuwbouw] {scraper.name} fout: {e}", flush=True)
                db.table("scraper_config").update({
                    "status":        "fout",
                    "error_message": str(e)[:500],
                }).eq("name", scraper.name).execute()

        _update_nieuwbouw_lifecycle(db, all_scraped_urls)

    except Exception as e:
        print(f"[nieuwbouw] ❌ Job fout: {e}", flush=True)


if __name__ == '__main__':
    print("🏠 Huiszoekerbot gestart", flush=True)

    alle_scrapers = load_scrapers()
    if not alle_scrapers:
        print("[main] ❌ Geen scrapers gevonden — stop.", flush=True)
        exit(1)

    registreer_scrapers(alle_scrapers)
    storage = ListingStorage()

    # Wekelijkse nieuwbouw-scrape via APScheduler (los van de 15-minuten loop)
    nieuwbouw_scrapers = [s for s in alle_scrapers if getattr(s, "category", "") == "nieuwbouw"]
    if nieuwbouw_scrapers:
        namen = [s.name for s in nieuwbouw_scrapers]
        scheduler = BackgroundScheduler(timezone="Europe/Amsterdam")
        scheduler.add_job(
            scrape_nieuwbouw_job,
            trigger="interval",
            weeks=1,
            args=[nieuwbouw_scrapers],
            id="nieuwbouw_weekly",
            next_run_time=datetime.now(timezone.utc),  # ook direct bij opstarten
        )
        scheduler.start()
        print(f"[nieuwbouw] Wekelijkse scheduler gestart voor: {namen}", flush=True)
    else:
        print("[nieuwbouw] ⚠️ Geen nieuwbouw-scrapers gevonden — wekelijkse job overgeslagen", flush=True)

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
            combis = bouw_combis(scrapers, prefs)
            alle_woningen = []
            counts_per_scraper: dict = {}  # scraper.name → totaal gevonden listings
            errors_per_scraper: dict = {}  # scraper.name → laatste foutmelding

            for params in combis.values():
                scraper = params["scraper"]
                try:
                    woningen = scraper.scrape(
                        stad=params["stad"],
                        min_prijs=params["min_prijs"],
                        max_prijs=params["max_prijs"],
                        types=params["types"],
                        radius_km=params["radius_km"],
                    )
                except Exception as e:
                    print(f"[scrapers] ❌ {scraper.name} fout: {e}", flush=True)
                    errors_per_scraper[scraper.name] = str(e)[:500]
                    asyncio.run(stuur_warning(
                        f"⚠️ {scraper.name} fout!\n"
                        f"Stad: {params['stad']}, Prijs: €{params['min_prijs']}-€{params['max_prijs']}\n"
                        f"Fout: {e}"
                    ))
                    woningen = []
                alle_woningen.extend(woningen)
                counts_per_scraper[scraper.name] = counts_per_scraper.get(scraper.name, 0) + len(woningen)

            update_scraper_stats(counts_per_scraper, errors_per_scraper)

            _cs = BaseScraper._stats
            print(
                f"[cache] Direct: {_cs['direct']}, FlareSolverr: {_cs['flare']}, "
                f"Cache hits: {_cs['cache']} (bespaard)",
                flush=True
            )

            uniek = Deduplicator().deduplicate(alle_woningen)
            duplicaten = len(alle_woningen) - len(uniek)
            if duplicaten:
                print(f"[main] {duplicaten} cross-site duplicaat/duplicaten verwijderd", flush=True)

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
                f"Volgende check over 15 minuten...",
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
