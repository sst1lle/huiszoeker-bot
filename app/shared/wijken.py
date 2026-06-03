"""
Beschikbare wijken per stad via de CBS Wijkenkaart (PDOK WFS), met cache in Supabase.

Een stad-slug uit user_preferences (bv. 'den-haag') wordt eerst naar de officiële
CBS-gemeentenaam vertaald via de PDOK Locatieserver ('den-haag' -> "'s-Gravenhage"),
daarna worden de wijken opgehaald uit de WFS-laag wijkenbuurten:wijken.

De wijknamen zijn exact dezelfde als die shared.geocoder per listing teruggeeft
(bv. 'Wijk 07 Scheveningen'), zodat de wijk-filter consistent matcht.

Let op: PDOK's WFS negeert CQL_FILTER — we gebruiken daarom de OGC-standaard FILTER (XML).
"""
import logging
import requests

from db import get_db

logger = logging.getLogger(__name__)

_LOCATIESERVER = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
_WFS = "https://service.pdok.nl/cbs/wijkenbuurten/2023/wfs/v1_0"
_TIMEOUT = 20
_UA = "huiszoeker-wijken/1.0"
# CBS-pseudowijken die geen zinvolle keuze zijn
_NEGEER = {"Groot water", "Buitenland", "", None}


def _gemeentenaam(stad_slug: str) -> str | None:
    """Vertaal stad-slug naar officiële CBS-gemeentenaam via PDOK Locatieserver."""
    q = stad_slug.replace("-", " ").strip()
    if not q:
        return None
    r = requests.get(
        _LOCATIESERVER,
        params={"q": q, "fq": "type:gemeente", "rows": 1},
        timeout=_TIMEOUT, headers={"User-Agent": _UA},
    )
    r.raise_for_status()
    docs = (r.json().get("response") or {}).get("docs") or []
    return docs[0].get("gemeentenaam") if docs else None


def gemeentenaam_voor_stad(stad_slug: str) -> str | None:
    """
    Officiële CBS-gemeentenaam voor een stad-slug (bv. 'den-haag' -> "'s-Gravenhage").
    Gebruikt de gecachete waarde uit wijken_cache indien aanwezig, anders PDOK Locatieserver.
    Bij een fout → None (geocoding valt dan terug op zoeken zonder gemeente-constraint).
    """
    stad_slug = (stad_slug or "").strip().lower()
    if not stad_slug:
        return None
    try:
        rows = get_db().table("wijken_cache").select("gemeentenaam").eq("stad", stad_slug).limit(1).execute().data
        if rows and rows[0].get("gemeentenaam"):
            return rows[0]["gemeentenaam"]
    except Exception:
        pass
    try:
        return _gemeentenaam(stad_slug)
    except Exception as e:
        logger.warning(f"[wijken] gemeentenaam-resolutie mislukt voor '{stad_slug}': {e}")
        return None


def stad_db_variants(stad_str: str) -> list[str]:
    """
    Exacte stad-waarden om in de DB op te matchen voor een (komma-gescheiden) stad-voorkeur:
    de slug zelf (oude records) + de officiële CBS-gemeentenaam (PDOK-waarheid op verse records).
    Bv. 'den-haag' → ['den-haag', "'s-Gravenhage"]. Voor DB-side filtering met .in_("stad", …).
    """
    out = set()
    for s in (stad_str or "").split(","):
        s = s.strip()
        if not s:
            continue
        out.add(s)
        gem = gemeentenaam_voor_stad(s)
        if gem:
            out.add(gem)
    return list(out)


def _wfs_wijken(gemeentenaam: str) -> list[str]:
    """Haal wijknamen voor een gemeente op via de CBS WFS (OGC FILTER — geen CQL)."""
    flt = (
        '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0">'
        "<fes:PropertyIsEqualTo>"
        "<fes:ValueReference>gemeentenaam</fes:ValueReference>"
        f"<fes:Literal>{gemeentenaam}</fes:Literal>"
        "</fes:PropertyIsEqualTo></fes:Filter>"
    )
    r = requests.get(
        _WFS,
        params={
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": "wijkenbuurten:wijken", "outputFormat": "application/json",
            "count": "1000", "propertyName": "wijknaam", "FILTER": flt,
        },
        timeout=_TIMEOUT, headers={"User-Agent": _UA},
    )
    r.raise_for_status()
    namen = {f.get("properties", {}).get("wijknaam") for f in r.json().get("features", [])}
    return sorted(n for n in namen if n not in _NEGEER)


def wijken_voor_stad(stad_slug: str) -> list[str]:
    """
    Beschikbare CBS-wijken voor een stad-slug, met cache in wijken_cache.
    Bij een API-/DB-fout → lege lijst (UI toont 'geen wijken', filter blijft leeg = alle wijken).
    """
    stad_slug = (stad_slug or "").strip().lower()
    if not stad_slug:
        return []

    db = get_db()

    # 1. cache
    try:
        rows = db.table("wijken_cache").select("wijken").eq("stad", stad_slug).limit(1).execute().data
        if rows:
            return rows[0].get("wijken") or []
    except Exception as e:
        logger.warning(f"[wijken] cache-lees mislukt ({e}); zonder cache verder")

    # 2. resolve gemeentenaam + WFS
    try:
        gem = _gemeentenaam(stad_slug)
        if not gem:
            logger.warning(f"[wijken] geen gemeentenaam gevonden voor '{stad_slug}'")
            return []
        wijken = _wfs_wijken(gem)
    except Exception as e:
        logger.warning(f"[wijken] ophalen mislukt voor '{stad_slug}': {e}")
        return []

    # 3. cache wegschrijven (faalt stil als tabel ontbreekt)
    try:
        db.table("wijken_cache").upsert(
            {"stad": stad_slug, "gemeentenaam": gem, "wijken": wijken}, on_conflict="stad"
        ).execute()
    except Exception as e:
        logger.warning(f"[wijken] cache-schrijf mislukt ({e})")

    return wijken
