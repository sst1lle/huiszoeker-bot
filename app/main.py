import os
import json
import time
import asyncio
from dotenv import load_dotenv
from telegram import Bot

from scrapers.pararius import scrape_pararius

DATA_FILE = '/app/data/woningen.json'
USERS_DIR = '/app/data/users'

os.environ['PYTHONUNBUFFERED'] = '1'
load_dotenv()

INTERVAL = 15 * 60  # 15 minuten


def laad_users():
    users = {}
    if os.path.exists(USERS_DIR):
        for f in os.listdir(USERS_DIR):
            if f.endswith('.json'):
                uid = f.replace('.json', '')
                with open(os.path.join(USERS_DIR, f)) as fp:
                    users[uid] = json.load(fp)
    return users


def laad_bestaande():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return []


def sla_op(woningen):
    os.makedirs('/app/data', exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(woningen, f, indent=2, ensure_ascii=False)


def check_nieuw(nieuwe_woningen, bestaande_woningen):
    bestaande_links = {w['link'].rstrip('/') for w in bestaande_woningen}
    unieke = []
    for w in nieuwe_woningen:
        link = w['link'].rstrip('/')
        if link not in bestaande_links:
            unieke.append(w)
            bestaande_links.add(link)
    return unieke


def woning_past_bij_user(woning, user):
    """Check of een woning past binnen de prijsrange van een user."""
    try:
        # Haal getal uit prijs string, bijv "€ 950 per maand" -> 950
        prijs_str = woning.get('prijs', '')
        cijfers = ''.join(filter(str.isdigit, prijs_str.replace('.', '')))
        if not cijfers:
            return True  # Bij twijfel toch sturen
        prijs = int(cijfers)
        return user['min_prijs'] <= prijs <= user['max_prijs']
    except:
        return True


async def stuur_telegram_user(user, bericht):
    """Stuur bericht naar een specifieke user via Telegram username."""
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))

    # Telegram chat_id kan ook als username via @username
    telegram = user.get('telegram_username', '').strip()
    if not telegram:
        print(f"[telegram] Geen username voor {user.get('naam')}", flush=True)
        return

    # Zorg dat het met @ begint
    if not telegram.startswith('@'):
        telegram = '@' + telegram

    # Probeer ook via TELEGRAM_CHAT_ID env als fallback
    chat_ids_env = os.getenv('TELEGRAM_CHAT_ID', '').split(',')

    # Stuur naar alle chat_ids uit .env (legacy) + de user zelf
    targets = [c.strip() for c in chat_ids_env if c.strip()]
    if telegram not in targets:
        targets.append(telegram)

    for chat_id in targets:
        try:
            await bot.send_message(chat_id=chat_id, text=bericht)
        except Exception as e:
            print(f"[telegram] Fout voor {chat_id}: {e}", flush=True)


async def stuur_warning(bericht):
    """Stuur waarschuwing naar alle chat_ids in .env."""
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    chat_ids = os.getenv('TELEGRAM_CHAT_ID', '').split(',')
    for chat_id in chat_ids:
        chat_id = chat_id.strip()
        if not chat_id:
            continue
        try:
            await bot.send_message(chat_id=chat_id, text=bericht)
        except Exception as e:
            print(f"[telegram] Warning fout voor {chat_id}: {e}", flush=True)


if __name__ == '__main__':
    print("🏠 Huiszoekerbot gestart", flush=True)

    while True:
        try:
            users = laad_users()
            bestaande = laad_bestaande()

            if not users:
                print("[main] Geen gebruikers gevonden, wacht...", flush=True)
                time.sleep(INTERVAL)
                continue

            print(f"[main] {len(users)} gebruiker(s) actief", flush=True)

            # Verzamel unieke combinaties van stad+prijs om dubbele scrapes te vermijden
            scraped = {}  # key: "stad-min-max" -> lijst woningen

            alle_nieuw_globaal = []

            for uid, user in users.items():
                stad = user.get('stad', 'den-haag')
                min_prijs = user.get('min_prijs', 0)
                max_prijs = user.get('max_prijs', 1500)
                naam = user.get('naam', uid)

                scrape_key = f"{stad}-{min_prijs}-{max_prijs}"

                # Alleen scrapen als deze combinatie nog niet gedaan is
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
                    print(f"[main] {naam}: hergebruik scrape voor {stad} ({len(woningen)} woningen)", flush=True)

                # Check nieuwe woningen voor deze user
                nieuw = check_nieuw(woningen, bestaande)

                # Filter op prijs van deze specifieke user
                nieuw_voor_user = [w for w in nieuw if woning_past_bij_user(w, user)]

                if nieuw_voor_user:
                    for w in nieuw_voor_user:
                        bericht = (
                            f"🏠 Nieuwe woning voor {naam}!\n"
                            f"{w['titel']}\n"
                            f"{w['prijs']}\n"
                            f"📍 {stad}\n"
                            f"{w['link']}"
                        )
                        asyncio.run(stuur_telegram_user(user, bericht))

                    alle_nieuw_globaal += nieuw_voor_user

            # Sla alle nieuwe woningen op (over alle users heen)
            if alle_nieuw_globaal:
                bestaande += alle_nieuw_globaal
                sla_op(bestaande)

            print(f"[main] ✅ Loop klaar — {len(alle_nieuw_globaal)} nieuw gevonden", flush=True)
            print(f"[main] Volgende check over 15 minuten...", flush=True)

        except Exception as e:
            print(f"[main] ❌ Fout in loop: {e}", flush=True)
            try:
                asyncio.run(stuur_warning(f"❌ Huiszoekerbot fout:\n{e}"))
            except:
                pass

        time.sleep(INTERVAL)
