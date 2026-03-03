from curl_cffi import requests
from bs4 import BeautifulSoup


def scrape_huurwoningen(stad='den-haag', min_prijs=0, max_prijs=1200):
    url = f"https://www.huurwoningen.nl/in/{stad}/?price={min_prijs}-{max_prijs}"

    try:
        print(f"[huurwoningen] Ophalen: {url}", flush=True)
        r = requests.get(url, impersonate="chrome", timeout=20)
        print(f"[huurwoningen] HTTP status: {r.status_code}", flush=True)
    except Exception as e:
        print(f"[huurwoningen] ❌ Verbindingsfout: {e}", flush=True)
        return []

    if r.status_code != 200:
        print(f"[huurwoningen] ⚠️ HTTP {r.status_code}", flush=True)
        print(f"[huurwoningen] HTML snippet: {r.text[:800]}", flush=True)
        return []

    if "Just a moment" in r.text:
        print(f"[huurwoningen] ⚠️ Cloudflare challenge nog actief!", flush=True)
        print(f"[huurwoningen] HTML snippet: {r.text[:800]}", flush=True)
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    woningen = []

    for item in soup.select("article.listing-search-item"):
        try:
            titel_el = item.select_one(".listing-search-item__title a")
            prijs_el = item.select_one(".listing-search-item__price")

            if not titel_el or not prijs_el:
                continue

            woningen.append({
                "titel": titel_el.text.strip(),
                "prijs": prijs_el.text.strip(),
                "link":  titel_el.get("href"),
                "bron":  "huurwoningen.nl"
            })
        except:
            continue

    if len(woningen) == 0:
        print(f"[huurwoningen] ⚠️ 0 woningen gevonden!", flush=True)
        print(f"[huurwoningen] HTML snippet: {r.text[:800]}", flush=True)
    else:
        print(f"[huurwoningen] ✅ {len(woningen)} woningen gevonden.", flush=True)

    return woningen
