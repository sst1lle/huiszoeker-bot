import re
import logging
from datetime import datetime
from bs4 import BeautifulSoup

from shared.cities import canonical_city, stad_slugs_uit_pref
from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://kamernet.nl"

# Mapping van type_woning naar Kamernet URL-segment
TYPE_SEGMENT = {
    "kamer":            "room",
    "appartement":      "apartment",
    "studio":           "studio",
    "studentenwoning":  "student-housing",
    "gemeubileerd":     "furnished-apartments",
    "anti-kraak":       "apartment",  # geen aparte pagina, filter handmatig
}

# Mapping van Engelse Kamernet typenamen naar Nederlands
_TYPE_NL = {
    "apartment": "appartement",
    "room": "kamer",
    "studio": "studio",
    "student housing": "studentenwoning",
    "anti-squat": "anti-kraak",
}



def _parse_prijs(text: str) -> int | None:
    # Haal cijfers op uit tekst zoals "€ 1.250 /mnd" → 1250
    cleaned = text.replace(".", "").replace(",", "")
    match = re.search(r"\d+", cleaned)
    return int(match.group()) if match else None


def _parse_listings(html: str, stad: str, scraped_at: str) -> list[dict]:
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
            "scraped_at": scraped_at,
            "omschrijving": None,
            "rating": None,
            "rating_details": None,
        })

    return results


class KamernetScraper(BaseScraper):
    name = "kamernet"
    robots_txt_compliant = True
    request_delay_seconds = 2.0
    allow_flaresolverr = False  # kamernet werkt direct; Byparr hangt 70s op networkidle (SPA wordt nooit idle)

    def _scrape_impl(
        self,
        stad: str,
        min_prijs: int,
        max_prijs: int,
        types: list[str],
    ) -> list[dict]:
        scraped_at = datetime.utcnow().isoformat()

        gemeubileerd_filter = "gemeubileerd" in types
        scrape_types = [t for t in types if t != "gemeubileerd"]

        # Geen filter ingesteld → standaard appartement, studio, anti-kraak
        if not scrape_types:
            scrape_types = ["appartement", "studio", "anti-kraak"]

        # Eén voorkeur kan meerdere steden bevatten ("utrecht, amsterdam"). Kamernet
        # ondersteunt geen komma-gescheiden steden in één URL → splits in losse requests per stad.
        steden = stad_slugs_uit_pref(stad)

        all_listings: list[dict] = []
        seen_urls: set[str] = set()  # gedeeld over alle steden + woningtypes om dubbels te voorkomen

        for enkele_stad in steden:
            stad_slug = canonical_city(enkele_stad)
            base_urls = []
            for type_woning in scrape_types:
                segment = TYPE_SEGMENT.get(type_woning)
                if not segment:
                    logger.warning(f"[{self.name}] Onbekend type: {type_woning}, overgeslagen")
                    continue
                url = f"{BASE_URL}/en/for-rent/{segment}-{stad_slug}?maxRent={max_prijs}&minRent={min_prijs}"
                if gemeubileerd_filter:
                    url += "&furnishing=furnished"
                base_urls.append(url)

            # Per woningtype pagineren (Kamernet toont nieuwste eerst; paginering via &pageNo=N),
            # met early-stop zodra een pagina geen nieuwe listings oplevert. De individuele stad
            # gaat mee in elke listing (c=enkele_stad) voor correcte matching/notificaties.
            for base in base_urls:
                def page_url(page: int, base=base) -> str:
                    return base if page == 1 else f"{base}&pageNo={page}"
                all_listings += self._scrape_paginated(
                    page_url,
                    lambda html, c=enkele_stad: _parse_listings(html, c, scraped_at),
                    seen_this_run=seen_urls,
                )

        logger.info(f"[{self.name}] {len(all_listings)} woningen gevonden voor {stad}")
        return all_listings


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    stad = sys.argv[1] if len(sys.argv) > 1 else "den-haag"
    scraper = KamernetScraper()
    resultaten = scraper.scrape(
        stad=stad,
        min_prijs=500,
        max_prijs=1500,
        types=["appartement", "studio"]
    )
    for w in resultaten:
        print(w)
