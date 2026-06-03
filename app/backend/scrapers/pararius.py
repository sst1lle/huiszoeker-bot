import re
import logging
from datetime import datetime
from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.pararius.nl"


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
    if any(x in text for x in ["verhuurd", "onder optie", "onder bod", "rented", "option", "under offer"]):
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


class ParariusScraper(BaseScraper):
    name = "pararius"
    robots_txt_compliant = True
    request_delay_seconds = 2.0
    uses_types = False  # Pararius-URL heeft geen type-filter; retourneert altijd alle typen
    uses_price_filter = False  # prijsfilter gebeurt centraal in SQL per user
    flaresolverr_only = True

    def _scrape_impl(
        self,
        stad: str,
        min_prijs: int,
        max_prijs: int,
        types: list[str],
    ) -> list[dict]:
        base = f"{BASE_URL}/huurwoningen/{stad}"

        # Pararius toont standaard de nieuwste listings eerst; paginering via /page-N
        def page_url(page: int) -> str:
            return base if page == 1 else f"{base}/page-{page}"

        return self._scrape_paginated(page_url, lambda html: self._parse_html(html, stad))

    def _parse_html(self, html: str, stad: str) -> list[dict]:
        if "Just a moment" in html:
            logger.warning(f"[{self.name}] Cloudflare blocking detected")
            return []

        soup = BeautifulSoup(html, "html.parser")
        woningen = []
        scraped_at = datetime.utcnow().isoformat()

        items = soup.select(
            "section.listing-search-item, li.search-list__item--listing"
        )

        if not items:
            logger.warning(f"[{self.name}] geen listings gevonden")
            logger.debug(html[:800])
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
                "foto_url": _extract_image(item),
                "beschikbaar": _check_beschikbaar(item),
                "scraped_at": scraped_at,
                "omschrijving": None,
                "rating": None,
                "rating_details": None,
            }

            woningen.append(woning)

        logger.info(f"[{self.name}] gevonden: {len(woningen)} woningen")
        return woningen


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    stad = sys.argv[1] if len(sys.argv) > 1 else "den-haag"
    scraper = ParariusScraper()
    resultaten = scraper.scrape(stad=stad, min_prijs=500, max_prijs=1500, types=[])
    for w in resultaten:
        print(w)
