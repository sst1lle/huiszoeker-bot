import os
import json
import time
import asyncio
from dotenv import load_dotenv
from telegram import Bot

from scrapers.pararius import scrape_pararius
from scrapers.huurwoningen import scrape_huurwoningen

DATA_FILE = '/app/data/woningen.json'
CONFIG_FILE = '/app/data/config.json'

os.environ['PYTHONUNBUFFERED'] = '1'
load_dotenv()


def laad_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {
        'stad': 'den-haag',
        'radius': 10,
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
            bestaande_links.add(link)  # voorkomt dubbele binnen zelfde run

    return unieke


async def stuur_telegram(bericht):
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    chat_ids = os.getenv('TELEGRAM_CHAT_ID', '').split(',')

    for chat_id in chat_ids:
        chat_id = chat_id.strip()
        if not chat_id:
            continue

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=bericht
            )
        except Exception as e:
            print(f"Telegram fout voor {chat_id}: {e}", flush=True)


if __name__ == '__main__':
    print("Huiszoekerbot gestart", flush=True)

    while True:
        try:
            config = laad_config()
            bestaande = laad_bestaande()

            # ? Scrapen
            pararius_woningen = scrape_pararius(
                stad=config['stad'],
                min_prijs=config['min_prijs'],
                max_prijs=config['max_prijs']
            )

            huurwoningen_woningen = scrape_huurwoningen(
                stad=config['stad'],
                min_prijs=config['min_prijs'],
                max_prijs=config['max_prijs']
            )

            # ? Nieuwe woningen bepalen
            nieuw_pararius = check_nieuw(pararius_woningen, bestaande)
            nieuw_huurwoningen = check_nieuw(huurwoningen_woningen, bestaande)

            alle_nieuw = nieuw_pararius + nieuw_huurwoningen

            # ? Alleen sturen als er echt nieuwe zijn
            if alle_nieuw:
                for w in alle_nieuw:
                    bericht = (
                        f"? Nieuwe woning ({w['bron']})!\n"
                        f"{w['titel']}\n"
                        f"{w['prijs']}\n"
                        f"{w['link']}"
                    )

                    asyncio.run(stuur_telegram(bericht))

                # ? Pas na versturen opslaan
                bestaande += alle_nieuw
                sla_op(bestaande)

            print(f"Loop klaar ? {len(alle_nieuw)} nieuw", flush=True)

        except Exception as e:
            print(f"Fout in loop: {e}", flush=True)

        time.sleep(90)
