import re
import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT = 15
_MIN_CARDS_THRESHOLD = 3  # below this → fallback to FlareSolverr


def _fetch_html(url: str, site_label: str) -> tuple[str | None, str]:
    """
    Fetch HTML via direct requests. Falls back to FlareSolverr if fewer than
    _MIN_CARDS_THRESHOLD cards are detected (JS-rendered page guard).
    Returns (html, method_used).
    """
    try:
        r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": _UA}, allow_redirects=True)
        if r.status_code == 200:
            html = r.text
            # Quick sniff: count project-card indicators before full parse
            rough_count = html.count("project-card") + html.count("<article")
            if rough_count >= _MIN_CARDS_THRESHOLD:
                logger.info(f"[nieuwbouw] {site_label}: using requests")
                return html, "requests"
            logger.info(
                f"[nieuwbouw] {site_label}: requests returned {rough_count} card hints "
                f"(< {_MIN_CARDS_THRESHOLD}) — switching to FlareSolverr"
            )
        else:
            logger.warning(f"[nieuwbouw] {site_label}: HTTP {r.status_code} — switching to FlareSolverr")
    except Exception as e:
        logger.warning(f"[nieuwbouw] {site_label}: requests mislukt ({e}) — switching to FlareSolverr")

    try:
        html = BaseScraper.flare_get(url)
        logger.info(f"[nieuwbouw] {site_label}: using flaresolverr")
        return html, "flaresolverr"
    except Exception as e:
        logger.error(f"[nieuwbouw] {site_label}: FlareSolverr ook mislukt: {e}")
        return None, "failed"


def _parse_prijzen(text: str) -> tuple[int | None, int | None]:
    """Extract (price_min, price_max) from strings like '€250.000,- tot €650.000,-'."""
    bedragen = re.findall(r"€\s*([\d.]+)", text)
    vals = []
    for b in bedragen:
        cleaned = re.sub(r"\.", "", b)
        try:
            vals.append(int(cleaned))
        except ValueError:
            pass
    vals = [v for v in vals if v > 100]
    if not vals:
        return None, None
    return min(vals), max(vals)


# ─── nieuwbouw-nederland.nl ───────────────────────────────────────────────────
# Actual HTML structure (verified):
#   <article class="odd first">
#     <h2><a href="...">Title</a></h2>
#     <span class="prijs">€250.000,- tot €650.000,-</span>
#     <span class="segment">Koop (306)</span>
#     <span class="extra"><span class="plaats">Amsterdam</span></span>
#   </article>

def _scrape_nieuwbouw_nederland(stad: str) -> list[dict]:
    url = f"https://www.nieuwbouw-nederland.nl/projecten/?place={stad}"
    logger.info(f"[nieuwbouw] Fetching nieuwbouw-nederland.nl for stad: {stad}")

    html, method = _fetch_html(url, "nieuwbouw-nederland.nl")
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("article")
    logger.info(f"[nieuwbouw] nieuwbouw-nederland.nl ({method}): {len(cards)} raw cards for '{stad}'")

    projecten = []
    scraped_at = datetime.now(timezone.utc).isoformat()

    for card in cards:
        try:
            h2 = card.find("h2")
            if not h2:
                continue
            a_tag = h2.find("a", href=True)
            if not a_tag:
                continue
            href = a_tag["href"]
            if not href.startswith("http"):
                href = "https://www.nieuwbouw-nederland.nl" + href
            title = a_tag.get_text(strip=True)
            if not title:
                continue

            plaats_el = card.find("span", class_="plaats")
            city = plaats_el.get_text(strip=True) if plaats_el else stad

            segment_el = card.find("span", class_="segment")
            segment_text = segment_el.get_text(strip=True).lower() if segment_el else ""
            if "koop" in segment_text:
                type_ = "koop"
            elif "huur" in segment_text:
                type_ = "huur"
            else:
                type_ = None

            units = None
            units_match = re.search(r"\((\d+)\)", segment_text)
            if units_match:
                units = int(units_match.group(1))

            prijs_el = card.find("span", class_="prijs")
            price_min, price_max = _parse_prijzen(prijs_el.get_text() if prijs_el else "")

            projecten.append({
                "title": title,
                "developer": None,
                "city": city,
                "type": type_,
                "price_min": price_min,
                "price_max": price_max,
                "units": units,
                "expected_date": None,
                "url": href,
                "scraped_at": scraped_at,
            })
        except Exception as e:
            logger.debug(f"[nieuwbouw-nederland.nl] Kaart parse fout: {e}")

    logger.info(
        f"[nieuwbouw] nieuwbouw-nederland.nl: {len(projecten)} bruikbare projecten "
        f"na filtering voor '{stad}'"
    )
    return projecten


# ─── nieuwbouw.nl ─────────────────────────────────────────────────────────────
# Actual HTML structure (verified, Livewire/Alpine.js, server-rendered):
#   <div data-gtm-track="project-card" data-project-id="01H963..." wire:key="project-01H963...">
#     <h3 class="text-blue text-base font-semibold ...">Project Title</h3>
#     ... (Tailwind classes, no stable non-utility class names)
#   </div>
# URL: constructed as https://nieuwbouw.nl/project/{data-project-id}/
# for koop: /aanbod/koop/?locatie={stad}

def _scrape_nieuwbouw_nl(stad: str) -> list[dict]:
    projecten = []
    scraped_at = datetime.now(timezone.utc).isoformat()

    for type_ in ("huur", "koop"):
        url = f"https://nieuwbouw.nl/aanbod/{type_}/?locatie={stad}"
        logger.info(f"[nieuwbouw] Fetching nieuwbouw.nl/{type_} for stad: {stad}")

        html, method = _fetch_html(url, f"nieuwbouw.nl/{type_}")
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select('div[data-gtm-track="project-card"]')
        logger.info(
            f"[nieuwbouw] nieuwbouw.nl/{type_} ({method}): {len(cards)} raw cards for '{stad}'"
        )

        for card in cards:
            try:
                project_id = card.get("data-project-id", "")

                # URL: prefer an <a href> in the card, fall back to id-based URL
                a_tag = card.find("a", href=True)
                if a_tag:
                    href = a_tag["href"]
                    if not href.startswith("http"):
                        href = "https://nieuwbouw.nl" + href
                elif project_id:
                    href = f"https://nieuwbouw.nl/project/{project_id}/"
                else:
                    continue

                title_el = card.find("h3")
                title = title_el.get_text(strip=True) if title_el else None
                if not title:
                    continue

                # City: look for small location text (typically after a pin icon)
                # Tailwind classes aren't stable so search all small/p/span tags
                city = stad
                for el in card.find_all(["p", "span", "div"]):
                    txt = el.get_text(strip=True)
                    # Heuristic: short text without numbers that isn't the title
                    if txt and len(txt) < 40 and txt != title and not re.search(r"\d", txt):
                        city = txt
                        break

                # Price: look for any element containing "€"
                price_min = price_max = None
                for el in card.find_all(string=re.compile(r"€")):
                    pm, px = _parse_prijzen(el)
                    if pm:
                        price_min = min(pm, price_min) if price_min else pm
                    if px:
                        price_max = max(px, price_max) if price_max else px

                # Units: "X woningen" / "X appartementen"
                units = None
                card_text = card.get_text(" ", strip=True)
                units_match = re.search(r"(\d+)\s*(?:woningen|appartementen|units)", card_text, re.I)
                if units_match:
                    units = int(units_match.group(1))

                # Expected date
                date_match = re.search(
                    r"(?:oplevering|verwacht|Q[1-4])\s*:?\s*((?:Q[1-4]\s*)?20\d{2})",
                    card_text, re.I
                )
                expected_date = date_match.group(1).strip() if date_match else None

                projecten.append({
                    "title": title,
                    "developer": None,
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
                logger.debug(f"[nieuwbouw.nl/{type_}] Kaart parse fout: {e}")

        count_type = sum(1 for p in projecten if p["type"] == type_)
        logger.info(
            f"[nieuwbouw] nieuwbouw.nl/{type_}: {count_type} bruikbare projecten voor '{stad}'"
        )

    return projecten


# ─── Scraper class ────────────────────────────────────────────────────────────

class NieuwbouwScraper(BaseScraper):
    name = "nieuwbouw"
    excluded_from_main_loop = True  # wekelijks via APScheduler, niet per 15 min

    def scrape(self, stad, min_prijs, max_prijs, types, radius_km=None):
        return []

    def scrape_projecten(self, steden: list[str]) -> list[dict]:
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

                before = len(alle)
                for p in projecten:
                    if p["url"] not in seen_urls:
                        seen_urls.add(p["url"])
                        alle.append(p)

                logger.info(
                    f"[nieuwbouw] {site_naam} voor '{stad}': "
                    f"{len(projecten)} gevonden, {len(alle) - before} nieuw na dedup"
                )

        logger.info(f"[nieuwbouw] Totaal: {len(alle)} unieke projecten over {len(steden)} stad(en)")
        return alle
