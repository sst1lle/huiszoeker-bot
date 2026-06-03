import re
import json
import logging
from datetime import datetime
from bs4 import BeautifulSoup

from shared.cities import canonical_city
from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.funda.nl"

_SLUG_PREFIXES = {
    "appartement", "huis", "studio", "kamer", "woning", "parkeergelegenheid",
    "garage", "praktijkruimte", "kantoorruimte", "winkelruimte", "bedrijfsruimte",
    "eengezinswoning", "tussenwoning", "hoekwoning", "vrijstaande", "object",
    "bovenwoning", "benedenwoning", "maisonnette", "penthouse", "galerijflat",
    "portiekflat", "portiekwoning", "recreatiewoning",
}


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


def _adres_uit_slug(rel_url: str) -> str | None:
    """
    /detail/huur/den-haag/appartement-randveen-78/43291827/ → "Randveen 78"
    /detail/huur/utrecht/parkeergelegenheid-karel-doormanlaan-22-a/43292883/ → "Karel Doormanlaan 22 a"
    """
    try:
        parts = rel_url.strip("/").split("/")
        if len(parts) < 5:
            return None
        slug = parts[-2]  # bv. "appartement-randveen-78"
        segs = slug.split("-")
        while segs and segs[0].lower() in _SLUG_PREFIXES:
            segs.pop(0)
        if not segs:
            return None
        return " ".join(s.title() if not re.match(r"^\d", s) else s for s in segs)
    except Exception:
        return None


class FundaScraper(BaseScraper):
    """
    Scraper voor Funda huurwoningen via Byparr + Nuxt 3 __NUXT_DATA__ parse.

    Funda migreerde van Next.js naar Nuxt.js. Listing-data zit in
    <script id="__NUXT_DATA__"> als een gecomprimeerde pointer-array:
    - Waarden in dicts zijn integer-pointers naar de flat array
    - [N] (lijst met één int) = pointer → nuxt_data[N]
    - ["Ref"/"Reactive"/etc., N] = type-tag → nuxt_data[N]
    - Primitieven (str/int/bool/None) = directe waarden

    robots.txt: funda.nl staat crawlen van /huur/ pagina's toe.
    uses_types = False: Funda heeft geen aparte URL per woningtype.
    """

    name = "funda"
    robots_txt_compliant = True
    request_delay_seconds = 5.0
    uses_types = False
    uses_price_filter = False
    flaresolverr_only = True

    FUNDA_TYPE_MAP = {
        "apartment": "appartement",
        "house":     "woning",
        "room":      "kamer",
        "studio":    "studio",
        "parking":   "parkeerplaats",
    }

    def _scrape_impl(
        self,
        stad: str,
        min_prijs: int,
        max_prijs: int,
        types: list[str],
    ) -> list[dict]:
        stad_slug = canonical_city(stad)
        base = (
            f"{BASE_URL}/zoeken/huur"
            f"?selected_area=%5B%22{stad_slug}%22%5D"
            f"&sort=%22date_down%22"  # nieuwste eerst
        )

        # Funda pagineert via &search_result=N
        def page_url(page: int) -> str:
            return base if page == 1 else f"{base}&search_result={page}"

        return self._scrape_paginated(page_url, lambda html: self._parse_nuxtdata(html, stad))

    def _parse_nuxtdata(self, html: str, stad: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", {"id": "__NUXT_DATA__"})
        if not script or not script.string:
            return []

        try:
            arr = json.loads(script.string)
        except Exception:
            return []

        _TAGS = {"Ref", "Reactive", "ShallowReactive", "ShallowRef"}

        def _deref(v):
            """Eén dereference: pointer (int of type-tag) → waarde in array."""
            if isinstance(v, int):
                return arr[v] if 0 <= v < len(arr) else None
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                if v[0] in _TAGS:
                    return _deref(v[1])
                if v[0] == "EmptyRef":
                    return None
            return v

        def _resolve(val, depth=0):
            """
            Resolve totdat een primitieve waarde bereikt is.
            [N] (single-int list) → nuxt_data[N] → recurse
            Type-tags → volg de referentie → recurse
            Primitieven → return as-is
            """
            if depth > 10 or val is None:
                return val
            if isinstance(val, list) and len(val) == 1 and isinstance(val[0], int):
                return _resolve(_deref(val[0]), depth + 1)
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str):
                if val[0] in _TAGS:
                    return _resolve(_deref(val[1]), depth + 1)
                if val[0] == "EmptyRef":
                    return None
            return val

        # Zoek de search state: het dict met "listings" + "totalListingsCount"
        search_state = None
        for item in arr:
            if isinstance(item, dict) and "listings" in item and "totalListingsCount" in item:
                search_state = item
                break

        if not search_state:
            return []

        # search_state["listings"] → int → ["Ref", N] → lijst van listing-pointers
        listings_list = _resolve(_deref(search_state["listings"]))
        if not isinstance(listings_list, list) or not listings_list:
            return []

        scraped_at = datetime.utcnow().isoformat()
        resultaten = []
        parking_count = 0

        for listing_ref in listings_list:
            try:
                raw = _deref(listing_ref)
                if not isinstance(raw, dict):
                    continue

                # URL: alleen /huur/ (niet /koophuur/)
                rel_url = _deref(raw.get("object_detail_page_relative_url"))
                if not isinstance(rel_url, str) or "/huur/" not in rel_url:
                    continue

                # Filter parkeerplaatsen
                obj_type_raw = _deref(raw.get("object_type"))
                if obj_type_raw == "parking" or "parkeergelegenheid" in rel_url:
                    parking_count += 1
                    continue

                url = BASE_URL + rel_url

                # External ID: laatste pad-segment vóór trailing slash
                external_id = rel_url.strip("/").split("/")[-1]

                # Adres uit URL-slug; fallback naar address.wijk
                adres = _adres_uit_slug(rel_url)
                if not adres:
                    addr_raw = _deref(raw.get("address"))
                    if isinstance(addr_raw, dict):
                        adres = (_deref(addr_raw.get("wijk"))
                                 or _deref(addr_raw.get("city")))

                # Object type: vertaal Engels → Nederlands voor matching in main.py
                type_woning = self.FUNDA_TYPE_MAP.get(obj_type_raw) if isinstance(obj_type_raw, str) else None

                # Prijs: raw["price"] → price_dict → ["rent_price"] → [N] → int
                prijs = None
                price_dict = _deref(raw.get("price"))
                if isinstance(price_dict, dict):
                    prijs = _parse_prijs(_resolve(_deref(price_dict.get("rent_price"))))

                # Oppervlakte: raw["floor_area"] → [N] → int
                oppervlakte = _parse_opp(_resolve(_deref(raw.get("floor_area"))))

                # Foto: photo_image_id[0] → resolve → string
                foto_url = None
                photo_list = _deref(raw.get("photo_image_id"))
                if isinstance(photo_list, list) and photo_list:
                    foto_id = _resolve(_deref(photo_list[0]))
                    if isinstance(foto_id, str) and foto_id.startswith("http"):
                        foto_url = foto_id

                resultaten.append({
                    "source":         "funda",
                    "url":            url,
                    "external_id":    external_id,
                    "adres":          adres,
                    "stad":           stad,
                    "prijs":          prijs,
                    "oppervlakte":    oppervlakte,
                    "type_woning":    type_woning,
                    "foto_url":       foto_url,
                    "beschikbaar":    True,
                    "scraped_at":     scraped_at,
                    "omschrijving":   None,
                    "rating":         None,
                    "rating_details": None,
                })
            except Exception:
                continue

        if parking_count:
            logger.debug(f"[{self.name}] {parking_count} parkeergelegenheid gefilterd voor {stad}")
        logger.debug(f"[{self.name}] __NUXT_DATA__: {len(resultaten)} woningen voor {stad}")
        return resultaten


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.WARNING)
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
