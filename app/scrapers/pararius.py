import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.pararius.nl"
FLARESOLVERR_URL = "http://flaresolverr:8191/v1"

def scrape_pararius(stad='den-haag', min_prijs=0, max_prijs=1200):
    target_url = f"https://www.pararius.nl/huurwoningen/{stad}/{min_prijs}-{max_prijs}"

    try:
        print(f"[pararius] Ophalen via FlareSolverr: {target_url}", flush=True)
        r = requests.post(FLARESOLVERR_URL, json={
            "cmd": "request.get",
            "url": target_url,
            "maxTimeout": 60000
        }, timeout=70)

        data = r.json()
        status = data.get("status")
        print(f"[pararius] FlareSolverr status: {status}", flush=True)

        if status != "ok":
            print(f"[pararius] ⚠️ FlareSolverr fout: {data.get('message')}", flush=True)
            return []

        html = data["solution"]["response"]

    except Exception as e:
        print(f"[pararius] ❌ Verbindingsfout: {e}", flush=True)
        return []

    if "Just a moment" in html:
        print(f"[pararius] ⚠️ Cloudflare challenge nog actief!", flush=True)
        return []

    soup = BeautifulSoup(html, 'html.parser')
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
        print(f"[pararius] HTML snippet: {html[:800]}", flush=True)
    else:
        print(f"[pararius] ✅ {len(woningen)} woningen gevonden", flush=True)

    return woningen
