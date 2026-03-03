import os
import json
import time
import asyncio
from dotenv import load_dotenv
from telegram import Bot

from scrapers.pararius import scrape_pararius

DATA_FILE = '/app/data/woningen.json'
CONFIG_FILE = '/app/data/config.json'

os.environ['PYTHONUNBUFFERED'] = '1'
load_dotenv()

INTERVAL = 15 * 60  # 15 minuten


def laad_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {
        'stad': 'den-haag',
        'min_prijs': 0,
        'max_prijs': 1200
    }


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


async def stuur_telegram(bericht):
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    chat_ids = os.getenv('TELEGRAM_CHAT_ID', '').split(',')

    for chat_id in chat_ids:
        chat_id = chat_id.strip()
        if not chat_id:
            continue
        try:
            await bot.send_message(chat_id=chat_id, text=bericht)
        except Exception as e:
            print(f"Telegram fout voor {chat_id}: {e}", flush=True)


if __name__ == '__main__':
    print("🏠 Huiszoekerbot gestart", flush=True)

    while True:
        try:
            config = laad_config()
            bestaande = laad_bestaande()

            pararius_woningen = scrape_pararius(
                stad=config['stad'],
                min_prijs=config['min_prijs'],
                max_prijs=config['max_prijs']
            )
            print(f"[main] Pararius resultaten: {len(pararius_woningen)}", flush=True)

            if len(pararius_woningen) == 0:
                asyncio.run(stuur_telegram(
                    "⚠️ Waarschuwing: Pararius gaf 0 resultaten!\n"
                    "Mogelijk geblokkeerd of Scrape.do probleem.\n"
                    f"Stad: {config['stad']}, Prijs: €{config['min_prijs']}-€{config['max_prijs']}"
                ))

            alle_nieuw = check_nieuw(pararius_woningen, bestaande)

            if alle_nieuw:
                for w in alle_nieuw:
                    bericht = (
                        f"🏠 Nieuwe woning ({w['bron']})!\n"
                        f"{w['titel']}\n"
                        f"{w['prijs']}\n"
                        f"{w['link']}"
                    )
                    asyncio.run(stuur_telegram(bericht))

                bestaande += alle_nieuw
                sla_op(bestaande)

            print(f"[main] ✅ Loop klaar — {len(alle_nieuw)} nieuw gevonden", flush=True)
            print(f"[main] Volgende check over 15 minuten...", flush=True)

        except Exception as e:
            print(f"[main] ❌ Fout in loop: {e}", flush=True)
            try:
                asyncio.run(stuur_telegram(f"❌ Huiszoekerbot fout:\n{e}"))
            except:
                pass

        time.sleep(INTERVAL)
