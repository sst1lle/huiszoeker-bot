import os
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.pararius.nl"

def scrape_pararius(stad='den-haag', min_prijs=0, max_prijs=1200):
    target_url = f"https://www.pararius.nl/huurwoningen/{stad}/{min_prijs}-{max_prijs}"
    api_key = os.getenv('SCRAPEDO_KEY')

    url = f"https://api.scrape.do?token={api_key}&url={target_url}"

    try:
        print(f"[pararius] Ophalen via Scrape.do: {target_url}", flush=True)
        r = requests.get(url, timeout=60)
        print(f"[pararius] HTTP status: {r.status_code}", flush=True)
    except Exception as e:
        print(f"[pararius] ❌ Verbindingsfout: {e}", flush=True)
        return []

    if r.status_code != 200:
        print(f"[pararius] ⚠️ HTTP {r.status_code}", flush=True)
        print(f"[pararius] HTML snippet: {r.text[:800]}", flush=True)
        return []

    if "Just a moment" in r.text:
        print(f"[pararius] ⚠️ Cloudflare challenge nog actief!", flush=True)
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    woningen = []

    for item in soup.select('li.search-list__item--listing'):
        titel_el = item.select_one('.listing-search-item__title')
        prijs_el = item.select_one('.listing-search-item__price')
        link_el  = item.select_one('a.listing-search-item__link--title')

        if not titel_el or not prijs_el or not link_el:
            continue

        woningen.append({
            'titel': titel_el.text.strip(),
            'prijs': prijs_el.text.strip(),
            'link':  BASE_URL + link_el['href'],
            'bron':  'pararius.nl'
        })

    if len(woningen) == 0:
        print(f"[pararius] ⚠️ 0 woningen gevonden!", flush=True)
        print(f"[pararius] HTML snippet: {r.text[:800]}", flush=True)
    else:
        print(f"[pararius] ✅ {len(woningen)} woningen gevonden", flush=True)

    return woningen
