import requests
import json
import os
import time
import asyncio
import sys
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Bot

os.environ['PYTHONUNBUFFERED'] = '1'

load_dotenv()
SITE_URL = os.getenv('SITE_URL', 'https://www.pararius.nl/huurwoningen/den-haag/0-1200')
DATA_FILE = '/app/data/woningen.json'

def scrape_woningen():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    response = requests.get(SITE_URL, headers=headers, timeout=10)
    soup = BeautifulSoup(response.text, 'html.parser')
    woningen = []

    for item in soup.select('li.search-list__item--listing'):
        titel_el = item.select_one('.listing-search-item__title')
        prijs_el = item.select_one('.listing-search-item__price')
        link_el  = item.select_one('a.listing-search-item__link--title')

        if not titel_el or not prijs_el or not link_el:
            continue

        titel = titel_el.text.strip()
        prijs = prijs_el.text.strip()
        link  = 'https://www.pararius.nl' + link_el['href']

        woningen.append({'titel': titel, 'prijs': prijs, 'link': link})

    return woningen

def laad_bestaande():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return []

def sla_op(woningen):
    os.makedirs('/app/data', exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(woningen, f, indent=2, ensure_ascii=False)

def check_nieuw(nieuw, oud):
    oud_links = {w['link'] for w in oud}
    return [w for w in nieuw if w['link'] not in oud_links]

async def stuur_telegram(bericht):
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    await bot.send_message(
        chat_id=os.getenv('TELEGRAM_CHAT_ID'),
        text=bericht
    )

if __name__ == '__main__':
    print('Huiszoekerbot gestart...', flush=True)
    while True:
        try:
            bestaand = laad_bestaande()
            woningen = scrape_woningen()
            nieuw = check_nieuw(woningen, bestaand)

            if nieuw:
                for w in nieuw:
                    bericht = f"Nieuwe woning!\n{w['titel']}\n{w['prijs']}\n{w['link']}"
                    asyncio.run(stuur_telegram(bericht))
                    print(f"Telegram verstuurd: {w['titel']}", flush=True)
            else:
                print('Geen nieuwe woningen.', flush=True)

            sla_op(woningen)
            print(f'{len(woningen)} woningen totaal gevonden.', flush=True)

        except Exception as e:
            print(f'Fout: {e}', flush=True)

        time.sleep(60)
