import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.pararius.nl"

def scrape_pararius(stad='den-haag', min_prijs=0, max_prijs=1200):
    SITE_URL = f"https://www.pararius.nl/huurwoningen/{stad}/{min_prijs}-{max_prijs}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    try:
        r = requests.get(SITE_URL, headers=headers, timeout=15)
    except Exception as e:
        print(f"[pararius] ❌ Verbindingsfout: {e}", flush=True)
        return []

    if r.status_code != 200:
        print(f"[pararius] ⚠️ HTTP status {r.status_code} voor URL: {SITE_URL}", flush=True)
        return []

    soup = BeautifulSoup(r.text, 'html.parser')

    woningen = []

    for item in soup.select('li.search-list__item--listing'):
        titel_el = item.select_one('.listing-search-item__title')
        prijs_el = item.select_one('.listing-search-item__price')
        link_el  = item.select_one('a.listing-search-item__link--title')

        if not titel_el or not prijs_el or not link_el:
            continue

        titel = titel_el.text.strip()
        prijs = prijs_el.text.strip()
        link  = BASE_URL + link_el['href']

        woningen.append({
            'titel': titel,
            'prijs': prijs,
            'link': link,
            'bron': 'pararius.nl'
        })

    if len(woningen) == 0:
        print(f"[pararius] ⚠️ 0 woningen gevonden! Mogelijk geblokkeerd of HTML-structuur gewijzigd.", flush=True)
        print(f"[pararius] ⚠️ Gebruikte URL: {SITE_URL}", flush=True)
        print(f"[pararius] ⚠️ HTTP status: {r.status_code}", flush=True)
        # Dump een stukje HTML om te debuggen
        print(f"[pararius] ⚠️ HTML snippet (eerste 500 chars): {r.text[:500]}", flush=True)
    else:
        print(f"[pararius] ✅ {len(woningen)} woningen gevonden", flush=True)

    return woningen
