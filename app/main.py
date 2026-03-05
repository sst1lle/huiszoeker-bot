import os
import json
import time
import asyncio
from dotenv import load_dotenv
from telegram import Bot

from scrapers.pararius import scrape_pararius

USERS_DIR = '/app/data/users'
SEEN_DIR = '/app/data/seen'

os.environ['PYTHONUNBUFFERED'] = '1'
load_dotenv()

INTERVAL = 15 * 60


def laad_users():
    users = {}
    if os.path.exists(USERS_DIR):
        for f in os.listdir(USERS_DIR):
            if f.endswith('.json'):
                uid = f.replace('.json', '')
                with open(os.path.join(USERS_DIR, f)) as fp:
                    users[uid] = json.load(fp)
    return users


def laad_gezien(uid):
    """Laad de links die al naar deze specifieke user gestuurd zijn."""
    os.makedirs(SEEN_DIR, exist_ok=True)
    path = os.path.join(SEEN_DIR, f'{uid}.json')
    if os.path.exists(path):
        with open(path) as f:
            return set(json.load(f))
    return set()


def sla_gezien_op(uid, gezien):
    """Sla de geziene links op voor deze specifieke user."""
    os.makedirs(SEEN_DIR, exist_ok=True)
    path = os.path.join(SEEN_DIR, f'{uid}.json')
    with open(path, 'w') as f:
        json.dump(list(gezien), f)


def check_nieuw_voor_user(woningen, gezien):
    nieuw = []
    for w in woningen:
        link = w['link'].rstrip('/')
        if link not in gezien:
            nieuw.append(w)
            gezien.add(link)
    return nieuw, gezien


async def stuur_telegram(chat_id, bericht):
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    try:
        await bot.send_message(chat_id=chat_id, text=bericht)
    except Exception as e:
        print(f"[telegram] Fout voor {chat_id}: {e}", flush=True)


async def stuur_warning(bericht):
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


if __name__ == '__main__':
    print("🏠 Huiszoekerbot gestart", flush=True)

    while True:
        try:
            users = laad_users()

            if not users:
                print("[main] Geen gebruikers gevonden, wacht...", flush=True)
                time.sleep(INTERVAL)
                continue

            print(f"[main] {len(users)} gebruiker(s) actief", flush=True)

            # Cache scrape resultaten per stad+prijs combinatie
            scraped = {}

            for uid, user in users.items():
                naam = user.get('naam', uid)
                stad = user.get('stad', 'den-haag')
                min_prijs = user.get('min_prijs', 0)
                max_prijs = user.get('max_prijs', 1500)
                chat_id = user.get('telegram_chat_id', '').strip()

                if not chat_id:
                    print(f"[main] {naam}: geen chat_id ingesteld, sla over", flush=True)
                    continue

                # Scrape alleen als deze combinatie nog niet gedaan is
                scrape_key = f"{stad}-{min_prijs}-{max_prijs}"
                if scrape_key not in scraped:
                    woningen = scrape_pararius(stad=stad, min_prijs=min_prijs, max_prijs=max_prijs)
                    scraped[scrape_key] = woningen
                    print(f"[main] {naam}: {len(woningen)} woningen gevonden voor {stad} €{min_prijs}-€{max_prijs}", flush=True)

                    if len(woningen) == 0:
                        asyncio.run(stuur_warning(
                            f"⚠️ Pararius gaf 0 resultaten!\n"
                            f"Stad: {stad}, Prijs: €{min_prijs}-€{max_prijs}"
                        ))
                else:
                    woningen = scraped[scrape_key]
                    print(f"[main] {naam}: hergebruik scrape ({len(woningen)} woningen)", flush=True)

                # Check welke woningen nieuw zijn voor DEZE specifieke user
                gezien = laad_gezien(uid)
                nieuw, gezien_updated = check_nieuw_voor_user(woningen, gezien)

                if nieuw:
                    for w in nieuw:
                        bericht = (
                            f"🏠 Nieuwe woning voor {naam}!\n"
                            f"{w['titel']}\n"
                            f"{w['prijs']}\n"
                            f"📍 {stad}\n"
                            f"{w['link']}"
                        )
                        asyncio.run(stuur_telegram(chat_id, bericht))

                    # Sla geziene links op voor deze user
                    sla_gezien_op(uid, gezien_updated)
                    print(f"[main] {naam}: {len(nieuw)} nieuw verstuurd", flush=True)
                else:
                    print(f"[main] {naam}: geen nieuwe woningen", flush=True)

            print(f"[main] ✅ Loop klaar, volgende check over 15 minuten...", flush=True)

        except Exception as e:
            print(f"[main] ❌ Fout in loop: {e}", flush=True)
            try:
                asyncio.run(stuur_warning(f"❌ Huiszoekerbot fout:\n{e}"))
            except:
                pass

        time.sleep(INTERVAL)
