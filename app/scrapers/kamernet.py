import re
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://kamernet.nl"
FLARESOLVERR_URL = "http://flaresolverr:8191/v1"

# Mapping van type_woning naar Kamernet URL-segment
TYPE_SEGMENT = {
    "kamer":            "room",
    "appartement":      "apartment",
    "studio":           "studio",
    "studentenwoning":  "student-housing",
    "gemeubileerd":     "furnished-apartments",
    "anti-kraak":       "apartment",  # geen aparte pagina, filter handmatig
}


def _fetch(url: str) -> str | None:
    """Probeer eerst direct; val terug op FlareSolverr bij blokkade."""
    # Stap 1: direct request
    try:
        r = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        if r.status_code == 200 and "Just a moment" not in r.text:
            print(f"[kamernet] ✅ Direct request gelukt", flush=True)
            return r.text
        print(f"[kamernet] Direct request geblokkeerd (status {r.status_code}), probeer FlareSolverr...", flush=True)
    except Exception as e:
        print(f"[kamernet] Direct request mislukt ({e}), probeer FlareSolverr...", flush=True)

    # Stap 2: FlareSolverr fallback
    try:
        r = requests.post(FLARESOLVERR_URL, json={
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000
        }, timeout=70)
        data = r.json()
        status = data.get("status")
        print(f"[kamernet] FlareSolverr status: {status}", flush=True)
        if status == "ok":
            return data["solution"]["response"]
        print(f"[kamernet] ⚠️ FlareSolverr fout: {data.get('message')}", flush=True)
    except Exception as e:
        print(f"[kamernet] ❌ FlareSolverr verbindingsfout: {e}", flush=True)

    return None


def _parse_prijs(text: str) -> int | None:
    # Haal cijfers op uit tekst zoals "€ 1.250 /mnd" → 1250
    cleaned = text.replace(".", "").replace(",", "")
    match = re.search(r"\d+", cleaned)
    return int(match.group()) if match else None


def _parse_listings(html: str, stad: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Kamernet gebruikt div[data-listing-id] of vergelijkbare containers
    # Probeer meerdere selectors om robuust te zijn tegen layout-wijzigingen
    items = (
        soup.select("div[data-listing-id]") or
        soup.select("div.tile") or
        soup.select("article.listing-item") or
        soup.select("div[class*='RoomTile'], div[class*='SearchResult']")
    )

    for item in items:
        # URL
        link_el = item.select_one("a[href*='/huren/']")
        if not link_el:
            link_el = item.select_one("a[href]")
        if not link_el:
            continue

        href = link_el.get("href", "")
        if not href:
            continue
        if not href.startswith("http"):
            href = BASE_URL + href

        # Sla niet-listing URLs over
        if "/huren/" not in href and "kamernet.nl" not in href:
            continue

        # external_id uit URL (numeriek ID)
        id_match = re.search(r"/(\d{4,})", href)
        external_id = id_match.group(1) if id_match else None

        # Adres — probeer meerdere selectors
        adres = None
        for sel in ["h2", "h3", "[class*='title']", "[class*='Title']", "[class*='address']", "[class*='Address']"]:
            el = item.select_one(sel)
            if el and el.text.strip():
                adres = el.text.strip()
                break

        # Prijs
        prijs = None
        for sel in ["[class*='price']", "[class*='Price']", "[class*='prijs']", "[class*='rent']", "[class*='Rent']"]:
            el = item.select_one(sel)
            if el:
                prijs = _parse_prijs(el.text)
                if prijs:
                    break

        # Oppervlakte
        oppervlakte = None
        for sel in ["[class*='surface']", "[class*='Surface']", "[class*='size']", "[class*='Size']", "[class*='m2']"]:
            el = item.select_one(sel)
            if el:
                m = re.search(r"(\d+)", el.text)
                if m:
                    oppervlakte = int(m.group(1))
                    break

        # Type woning
        type_woning = None
        for sel in ["[class*='type']", "[class*='Type']", "[class*='kind']", "[class*='Kind']", "[class*='category']"]:
            el = item.select_one(sel)
            if el and el.text.strip():
                type_woning = el.text.strip().lower()
                break

        # Eerste foto
        foto_url = None
        img_el = item.select_one("img[src]")
        if img_el:
            src = img_el.get("src", "")
            if src and not src.endswith(".svg"):
                foto_url = src if src.startswith("http") else BASE_URL + src

        results.append({
            "source": "kamernet",
            "url": href,
            "external_id": external_id,
            "adres": adres,
            "stad": stad,
            "prijs": prijs,
            "oppervlakte": oppervlakte,
            "type_woning": type_woning,
            "foto_url": foto_url,
            "beschikbaar": True,
        })

    return results


def scrape_kamernet(stad: str, min_prijs: int, max_prijs: int, types: list[str]) -> list[dict]:
    """Geeft lijst van listing-dicts terug voor Kamernet."""
    stad_slug = stad.lower().replace(" ", "-")

    gemeubileerd_filter = "gemeubileerd" in types
    scrape_types = [t for t in types if t != "gemeubileerd"]

    # Als alleen 'gemeubileerd' geselecteerd is, gebruik appartementen als basis
    if not scrape_types:
        scrape_types = ["appartement"]

    urls_to_scrape = []
    for type_woning in scrape_types:
        segment = TYPE_SEGMENT.get(type_woning)
        if not segment:
            print(f"[kamernet] ⚠️ Onbekend type: {type_woning}, overgeslagen", flush=True)
            continue
        url =f"{BASE_URL}/en/for-rent/{segment}-{stad_slug}?maxRent={max_prijs}&minRent={min_prijs}"
        if gemeubileerd_filter:
            url += "&furnishing=furnished"
        urls_to_scrape.append(url)

    all_listings: list[dict] = []
    seen_urls: set[str] = set()

    for url in urls_to_scrape:
        print(f"[kamernet] Ophalen: {url}", flush=True)
        html = _fetch(url)
        if not html:
            print(f"[kamernet] ⚠️ Geen HTML ontvangen voor {url}", flush=True)
            continue

        listings = _parse_listings(html, stad)
        for listing in listings:
            if listing["url"] not in seen_urls:
                seen_urls.add(listing["url"])
                all_listings.append(listing)

    if all_listings:
        print(f"[kamernet] ✅ {len(all_listings)} woningen gevonden voor {stad}", flush=True)
    else:
        print(f"[kamernet] ⚠️ 0 woningen gevonden voor {stad}", flush=True)

    return all_listings


if __name__ == "__main__":
    # Testrun: python app/scrapers/kamernet.py
    resultaten = scrape_kamernet(
        stad="den-haag",
        min_prijs=500,
        max_prijs=1500,
        types=["appartement", "studio"]
    )
    for w in resultaten:
        print(w)
