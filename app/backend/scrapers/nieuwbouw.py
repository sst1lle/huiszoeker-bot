import re
import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 15


def _get(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": _UA})
        if r.status_code != 200:
            logger.warning(f"[nieuwbouw] HTTP {r.status_code}: {url}")
            return None
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        logger.warning(f"[nieuwbouw] Request mislukt ({url}): {e}")
        return None


def _parse_prijs(text: str) -> int | None:
    cleaned = re.sub(r"[^\d]", "", text)
    return int(cleaned) if cleaned else None


def _scrape_nieuwbouw_nederland(stad: str) -> list[dict]:
    """
    Scrapes nieuwbouw-nederland.nl/projecten/?place={stad}
    Kaartstructuur (per augustus 2024): article.project-item of div[class*=project]
    """
    url = f"https://www.nieuwbouw-nederland.nl/projecten/?place={stad}"
    soup = _get(url)
    if not soup:
        return []

    projecten = []
    scraped_at = datetime.now(timezone.utc).isoformat()

    cards = (
        soup.select("article.project-item")
        or soup.select("div[class*='project-card']")
        or soup.select("div[class*='project-item']")
        or soup.select(".projects-list article")
    )

    for card in cards:
        try:
            # URL
            a = card.select_one("a[href]")
            if not a:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.nieuwbouw-nederland.nl" + href

            # Titel
            title_el = card.select_one("h2, h3, .project-title, [class*='title']")
            title = title_el.get_text(strip=True) if title_el else None
            if not title:
                continue

            # Stad
            loc_el = card.select_one(".project-location, [class*='location'], [class*='place']")
            city = loc_el.get_text(strip=True) if loc_el else stad

            # Developer
            dev_el = card.select_one(".developer, [class*='developer'], [class*='builder'], [class*='aannemer']")
            developer = dev_el.get_text(strip=True) if dev_el else None

            # Type (huur/koop) — zoek in tekst van de kaart
            card_text = card.get_text(" ", strip=True).lower()
            if "huur" in card_text:
                type_ = "huur"
            elif "koop" in card_text:
                type_ = "koop"
            else:
                type_ = None

            # Prijsrange
            prijs_els = card.select("[class*='price'], [class*='prijs'], .price")
            price_min = price_max = None
            for el in prijs_els:
                nums = re.findall(r"[\d.,]+", el.get_text())
                nums = [_parse_prijs(n) for n in nums if _parse_prijs(n) and _parse_prijs(n) > 100]
                if nums:
                    price_min = min(nums) if price_min is None else min(price_min, *nums)
                    price_max = max(nums) if price_max is None else max(price_max, *nums)

            # Aantal woningen
            units = None
            units_match = re.search(r"(\d+)\s*(?:woningen|appartementen|units)", card_text)
            if units_match:
                units = int(units_match.group(1))

            # Opleverdatum
            expected_date = None
            date_el = card.select_one("[class*='date'], [class*='oplevering'], [class*='delivery']")
            if date_el:
                expected_date = date_el.get_text(strip=True)
            else:
                date_match = re.search(
                    r"(?:oplevering|verwacht|oplever)\s*:?\s*([\w\s]+(?:20\d{2}))",
                    card_text,
                    re.IGNORECASE,
                )
                if date_match:
                    expected_date = date_match.group(1).strip()

            projecten.append({
                "title": title,
                "developer": developer,
                "city": city,
                "type": type_,
                "price_min": price_min,
                "price_max": price_max,
                "units": units,
                "expected_date": expected_date,
                "url": href,
                "scraped_at": scraped_at,
            })
        except Exception as e:
            logger.debug(f"[nieuwbouw-nederland] Parse fout voor kaart: {e}")

    logger.info(f"[nieuwbouw-nederland] {len(projecten)} projecten gevonden voor '{stad}'")
    return projecten


def _scrape_nieuwbouw_nl(stad: str) -> list[dict]:
    """
    Scrapes nieuwbouw.nl/aanbod/huur en /aanbod/koop voor een stad.
    Kaartstructuur: .project-card of article[class*=project]
    """
    projecten = []
    scraped_at = datetime.now(timezone.utc).isoformat()

    for type_ in ("huur", "koop"):
        url = f"https://www.nieuwbouw.nl/aanbod/{type_}/?locatie={stad}"
        soup = _get(url)
        if not soup:
            continue

        cards = (
            soup.select(".project-card")
            or soup.select("article[class*='project']")
            or soup.select("div[class*='project-card']")
            or soup.select(".listing-item")
        )

        for card in cards:
            try:
                a = card.select_one("a[href]")
                if not a:
                    continue
                href = a["href"]
                if not href.startswith("http"):
                    href = "https://www.nieuwbouw.nl" + href

                title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='naam']")
                title = title_el.get_text(strip=True) if title_el else None
                if not title:
                    continue

                loc_el = card.select_one("[class*='location'], [class*='locatie'], [class*='city'], [class*='stad']")
                city = loc_el.get_text(strip=True) if loc_el else stad

                dev_el = card.select_one("[class*='developer'], [class*='ontwikkelaar'], [class*='builder']")
                developer = dev_el.get_text(strip=True) if dev_el else None

                card_text = card.get_text(" ", strip=True).lower()

                prijs_els = card.select("[class*='price'], [class*='prijs']")
                price_min = price_max = None
                for el in prijs_els:
                    nums = re.findall(r"[\d.,]+", el.get_text())
                    nums = [_parse_prijs(n) for n in nums if _parse_prijs(n) and _parse_prijs(n) > 100]
                    if nums:
                        price_min = min(nums) if price_min is None else min(price_min, *nums)
                        price_max = max(nums) if price_max is None else max(price_max, *nums)

                units = None
                units_match = re.search(r"(\d+)\s*(?:woningen|appartementen|units)", card_text)
                if units_match:
                    units = int(units_match.group(1))

                expected_date = None
                date_el = card.select_one("[class*='date'], [class*='oplevering'], [class*='delivery']")
                if date_el:
                    expected_date = date_el.get_text(strip=True)

                projecten.append({
                    "title": title,
                    "developer": developer,
                    "city": city,
                    "type": type_,
                    "price_min": price_min,
                    "price_max": price_max,
                    "units": units,
                    "expected_date": expected_date,
                    "url": href,
                    "scraped_at": scraped_at,
                })
            except Exception as e:
                logger.debug(f"[nieuwbouw.nl/{type_}] Parse fout voor kaart: {e}")

        logger.info(f"[nieuwbouw.nl/{type_}] {sum(1 for p in projecten if p['type'] == type_)} projecten voor '{stad}'")

    return projecten


class NieuwbouwScraper(BaseScraper):
    name = "nieuwbouw"
    excluded_from_main_loop = True  # wekelijks via APScheduler, niet per 15 min

    def scrape(self, stad, min_prijs, max_prijs, types, radius_km=None):
        return []

    def scrape_projecten(self, steden: list[str]) -> list[dict]:
        """
        Scrapes beide sites voor alle opgegeven steden.
        Per-site fouten worden gelogd en overgeslagen.
        """
        alle = []
        seen_urls: set[str] = set()

        for stad in steden:
            for scrape_fn, site_naam in [
                (_scrape_nieuwbouw_nederland, "nieuwbouw-nederland.nl"),
                (_scrape_nieuwbouw_nl, "nieuwbouw.nl"),
            ]:
                try:
                    projecten = scrape_fn(stad)
                except Exception as e:
                    logger.error(f"[nieuwbouw] {site_naam} fout voor '{stad}': {e}")
                    continue

                for p in projecten:
                    if p["url"] not in seen_urls:
                        seen_urls.add(p["url"])
                        alle.append(p)

        logger.info(f"[nieuwbouw] Totaal: {len(alle)} unieke projecten over {len(steden)} stad(en)")
        return alle
