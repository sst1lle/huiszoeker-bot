from curl_cffi import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.pararius.nl"

def scrape_pararius(stad='den-haag', min_prijs=0, max_prijs=1200):
    url = f"https://www.pararius.nl/huurwoningen/{stad}/{min_prijs}-{max_prijs}"

    try:
        print(f"[pararius] Ophalen: {url}", flush=True)
        # impersonate='chrome' bootst de echte Chrome TLS fingerprint na — omzeilt Cloudflare
        r = requests.get(url, impersonate="chrome", timeout=20)
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
        print(f"[pararius] HTML snippet: {r.text[:800]}", flush=True)
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
