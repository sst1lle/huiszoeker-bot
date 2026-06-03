"""
Gedeelde stadsnaam-normalisatie (slug) voor DB-opslag en SQL-filters.
PDOK levert bv. 'Utrecht' of "'s-Gravenhage"; scraper-URLs gebruiken 'utrecht' / 'den-haag'.
"""
import re

_CITY_ALIASES = {
    "s-gravenhage": "den-haag",
}


def normalize_city_name(name: str) -> str:
    """
    Normaliseer een stadsnaam naar een vergelijkbare slug.
    'Den Haag' / 'den-haag' / "'s-Gravenhage" → 'den-haag'.
    """
    if not name:
        return ""
    s = name.strip().lower().replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return _CITY_ALIASES.get(s, s)


def stad_voor_db(stad: str | None) -> str | None:
    """Waarde voor listings.stad: genormaliseerde slug of None."""
    if not stad:
        return None
    slug = normalize_city_name(stad)
    return slug or stad.strip().lower()


def stad_slugs_uit_pref(stad_raw: str) -> list[str]:
    """Genormaliseerde slugs uit een komma-gescheiden stad-voorkeur."""
    out = []
    seen = set()
    for s in (stad_raw or "").split(","):
        slug = normalize_city_name(s.strip())
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out
