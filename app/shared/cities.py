"""
Canonical city slugs for listings.stad (single source of truth at write + query).

All DB writes and SQL filters use canonical_city() / stad_slugs_uit_pref().
Legacy spellings (PDOK/CBS) → _CITY_ALIASES; backfill migration 012.
Geen stad-normalisatie buiten dit bestand (scrapers: canonical_city; nieuwbouw: stad_nieuwbouw_city).
"""
import re

# Normalized slug (after strip/lower/replace) → canonical listings.stad
_CITY_ALIASES: dict[str, str] = {
    "amsterdam": "amsterdam",
    "den-haag": "den-haag",
    "s-gravenhage": "den-haag",
    "gravenhage": "den-haag",
    "rotterdam": "rotterdam",
    "utrecht": "utrecht",
    "eindhoven": "eindhoven",
    "groningen": "groningen",
    "tilburg": "tilburg",
    "almere": "almere",
    "breda": "breda",
    "nijmegen": "nijmegen",
    "haarlem": "haarlem",
    "arnhem": "arnhem",
    "enschede": "enschede",
    "amersfoort": "amersfoort",
    "apeldoorn": "apeldoorn",
    "leiden": "leiden",
    "delft": "delft",
    "zoetermeer": "zoetermeer",
    "zwolle": "zwolle",
    "maastricht": "maastricht",
    "den-bosch": "den-bosch",
    "s-hertogenbosch": "den-bosch",
}

# nieuwbouw_projects.city — vrije tekst (spaties), niet listings.stad
_NIEUWBOUW_CITY_LABEL: dict[str, str] = {
    "den-haag": "den haag",
    "den-bosch": "den bosch",
}


def canonical_city(name: str | None) -> str:
    """
    Canonical listings.stad: lowercase, stripped, hyphenated slug + alias map.
    'Den Haag' / "'s-Gravenhage" / 'den haag' → 'den-haag'.
    """
    if not name:
        return ""
    s = name.strip().lower().replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not s:
        return ""
    return _CITY_ALIASES.get(s, s)


def normalize_city_name(name: str) -> str:
    """Alias voor canonical_city (scrapers / scrape_plan)."""
    return canonical_city(name)


def stad_voor_db(stad: str | None) -> str | None:
    """Waarde voor listings.stad bij insert/upsert."""
    c = canonical_city(stad)
    return c or None


def stad_slugs_uit_pref(stad_raw: str) -> list[str]:
    """Canonical slugs uit komma-gescheiden user_preferences.stad (voor SQL .in_)."""
    out: list[str] = []
    seen: set[str] = set()
    for s in (stad_raw or "").split(","):
        slug = canonical_city(s.strip())
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def stad_pref_opslaan(stad_raw: str) -> str:
    """Canonical komma-string voor user_preferences.stad bij opslaan."""
    return ",".join(stad_slugs_uit_pref(stad_raw))


def stad_nieuwbouw_city(name: str | None) -> str | None:
    """Waarde/zoekterm voor nieuwbouw_projects.city (geen listings.stad)."""
    slug = canonical_city(name)
    if not slug:
        return None
    return _NIEUWBOUW_CITY_LABEL.get(slug, slug.replace("-", " "))


def stad_ilike_zoekterm(name: str | None) -> str:
    """ILIKE-zoekterm voor nieuwbouw_projects.city; gebruik met stad_slugs_uit_pref()."""
    return stad_nieuwbouw_city(name) or ""
