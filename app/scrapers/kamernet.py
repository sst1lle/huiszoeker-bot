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


# Mapping van Engelse Kamernet typenamen naar Nederlands
_TYPE_NL = {
    "apartment": "appartement",
    "room": "kamer",
    "studio": "studio",
    "student housing": "studentenwoning",
    "anti-squat": "anti-kraak",
}


def _parse_listings(html: str, stad: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Elke listing is een <a class="... SearchResultCard_root__* ...">
    # De CSS-module hash (__hSxn3) kan veranderen bij builds, dus [class*=] gebruiken
    items = soup.select('a[class*="SearchResultCard_root"]')

    for item in items:
        # URL (het <a> element IS de container)
        href = item.get("href", "")
        if not href or "/for-rent/" not in href:
            continue
        if not href.startswith("http"):
            href = BASE_URL + href

        # external_id: URL eindigt op "type-{id}", bijv. "apartment-2365513"
        id_match = re.search(r"-(\d+)$", href)
        external_id = id_match.group(1) if id_match else None

        # Foto: <img class="... SearchResultCard_media__* ...">
        foto_url = None
        img_el = item.select_one('img[class*="SearchResultCard_media"]')
        if not img_el:
            img_el = item.select_one("img[src]")
        if img_el:
            src = img_el.get("src", "")
            if src and not src.endswith(".svg"):
                foto_url = src if src.startswith("http") else BASE_URL + src

        # Content rows: elke <div class="SearchResultCard_contentRow__*">
        # Rij 0: adres ("Dorpsstraat, Den Haag")
        # Rij 1: details ("120 m²", "furnished", "Apartment")
        # Rij 2: beschikbaarheid ("From 1 Apr 2026")
        # Rij 3 (laatste): prijs ("€1,575 /month")
        rows = item.select('div[class*="SearchResultCard_contentRow"]')

        # Adres uit rij 0: twee spans samenvoegen
        adres = None
        if rows:
            spans = rows[0].select("span")
            parts = [s.text.strip().rstrip(",") for s in spans if s.text.strip()]
            if parts:
                adres = ", ".join(parts)

        # Oppervlakte en type uit rij 1
        oppervlakte = None
        type_woning = None
        if len(rows) > 1:
            # Type: <p class="... MuiTypography-noWrap ..."> — stabiele MUI-klasse
            type_el = rows[1].select_one("p.MuiTypography-noWrap")
            if type_el:
                raw_type = type_el.text.strip().lower()
                type_woning = _TYPE_NL.get(raw_type, raw_type)

            # Oppervlakte: p met "m²" in de tekst
            for p in rows[1].select("p"):
                if "m²" in p.text:
                    m = re.search(r"(\d+)", p.text)
                    if m:
                        oppervlakte = int(m.group(1))
                    break

        # Prijs uit laatste rij: <span class="... MuiTypography-h5 ...">
        prijs = None
        if rows:
            price_span = rows[-1].select_one("span.MuiTypography-h5")
            if price_span:
                prijs = _parse_prijs(price_span.text)

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
