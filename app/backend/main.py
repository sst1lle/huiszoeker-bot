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
    Wordt eenmalig aangeroepen bij botstart — zorgt dat /admin/scrapers ze toont.
    """
    try:
        db = get_db()
        bestaand = {c["name"] for c in (db.table("scraper_config").select("name").execute().data or [])}
        for s in scrapers:
            if s.name not in bestaand:
                db.table("scraper_config").insert({"name": s.name, "enabled": True}).execute()
                print(f"[scrapers] Geregistreerd in scraper_config: {s.name}", flush=True)
    except Exception as e:
        print(f"[scrapers] Kon scrapers niet registreren: {e}", flush=True)


def update_scraper_stats(counts: dict) -> None:
    """
    Schrijf last_run en last_count terug naar scraper_config na elke scrape-ronde.
    counts: {scraper_name: total_listings_found}
    """
    if not counts:
        return
    nu = datetime.now(timezone.utc).isoformat()
    try:
        db = get_db()
        for name, count in counts.items():
            db.table("scraper_config").update({
                "last_run":   nu,
                "last_count": count,
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
    for scraper in scrapers:
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


if __name__ == '__main__':
    print("🏠 Huiszoekerbot gestart", flush=True)

    alle_scrapers = load_scrapers()
    if not alle_scrapers:
        print("[main] ❌ Geen scrapers gevonden — stop.", flush=True)
        exit(1)

    registreer_scrapers(alle_scrapers)
    storage = ListingStorage()

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
                    asyncio.run(stuur_warning(
                        f"⚠️ {scraper.name} fout!\n"
                        f"Stad: {params['stad']}, Prijs: €{params['min_prijs']}-€{params['max_prijs']}\n"
                        f"Fout: {e}"
                    ))
                    woningen = []
                alle_woningen.extend(woningen)
                counts_per_scraper[scraper.name] = counts_per_scraper.get(scraper.name, 0) + len(woningen)

            update_scraper_stats(counts_per_scraper)

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
