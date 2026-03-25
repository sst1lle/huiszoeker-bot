import os
import time
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from telegram import Bot

from db import get_db
from scrapers.pararius import scrape_pararius
from scrapers.kamernet import scrape_kamernet

os.environ['PYTHONUNBUFFERED'] = '1'
load_dotenv()

INTERVAL = 15 * 60
VALIDATIE_INTERVAL_UREN = 6


async def stuur_telegram(chat_id: str, bericht: str):
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    try:
        await bot.send_message(chat_id=chat_id, text=bericht)
    except Exception as e:
        print(f"[telegram] Fout voor {chat_id}: {e}", flush=True)


async def stuur_warning(bericht: str):
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    chat_ids = os.getenv('TELEGRAM_CHAT_ID', '').split(',')
    for chat_id in chat_ids:
        chat_id = chat_id.strip()
        if not chat_id:
            continue
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


def upsert_listing(listing: dict) -> str | None:
    """Insert nieuwe listing of update beschikbaar=True als hij teruggekomen is. Geeft UUID terug."""
    if not listing.get("prijs"):
        return None  # listing zonder prijs is niet bruikbaar voor matching

    db = get_db()

    bestaand = db.table("listings").select("id, beschikbaar").eq("url", listing["url"]).execute()

    if bestaand.data:
        record = bestaand.data[0]
        if not record["beschikbaar"]:
            db.table("listings").update({"beschikbaar": True}).eq("id", record["id"]).execute()
        return record["id"]

    nu = datetime.now(timezone.utc).isoformat()
    nieuw = {**listing, "eerste_gezien": nu, "created_at": nu, "laatst_gevalideerd": nu}
    result = db.table("listings").insert(nieuw).execute()
    return result.data[0]["id"] if result.data else None


def zoek_nieuwe_voor_user(pref: dict) -> list[dict]:
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

    nieuw = []
    for listing in listings:
        if listing["id"] in al_gestuurd:
            continue
        listing_type = listing.get("type_woning")
        # type_woning=None (Pararius) matcht altijd; anders moet het in de voorkeur staan
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


async def verwerk_notificaties(prefs: list[dict]) -> int:
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

            # Dedupliceer scrape-combinaties: elke unieke stad+prijs slechts één keer scrapen
            pararius_combis: dict[str, dict] = {}
            kamernet_combis: dict[str, dict] = {}

            for pref in prefs:
                stad = (pref.get("stad") or "").strip()
                min_p = pref.get("min_prijs") or 0
                max_p = pref.get("max_prijs") or 1500
                types = pref.get("type_woning") or []

                p_key = f"{stad}-{min_p}-{max_p}"
                if p_key not in pararius_combis:
                    pararius_combis[p_key] = {"stad": stad, "min_prijs": min_p, "max_prijs": max_p}

                k_key = f"{stad}-{min_p}-{max_p}-{','.join(sorted(types))}"
                if k_key not in kamernet_combis:
                    kamernet_combis[k_key] = {"stad": stad, "min_prijs": min_p, "max_prijs": max_p, "types": types}

            totaal = 0

            for params in pararius_combis.values():
                woningen = scrape_pararius(
                    stad=params["stad"],
                    min_prijs=params["min_prijs"],
                    max_prijs=params["max_prijs"]
                )
                if not woningen:
                    asyncio.run(stuur_warning(
                        f"⚠️ Pararius gaf 0 resultaten!\n"
                        f"Stad: {params['stad']}, Prijs: €{params['min_prijs']}-€{params['max_prijs']}"
                    ))
                for w in woningen:
                    upsert_listing(w)
                    totaal += 1

            for params in kamernet_combis.values():
                woningen = scrape_kamernet(
                    stad=params["stad"],
                    min_prijs=params["min_prijs"],
                    max_prijs=params["max_prijs"],
                    types=params["types"]
                )
                for w in woningen:
                    upsert_listing(w)
                    totaal += 1

            print(f"[main] {totaal} listings verwerkt", flush=True)

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
                asyncio.run(stuur_warning(f"❌ Huiszoekerbot fout:\n{e}"))
            except Exception:
                pass

        time.sleep(INTERVAL)
