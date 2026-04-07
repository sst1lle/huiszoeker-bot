import re
import json
import logging
from datetime import datetime
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.funda.nl"
FLARESOLVERR_URL = "http://flaresolverr:8191/v1"


def _parse_prijs(val) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val) if val > 0 else None
    s = str(val).replace(".", "").replace(",", "").replace("€", "")
    s = s.replace("/mnd", "").replace("/maand", "").replace("per maand", "")
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def _parse_opp(val) -> int | None:
    if val is None:
        return None
    m = re.search(r"(\d+)", str(val))
    return int(m.group(1)) if m else None


def _extract_external_id(url: str) -> str | None:
    # Funda URLs: /huur/den-haag/huis-12345678-straatnaam/
    m = re.search(r"-(\d{7,9})-", url)
    return m.group(1) if m else None


class FundaScraper(BaseScraper):
    """
    Scraper voor Funda huurwoningen.

    Strategie (in volgorde):
      1. funda-scraper package (pip install funda-scraper) — meest betrouwbaar
      2. FlareSolverr + __NEXT_DATA__ JSON parse — als package faalt/geblokkeerd
      3. FlareSolverr + BeautifulSoup HTML parse — last resort

    robots.txt: funda.nl staat crawlen van /huur/ pagina's toe.
    Disallowed zijn o.a. /mijn-funda/, /api/, /account/ en admin-paden.
    Huuroverzichtspagina's vallen buiten de Disallow-regels.

    uses_types = False: Funda heeft geen aparte URL per woningtype voor huur;
    het type-filter werkt via query parameters die intern worden afgehandeld.
    """

    name = "funda"
    robots_txt_compliant = True
    request_delay_seconds = 5.0
    uses_types = False

    def scrape(
        self,
        stad: str,
        min_prijs: int,
        max_prijs: int,
        types: list[str],
        radius_km: int | None = None,
    ) -> list[dict]:
        return self._via_flaresolverr(stad, min_prijs, max_prijs)

    # ── FlareSolverr ─────────────────────────────────────────────────────────

    def _via_flaresolverr(self, stad: str, min_prijs: int, max_prijs: int) -> list[dict]:
        url = f"{BASE_URL}/zoeken/huur?selected_area=%5B%22{stad.lower().replace(' ', '-')}%22%5D&price=%22-{max_prijs}%22"

        logger.warning(f"[{self.name}] FlareSolverr: {url}")
        try:
            r = requests.post(FLARESOLVERR_URL, json={
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000,
            }, timeout=70)
            data = r.json()
            if data.get("status") != "ok":
                logger.error(f"[{self.name}] FlareSolverr fout: {data.get('message')}")
                return []
            html = data["solution"]["response"]
        except Exception as e:
            logger.error(f"[{self.name}] FlareSolverr verbindingsfout: {e}")
            return []

        # ── DEBUG ─────────────────────────────────────────────────────────────
        soup = BeautifulSoup(html, "html.parser")
        nuxt_script = soup.find("script", {"id": "__NUXT_DATA__"})
        if not nuxt_script or not nuxt_script.string:
            print("[funda debug] __NUXT_DATA__ script niet gevonden", flush=True)
        else:
            raw = nuxt_script.string
            print(f"[funda debug] __NUXT_DATA__ lengte: {len(raw)}", flush=True)
            print(f"[funda debug] eerste 3000 chars:\n{raw[:3000]}", flush=True)

            # Zoek naar listing-gerelateerde veldnamen in de ruwe JSON string
            for term in ("fetchListings", "listingId", "GlobalId", "huurprijs", "rentPrice",
                         "objectType", "streetName", "postalCode", "per maand", "address"):
                count = raw.count(term)
                if count:
                    idx = raw.index(term)
                    snippet = raw[max(0, idx-30):idx+80]
                    print(f"[funda debug] '{term}' ({count}x): ...{snippet}...", flush=True)

            # Probeer te parsen en zoek fetchListings in de array
            try:
                arr = json.loads(raw)
                print(f"[funda debug] array lengte: {len(arr)}", flush=True)
                # fetchListings staat op index 3 als {"fetchListings": 4, ...}
                # Zoek het object met fetchListings als key
                for i, item in enumerate(arr):
                    if isinstance(item, dict) and "fetchListings" in item:
                        fl_idx = item["fetchListings"]
                        fl_val = arr[fl_idx] if isinstance(fl_idx, int) and fl_idx < len(arr) else fl_idx
                        print(f"[funda debug] arr[{i}] heeft fetchListings → index {fl_idx} → type: {type(fl_val).__name__}", flush=True)
                        if isinstance(fl_val, (dict, list)):
                            print(f"[funda debug] fetchListings value (500 chars): {str(fl_val)[:500]}", flush=True)
                        # Zoek ook dieper: resolve één niveau
                        if isinstance(fl_val, dict):
                            for k, v in list(fl_val.items())[:10]:
                                resolved = arr[v] if isinstance(v, int) and v < len(arr) else v
                                print(f"[funda debug]   [{k}] → {str(resolved)[:120]}", flush=True)
            except Exception as ex:
                print(f"[funda debug] JSON parse fout: {ex}", flush=True)

        # Zoek naar Funda API-endpoints in de HTML (voor directe API-aanroep)
        api_urls = re.findall(r'https?://[a-z.]*funda[a-z.]*(?:api|search|listing)[^"\'\\s]{0,80}', html)
        print(f"[funda debug] API URL kandidaten: {list(set(api_urls))[:5]}", flush=True)
        # ── /DEBUG ────────────────────────────────────────────────────────────

        # Probeer __NEXT_DATA__ eerst; val terug op HTML-parse
        resultaten = self._parse_nextdata(html, stad)
        if not resultaten:
            resultaten = self._parse_html(html, stad)
        return resultaten

    def _parse_nextdata(self, html: str, stad: str) -> list[dict]:
        """
        Funda gebruikt Next.js — listing-data zit in <script id="__NEXT_DATA__">.
        Zoek recursief naar een lijst van objecten met 'GlobalId' (Funda's listing-ID).
        Dit pad is fragiel en kan breken bij Funda-deploys.
        """
        try:
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not m:
                return []
            nextdata = json.loads(m.group(1))
            hits = self._find_hits(nextdata)
            if not hits:
                return []

            scraped_at = datetime.utcnow().isoformat()
            resultaten = []
            for hit in hits:
                url = hit.get("Url") or hit.get("url", "")
                if not url.startswith("http"):
                    url = BASE_URL + url
                prijs_raw = hit.get("PriceRent") or hit.get("Price") or hit.get("priceRent")
                resultaten.append({
                    "source":         "funda",
                    "url":            url,
                    "external_id":    str(hit.get("GlobalId") or _extract_external_id(url) or ""),
                    "adres":          hit.get("Address") or hit.get("address"),
                    "stad":           stad,
                    "prijs":          _parse_prijs(prijs_raw),
                    "oppervlakte":    _parse_opp(hit.get("FloorArea") or hit.get("floorArea")),
                    "type_woning":    None,
                    "foto_url":       hit.get("MainImageUrl") or hit.get("mainImageUrl"),
                    "beschikbaar":    True,
                    "scraped_at":     scraped_at,
                    "omschrijving":   None,
                    "rating":         None,
                    "rating_details": None,
                })
            logger.warning(f"[{self.name}] __NEXT_DATA__: {len(resultaten)} woningen voor {stad}")
            return resultaten
        except Exception as e:
            logger.warning(f"[{self.name}] __NEXT_DATA__ parse mislukt: {e}")
            return []

    def _find_hits(self, obj, depth: int = 0) -> list:
        """Zoek recursief in __NEXT_DATA__ naar een lijst van listing-objecten (herkenbaar aan 'GlobalId')."""
        if depth > 8:
            return []
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "GlobalId" in obj[0]:
            return obj
        if isinstance(obj, dict):
            for v in obj.values():
                result = self._find_hits(v, depth + 1)
                if result:
                    return result
        return []

    def _parse_html(self, html: str, stad: str) -> list[dict]:
        """
        Last-resort BeautifulSoup parse.
        Funda rendert listing-cards server-side met data-object-url-tracking attributen.
        CSS-klassen kunnen veranderen bij frontend-deploys.
        """
        soup = BeautifulSoup(html, "html.parser")
        resultaten = []
        scraped_at = datetime.utcnow().isoformat()

        for card in soup.select('[data-object-url-tracking="resultlist"]'):
            a = card.select_one("a[href*='/huur/']")
            if not a:
                continue
            url = a.get("href", "")
            if not url.startswith("http"):
                url = BASE_URL + url

            adres_el = card.select_one("[class*='street-name']") or card.select_one("h2")
            prijs_el  = card.select_one("[class*='price']")

            resultaten.append({
                "source":         "funda",
                "url":            url,
                "external_id":    _extract_external_id(url),
                "adres":          adres_el.get_text(strip=True) if adres_el else None,
                "stad":           stad,
                "prijs":          _parse_prijs(prijs_el.get_text()) if prijs_el else None,
                "oppervlakte":    None,
                "type_woning":    None,
                "foto_url":       None,
                "beschikbaar":    True,
                "scraped_at":     scraped_at,
                "omschrijving":   None,
                "rating":         None,
                "rating_details": None,
            })

        logger.warning(f"[{self.name}] HTML fallback: {len(resultaten)} woningen voor {stad}")
        return resultaten


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    stad = sys.argv[1] if len(sys.argv) > 1 else "den-haag"
    min_p = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    max_p = int(sys.argv[3]) if len(sys.argv) > 3 else 1500

    scraper = FundaScraper()
    resultaten = scraper.scrape(stad=stad, min_prijs=min_p, max_prijs=max_p, types=[])
    print(f"\n{len(resultaten)} woningen gevonden:\n")
    for w in resultaten[:5]:
        print(f"  {w['adres']} — €{w['prijs']} — {w['url']}")
    if len(resultaten) > 5:
        print(f"  ... en {len(resultaten) - 5} meer")
