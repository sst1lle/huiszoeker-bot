"""
Scrape-orchestratie: exact één run per (scraper, stad) per interval.

Steden komen uit alle user_preferences; prijs-range en types zijn de union
over alle gebruikers die die stad zoeken. Geen per-user scrape-combinaties.
"""
from shared.cities import normalize_city_name

_DEFAULT_MIN_PRIJS = 0
_DEFAULT_MAX_PRIJS = 9999
_KAMERNET_DEFAULT_TYPES = ["appartement", "studio", "anti-kraak"]


def _aggregate_prefs_per_stad(prefs: list) -> dict[str, dict]:
    """
    Per genormaliseerde stad-slug: min/max prijs (union) en verzamelde woningtypes.
    """
    agg: dict[str, dict] = {}
    for pref in prefs:
        min_p = pref.get("min_prijs")
        if min_p is None:
            min_p = _DEFAULT_MIN_PRIJS
        max_p = pref.get("max_prijs")
        if max_p is None:
            max_p = _DEFAULT_MAX_PRIJS
        types = pref.get("type_woning") or []

        for raw in (pref.get("stad") or "").split(","):
            raw = raw.strip()
            if not raw:
                continue
            slug = normalize_city_name(raw) or raw.lower().replace(" ", "-")
            if slug not in agg:
                agg[slug] = {"min_prijs": min_p, "max_prijs": max_p, "types": set()}
            else:
                rec = agg[slug]
                rec["min_prijs"] = min(rec["min_prijs"], min_p)
                rec["max_prijs"] = max(rec["max_prijs"], max_p)
            rec = agg[slug]
            for t in types:
                if t:
                    rec["types"].add(t)
    return agg


def bouw_scrape_taken(scrapers: list, prefs: list) -> list[dict]:
    """
    Lijst van scrape-taken: één dict per (scraper, stad).

    Keys: scraper, stad (slug), min_prijs, max_prijs, types (list; leeg als uses_types=False).
    """
    agg = _aggregate_prefs_per_stad(prefs)
    if not agg:
        return []

    tasks: list[dict] = []
    for scraper in scrapers:
        if getattr(scraper, "excluded_from_main_loop", False):
            continue
        if getattr(scraper, "category", "huurwoningen") != "huurwoningen":
            continue
        for slug, rec in agg.items():
            if scraper.uses_types:
                types = sorted(rec["types"]) if rec["types"] else list(_KAMERNET_DEFAULT_TYPES)
            else:
                types = []
            tasks.append({
                "scraper": scraper,
                "stad": slug,
                "min_prijs": rec["min_prijs"],
                "max_prijs": rec["max_prijs"],
                "types": types,
            })
    return tasks


def taken_per_scraper(tasks: list[dict]) -> dict[str, list[dict]]:
    """Groepeer taken op scraper.name voor de scheduler-gateway (één lock per scraper)."""
    out: dict[str, list[dict]] = {}
    for t in tasks:
        out.setdefault(t["scraper"].name, []).append(t)
    return out
