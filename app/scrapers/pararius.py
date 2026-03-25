import re
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.pararius.nl"
FLARESOLVERR_URL = "http://flaresolverr:8191/v1"


def _parse_prijs(text: str) -> int | None:
    if not text:
        return None
    cleaned = text.replace(".", "").replace(",", "")
    match = re.search(r"\d+", cleaned)
    return int(match.group()) if match else None


def _extract_external_id(href: str) -> str | None:
    try:
        parts = href.strip("/").split("/")
        if len(parts) >= 3 and re.fullmatch(r"[a-f0-9]{8}", parts[2], re.I):
            return parts[2]
    except Exception:
        pass
    return None


def _extract_oppervlakte(item) -> int | None:
    for feat in item.select(".listing-search-item__features li"):
        text = feat.get_text(strip=True)
        if "m²" in text:
            m = re.search(r"(\d+)", text)
            if m:
                return int(m.group(1))
    return None


def _check_beschikbaar(item) -> bool:
    text = item.get_text(" ", strip=True).lower()
    if any(x in text for x in ["verhuurd", "onder optie", "rented", "option"]):
        return False
    return True


def _extract_image(item) -> str | None:
    """
    Robuuste image extractor:
    - data-src (lazy loading)
    - srcset (eerste image pakken)
    - fallback src
    """
    img = item.select_one("img")

    if not img:
        return None

    # 1. data-src (meest voorkomend bij Pararius)
    if img.get("data-src"):
        return img["data-src"]

    # 2. srcset (pak eerste URL)
    if img.get("srcset"):
        srcset = img["srcset"].split(",")[0].strip().split(" ")[0]
        return srcset

    # 3. fallback
    if img.get("src"):
        return img["src"]

    return None


def scrape_pararius(
    stad: str = "den-haag",
    min_prijs: int = 0,
    max_prijs: int = 1200
) -> list[dict]:

    target_url = f"{BASE_URL}/huurwoningen/{stad}/{min_prijs}-{max_prijs}"

    try:
        print(f"[pararius] Fetch via FlareSolverr: {target_url}")

        r = requests.post(
            FLARESOLVERR_URL,
            json={
                "cmd": "request.get",
                "url": target_url,
                "maxTimeout": 60000
            },
            timeout=70
        )

        data = r.json()

        if data.get("status") != "ok":
            print(f"[pararius] FlareSolverr error: {data}")
            return []

        html = data["solution"]["response"]

    except Exception as e:
        print(f"[pararius] Connection error: {e}")
        return []

    if "Just a moment" in html:
        print("[pararius] Cloudflare blocking detected")
        return []

    soup = BeautifulSoup(html, "html.parser")
    woningen = []

    items = soup.select(
        "section.listing-search-item, li.search-list__item--listing"
    )

    if not items:
        print("[pararius] WARNING: geen listings gevonden")
        print(html[:800])
        return []

    for item in items:
        titel_el = item.select_one(".listing-search-item__title a")
        prijs_el = item.select_one(".listing-search-item__price")

        if not titel_el or not prijs_el:
            continue

        href = titel_el.get("href")
        if not href:
            continue

        full_url = BASE_URL + href

        woning = {
            "source": "pararius",
            "url": full_url,
            "external_id": _extract_external_id(href),
            "adres": titel_el.get_text(strip=True),
            "stad": stad,
            "prijs": _parse_prijs(prijs_el.get_text()),
            "oppervlakte": _extract_oppervlakte(item),
            "type_woning": None,
            "beschikbaar": _check_beschikbaar(item),
            "foto_url": _extract_image(item),
        }

        woningen.append(woning)

    print(f"[pararius] gevonden: {len(woningen)} woningen")

    return woningen