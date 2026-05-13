"""
Nieuwbouw scraper — scrapet alle pagina's van beide sites, slaat landelijk op.
Stadsfiltering gebeurt in de dashboard query layer, niet hier.
"""
import re
import time
import traceback
import logging
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_TIMEOUT       = 15
_PAGE_DELAY    = 1.5   # seconden tussen paginaverzoeken (ethisch scrapen)
_MAX_PAGES     = 60    # harde limiet om oneindige loops te voorkomen
_STOP_IF_NO_NEW = 3    # stop na N opeenvolgende pagina's zonder nieuwe projecten
_GEO_SLEEP     = 1.05  # Nominatim eist ≥1 sec tussen verzoeken
_MAX_RUNTIME_S = 7200  # 2 uur absolute tijdslimiet per scraper

_HIDDEN_STATUSES = {"sold_out", "rented_out", "under_option", "registration_closed"}

# Meest specifieke patronen eerst om false positives te vermijden
_STATUS_KEYWORDS: list[tuple[str, str]] = [
    ("nog woningen beschikbaar",    "available"),
    ("woningen beschikbaar",        "available"),
    ("nog beschikbaar",             "available"),
    ("in verhuur",                  "available"),
    ("in verkoop",                  "available"),
    ("beschikbaar",                 "available"),
    ("volledig verkocht",           "sold_out"),
    ("uitverkocht",                 "sold_out"),
    ("volledig verhuurd",           "rented_out"),
    ("verhuurd",                    "rented_out"),
    ("onder optie",                 "under_option"),
    ("inschrijving is gesloten",    "registration_closed"),
    ("inschrijving gesloten",       "registration_closed"),
    ("registratie gesloten",        "registration_closed"),
]

_STAD_MAP = {
    "'s-gravenhage":    "den haag",
    "s-gravenhage":     "den haag",
    "sgravenhage":      "den haag",
    "the hague":        "den haag",
    "'s-hertogenbosch": "den bosch",
    "s-hertogenbosch":  "den bosch",
    "shertogenbosch":   "den bosch",
}

# Geo-cache is module-level en gedeeld tussen beide scrapers binnen één run
_geo_cache: dict[str, tuple[float | None, float | None]] = {}
_geo_calls  = 0   # Nominatim requests in deze run (reset bij start job)
_geo_hits   = 0   # cache hits


def _detect_status(card) -> tuple[str, str | None]:
    _CLASS_STATUS = {
        "uitverkocht": "sold_out",
        "verkocht":    "sold_out",
        "verhuurd":    "rented_out",
        "gesloten":    "registration_closed",
        "optie":       "under_option",
    }
    for el in card.find_all(True):
        classes_lower = " ".join(el.get("class", [])).lower()
        for keyword, status in _CLASS_STATUS.items():
            if keyword in classes_lower:
                return status, keyword

    text = card.get_text(" ", strip=True).lower()
    for phrase, status in _STATUS_KEYWORDS:
        if phrase in text:
            return status, phrase

    return "available", None


def _normalize_city(city: str | None) -> str | None:
    if not city:
        return None
    s = city.strip().lower()
    return _STAD_MAP.get(s, s)


def _geocode(city: str) -> tuple[float | None, float | None]:
    global _geo_calls, _geo_hits
    key = city.lower().strip()
    if key in _geo_cache:
        _geo_hits += 1
        return _geo_cache[key]
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{city}, Netherlands", "format": "json", "limit": 1},
            headers={"User-Agent": "huursignal-nieuwbouw/1.0 (sam@huursignal.nl)"},
            timeout=6,
        )
        data = r.json()
        result = (float(data[0]["lat"]), float(data[0]["lon"])) if data else (None, None)
    except Exception as e:
        logger.debug(f"[geocode] Mislukt voor '{city}': {e}")
        result = (None, None)
    _geo_cache[key] = result
    _geo_calls += 1
    time.sleep(_GEO_SLEEP)
    return result


def _get(url: str, label: str) -> tuple[str | None, str]:
    try:
        r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": _UA}, allow_redirects=True)
        if r.status_code == 200 and "Just a moment" not in r.text:
            return r.text, "requests"
        print(f"[nieuwbouw] {label}: HTTP {r.status_code} — FlareSolverr fallback", flush=True)
    except Exception as e:
        print(f"[nieuwbouw] {label}: requests mislukt ({e}) — FlareSolverr fallback", flush=True)

    try:
        html = BaseScraper.flare_get(url)
        print(f"[nieuwbouw] {label}: flaresolverr OK", flush=True)
        return html, "flaresolverr"
    except Exception as e:
        print(f"[nieuwbouw] {label}: beide methodes mislukt: {e}", flush=True)
        return None, "failed"


def _parse_prijs_range(text: str) -> tuple[int | None, int | None]:
    bedragen = re.findall(r"€\s*([\d.]+)", text)
    vals = []
    for b in bedragen:
        try:
            vals.append(int(b.replace(".", "")))
        except ValueError:
            pass
    vals = [v for v in vals if v > 100]
    return (min(vals), max(vals)) if vals else (None, None)


# ─── nieuwbouw-nederland.nl ───────────────────────────────────────────────────

def _parse_nn_card(card, scraped_at: str) -> dict | None:
    try:
        h2 = card.find("h2")
        if not h2:
            return None
        a = h2.find("a", href=True)
        if not a:
            return None
        href = a["href"]
        if not href.startswith("http"):
            href = "https://www.nieuwbouw-nederland.nl" + href
        title = a.get_text(strip=True)
        if not title:
            return None

        plaats_el = card.find("span", class_="plaats")
        raw_city  = plaats_el.get_text(strip=True) if plaats_el else None
        city      = _normalize_city(raw_city)

        segment_el   = card.find("span", class_="segment")
        segment_text = segment_el.get_text(strip=True).lower() if segment_el else ""
        type_ = "koop" if "koop" in segment_text else ("huur" if "huur" in segment_text else None)

        units_match = re.search(r"\((\d+)\)", segment_text)
        units = int(units_match.group(1)) if units_match else None

        prijs_el             = card.find("span", class_="prijs")
        price_min, price_max = _parse_prijs_range(prijs_el.get_text() if prijs_el else "")

        status, status_text = _detect_status(card)

        lat = lon = None
        if city:
            lat, lon = _geocode(city)

        return {
            "title":               title,
            "developer":           None,
            "city":                city,
            "type":                type_,
            "price_min":           price_min,
            "price_max":           price_max,
            "units":               units,
            "expected_date":       None,
            "source":              "nieuwbouw-nederland.nl",
            "latitude":            lat,
            "longitude":           lon,
            "url":                 href,
            "scraped_at":          scraped_at,
            "status":              status,
            "status_text":         status_text,
            "is_active":           True,
            "last_seen_at":        scraped_at,
            "consecutive_missing": 0,
        }
    except Exception:
        logger.debug("[nn] Kaart parse fout", exc_info=True)
        return None


def _scrape_nieuwbouw_nederland() -> list[dict]:
    alle: list[dict]  = []
    seen_urls: set[str] = set()
    empty_streak = 0
    scraped_at   = datetime.now(timezone.utc).isoformat()
    t_start      = time.monotonic()

    print("[nn] Start scrapen nieuwbouw-nederland.nl", flush=True)

    for page_num in range(1, _MAX_PAGES + 1):
        elapsed = time.monotonic() - t_start
        if elapsed > _MAX_RUNTIME_S:
            print(f"[nn] Tijdslimiet bereikt ({elapsed:.0f}s), stoppen na pagina {page_num - 1}", flush=True)
            break

        url = (
            "https://www.nieuwbouw-nederland.nl/projecten/?sort=change_desc"
            if page_num == 1
            else f"https://www.nieuwbouw-nederland.nl/projecten/?sort=change_desc&p={page_num}"
        )

        t_page = time.monotonic()
        print(f"[nn] Pagina {page_num}/{_MAX_PAGES} ophalen… (totaal {len(alle)} tot nu, {elapsed:.0f}s verstreken)", flush=True)
        html, method = _get(url, f"nn p{page_num}")
        if not html:
            print(f"[nn] Pagina {page_num}: geen HTML, stoppen", flush=True)
            break

        soup  = BeautifulSoup(html, "html.parser")
        cards = soup.find_all("article")
        print(f"[nn] Pagina {page_num}: {len(cards)} kaarten via {method} ({time.monotonic() - t_page:.1f}s)", flush=True)

        if not cards:
            print(f"[nn] Geen kaarten op pagina {page_num}, stoppen", flush=True)
            break

        new_this_page = 0
        for card in cards:
            project = _parse_nn_card(card, scraped_at)
            if project and project["url"] not in seen_urls:
                seen_urls.add(project["url"])
                alle.append(project)
                new_this_page += 1

        hidden = sum(1 for p in alle if p.get("status") in _HIDDEN_STATUSES)
        print(f"[nn] Pagina {page_num}: {new_this_page} nieuw — totaal {len(alle)} ({hidden} verborgen status)", flush=True)

        if new_this_page == 0:
            empty_streak += 1
            if empty_streak >= _STOP_IF_NO_NEW:
                print(f"[nn] {_STOP_IF_NO_NEW} pagina's zonder nieuw, stoppen", flush=True)
                break
        else:
            empty_streak = 0

        if page_num < _MAX_PAGES:
            time.sleep(_PAGE_DELAY)

    elapsed = time.monotonic() - t_start
    print(
        f"[nn] KLAAR: {len(alle)} projecten, {page_num} pagina's, "
        f"geocode {_geo_calls} calls / {_geo_hits} cache hits, {elapsed:.0f}s totaal",
        flush=True,
    )
    return alle


# ─── nieuwbouw.nl ─────────────────────────────────────────────────────────────

def _parse_nieuwbouw_nl_card(card, type_: str, scraped_at: str) -> dict | None:
    try:
        project_id = card.get("data-project-id", "")

        a = card.find("a", href=True)
        if a:
            href = a["href"]
            if not href.startswith("http"):
                href = "https://nieuwbouw.nl" + href
        elif project_id:
            href = f"https://nieuwbouw.nl/project/{project_id}/"
        else:
            return None

        title_el = card.find("h3")
        title    = title_el.get_text(strip=True) if title_el else None
        if not title:
            return None

        city = None
        for el in card.find_all(["p", "span", "div"]):
            txt = el.get_text(strip=True)
            if txt and txt != title and len(txt) < 40 and not re.search(r"\d", txt):
                city = _normalize_city(txt)
                break

        card_text = card.get_text(" ", strip=True)

        price_min = price_max = None
        for el in card.find_all(string=re.compile(r"€")):
            pm, px = _parse_prijs_range(str(el))
            if pm:
                price_min = min(pm, price_min) if price_min else pm
            if px:
                price_max = max(px, price_max) if price_max else px

        units_match = re.search(r"(\d+)\s*(?:woningen|appartementen|units)", card_text, re.I)
        units = int(units_match.group(1)) if units_match else None

        date_match    = re.search(r"(?:Q[1-4]|oplevering)\s*:?\s*((?:Q[1-4]\s*)?20\d{2})", card_text, re.I)
        expected_date = date_match.group(1).strip() if date_match else None

        status, status_text = _detect_status(card)

        lat = lon = None
        if city:
            lat, lon = _geocode(city)

        return {
            "title":               title,
            "developer":           None,
            "city":                city,
            "type":                type_,
            "price_min":           price_min,
            "price_max":           price_max,
            "units":               units,
            "expected_date":       expected_date,
            "source":              "nieuwbouw.nl",
            "latitude":            lat,
            "longitude":           lon,
            "url":                 href,
            "scraped_at":          scraped_at,
            "status":              status,
            "status_text":         status_text,
            "is_active":           True,
            "last_seen_at":        scraped_at,
            "consecutive_missing": 0,
        }
    except Exception:
        logger.debug("[nieuwbouw.nl] Kaart parse fout", exc_info=True)
        return None


def _scrape_nieuwbouw_nl() -> list[dict]:
    alle: list[dict]  = []
    seen_urls: set[str] = set()
    scraped_at = datetime.now(timezone.utc).isoformat()
    t_start    = time.monotonic()

    print("[nieuwbouw.nl] Start scrapen nieuwbouw.nl (huur + koop)", flush=True)

    for type_ in ("huur", "koop"):
        empty_streak = 0
        base = f"https://nieuwbouw.nl/aanbod/{type_}/"
        print(f"[nieuwbouw.nl] === Type: {type_} ===", flush=True)

        for page_num in range(1, _MAX_PAGES + 1):
            elapsed = time.monotonic() - t_start
            if elapsed > _MAX_RUNTIME_S:
                print(f"[nieuwbouw.nl] Tijdslimiet bereikt ({elapsed:.0f}s), stoppen", flush=True)
                break

            url = base if page_num == 1 else f"{base}?page={page_num}&orderBy=RELEVANCE&direction=DESC"

            t_page = time.monotonic()
            print(f"[nieuwbouw.nl/{type_}] Pagina {page_num}/{_MAX_PAGES} ophalen… (totaal {len(alle)}, {elapsed:.0f}s)", flush=True)
            html, method = _get(url, f"nieuwbouw.nl/{type_} p{page_num}")
            if not html:
                print(f"[nieuwbouw.nl/{type_}] Pagina {page_num}: geen HTML, stoppen", flush=True)
                break

            soup  = BeautifulSoup(html, "html.parser")
            cards = soup.select('div[data-gtm-track="project-card"]')
            print(f"[nieuwbouw.nl/{type_}] Pagina {page_num}: {len(cards)} kaarten via {method} ({time.monotonic() - t_page:.1f}s)", flush=True)

            if not cards:
                print(f"[nieuwbouw.nl/{type_}] Geen kaarten op pagina {page_num}, stoppen", flush=True)
                break

            new_this_page = 0
            for card in cards:
                project = _parse_nieuwbouw_nl_card(card, type_, scraped_at)
                if project and project["url"] not in seen_urls:
                    seen_urls.add(project["url"])
                    alle.append(project)
                    new_this_page += 1

            print(f"[nieuwbouw.nl/{type_}] Pagina {page_num}: {new_this_page} nieuw — totaal {len(alle)}", flush=True)

            if new_this_page == 0:
                empty_streak += 1
                if empty_streak >= _STOP_IF_NO_NEW:
                    print(f"[nieuwbouw.nl/{type_}] {_STOP_IF_NO_NEW}x geen nieuw, stoppen", flush=True)
                    break
            else:
                empty_streak = 0

            if page_num < _MAX_PAGES:
                time.sleep(_PAGE_DELAY)

    elapsed = time.monotonic() - t_start
    print(
        f"[nieuwbouw.nl] KLAAR: {len(alle)} projecten, "
        f"geocode {_geo_calls} calls / {_geo_hits} cache hits, {elapsed:.0f}s totaal",
        flush=True,
    )
    return alle


# ─── Scraper classes ──────────────────────────────────────────────────────────

class NieuwbouwNederlandScraper(BaseScraper):
    name = "nieuwbouw_nederland"
    category = "nieuwbouw"
    excluded_from_main_loop = True

    def scrape(self, stad, min_prijs, max_prijs, types, radius_km=None):
        return []

    def scrape_projecten(self) -> list[dict]:
        global _geo_calls, _geo_hits
        _geo_calls = _geo_hits = 0
        print(f"[{self.name}] scrape_projecten gestart", flush=True)
        try:
            result = _scrape_nieuwbouw_nederland()
            print(f"[{self.name}] scrape_projecten klaar: {len(result)} projecten", flush=True)
            return result
        except Exception:
            print(f"[{self.name}] scrape_projecten FOUT:", flush=True)
            traceback.print_exc()
            return []


class NieuwbouwNlScraper(BaseScraper):
    name = "nieuwbouw_nl"
    category = "nieuwbouw"
    excluded_from_main_loop = True

    def scrape(self, stad, min_prijs, max_prijs, types, radius_km=None):
        return []

    def scrape_projecten(self) -> list[dict]:
        global _geo_calls, _geo_hits
        _geo_calls = _geo_hits = 0
        print(f"[{self.name}] scrape_projecten gestart", flush=True)
        try:
            result = _scrape_nieuwbouw_nl()
            print(f"[{self.name}] scrape_projecten klaar: {len(result)} projecten", flush=True)
            return result
        except Exception:
            print(f"[{self.name}] scrape_projecten FOUT:", flush=True)
            traceback.print_exc()
            return []
