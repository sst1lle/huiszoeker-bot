"""
PDOK-geocoding voor Nederlandse adressen, met caching in Supabase (tabel geocode_cache).

Gebruikt de PDOK Locatieserver (gratis, geen API-key nodig):
  https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?q=<adres>&fq=type:adres

Publieke API:
    from shared.geocoder import geocode
    result = await geocode("Zeesluisweg 50A, Den Haag")
    # -> {"straat": "Zeesluisweg", "huisnummer": "50A", "postcode": "2583DR",
    #     "wijk": "...", "buurt": "...", "stad": "'s-Gravenhage",
    #     "lat": 52.10..., "lng": 4.26...}
    # of None als PDOK niets vindt.

Caching (twee-traps):
- Eerste lookup gebeurt op het GENORMALISEERDE adres (lowercase, leestekens weg,
  spaties samengevouwen) → kleine schrijfvarianten van hetzelfde adres delen één key:
    "Zeesluisweg 50A Den Haag" / "zeesluisweg 50a den haag" / "Zeesluisweg 50A, Den Haag"
  worden allemaal "zeesluisweg 50a den haag".
- Zodra PDOK postcode + huisnummer teruggeeft, wordt DÁT de canonieke cache_key
  ("<postcode> <huisnummer>"); het genormaliseerde adres wordt als alias-entry
  weggeschreven zodat exact dat input-adres de volgende keer direct een hit geeft.
- Ook misses worden gecachet (found=False) zodat onvindbare adressen niet telkens
  opnieuw bij PDOK worden opgevraagd.

Graceful: elke fout (PDOK onbereikbaar, DB onbereikbaar, geen match) leidt tot een
nette terugval (None of cache overslaan), nooit een exception naar de aanroeper.
"""
import re
import asyncio
import logging

import httpx

from db import get_db

logger = logging.getLogger(__name__)

PDOK_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
_HTTP_TIMEOUT = 10.0
_USER_AGENT = "huiszoeker-geocoder/1.0"

# Velden die geocode() teruggeeft (en de bijbehorende kolommen in geocode_cache)
_RESULT_FIELDS = ("straat", "huisnummer", "postcode", "wijk", "buurt", "stad", "lat", "lng")

_POSTCODE_RE = re.compile(r"\b(\d{4})\s*([A-Za-z]{2})\b")
_HUISNR_RE = re.compile(r"\b(\d{1,5})\s*([A-Za-z]?)\b")
_POINT_RE = re.compile(r"POINT\(\s*([\d.]+)\s+([\d.]+)\s*\)")


def _norm_adres(adres: str) -> str:
    """Genormaliseerd adres als lookup-key: lowercase, leestekens → spatie, spaties samengevouwen."""
    return " ".join(re.sub(r"[^\w\s]", " ", adres.lower()).split())


def _pc_hnr_key(postcode: str | None, huisnummer: str | None) -> str | None:
    """Canonieke key '<postcode> <huisnummer>' (lowercase, postcode zonder spaties), of None."""
    if not postcode or not huisnummer:
        return None
    return f"{postcode.replace(' ', '')} {huisnummer}".lower().strip()


def _pc_hnr_key_from_input(adres: str) -> str | None:
    """Probeer postcode + huisnummer uit het ruwe input-adres te halen (voor de eerste lookup)."""
    pc = _POSTCODE_RE.search(adres)
    if not pc:
        return None
    hnr = _HUISNR_RE.search(adres.replace(pc.group(0), " "))  # postcode-cijfers eerst wegnemen
    if not hnr:
        return None
    huisnummer = f"{hnr.group(1)}{hnr.group(2)}"
    return _pc_hnr_key(f"{pc.group(1)}{pc.group(2)}", huisnummer)


def _parse_doc(doc: dict) -> dict:
    """Map een PDOK-doc naar het geocode()-resultaatschema."""
    lat = lng = None
    m = _POINT_RE.search(doc.get("centroide_ll") or "")
    if m:
        lng, lat = float(m.group(1)), float(m.group(2))

    huisnummer = doc.get("huis_nlt")
    if not huisnummer and doc.get("huisnummer") is not None:
        huisnummer = str(doc["huisnummer"])

    return {
        "straat": doc.get("straatnaam"),
        "huisnummer": huisnummer,
        "postcode": doc.get("postcode"),
        "wijk": doc.get("wijknaam"),
        "buurt": doc.get("buurtnaam"),
        "stad": doc.get("woonplaatsnaam"),
        "lat": lat,
        "lng": lng,
    }


async def _pdok_lookup(adres: str) -> dict | None:
    """
    Bevraag PDOK; geeft het resultaatschema (incl. de ECHTE stad) terug of None.
    Bewust GEEN gemeente-constraint: scrapers geven ook listings uit omliggende steden
    terug, en die moeten hun werkelijke stad/wijk krijgen (zie stad-validatie in main.py).
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
        r = await client.get(PDOK_URL, params={"q": adres, "rows": 1, "fq": "type:adres"})
        r.raise_for_status()
        docs = (r.json().get("response") or {}).get("docs") or []
    return _parse_doc(docs[0]) if docs else None


async def _cache_get(key: str) -> dict | None:
    """
    Cache-hit → {"result": <dict|None>}. Cache-miss of DB-fout → None.
    (De wrapper-dict onderscheidt een negatieve cache-hit van 'niet in cache'.)
    """
    def _q():
        return (
            get_db().table("geocode_cache").select("*")
            .eq("cache_key", key).limit(1).execute().data
        )
    try:
        rows = await asyncio.to_thread(_q)
    except Exception as e:
        logger.warning(f"[geocode] cache-lees mislukt ({e}); zonder cache verder")
        return None
    if not rows:
        return None
    row = rows[0]
    if not row.get("found"):
        return {"result": None}
    return {"result": {f: row.get(f) for f in _RESULT_FIELDS}}


async def _cache_put(key: str, adres: str, result: dict | None) -> None:
    """Sla resultaat (of miss) op onder cache_key. Faalt stil bij DB-fouten."""
    row = {"cache_key": key, "query": adres.strip(), "found": result is not None}
    if result:
        row.update(result)
    def _w():
        get_db().table("geocode_cache").upsert(row, on_conflict="cache_key").execute()
    try:
        await asyncio.to_thread(_w)
    except Exception as e:
        logger.warning(f"[geocode] cache-schrijf mislukt ({e}); resultaat niet gecachet")


async def geocode(adres: str) -> dict | None:
    """
    Geocode een Nederlands adres via PDOK naar de ECHTE locatie, met Supabase-cache.

    Geen geforceerde gemeente-constraint: PDOK mag de werkelijke stad teruggeven. Dit is
    cruciaal omdat scrapers (m.n. Kamernet) ook listings uit omliggende steden teruggeven —
    die moeten hun eigen stad/wijk krijgen, zodat de stad-validatie ze correct uitsluit.

    Geeft een dict terug met straat, huisnummer, postcode, wijk, buurt, stad, lat, lng,
    of None als PDOK niets vindt of bij een (tijdelijke) fout.
    """
    if not adres or not adres.strip():
        return None

    norm_key = _norm_adres(adres)
    input_pc_hnr = _pc_hnr_key_from_input(adres)  # canonieke key indien al in input aanwezig

    # 1. Cache check — eerst op postcode+huisnummer (indien afleidbaar uit input), dan op
    #    het genormaliseerde adres. Eerste hit wint.
    for key in dict.fromkeys(k for k in (input_pc_hnr, norm_key) if k):
        cached = await _cache_get(key)
        if cached is not None:
            return cached["result"]  # None bij negatieve cache-hit

    # 2. PDOK bevragen
    try:
        result = await _pdok_lookup(adres)
    except Exception as e:
        logger.warning(f"[geocode] PDOK-fout voor {adres!r}: {e}")
        return None  # tijdelijke fout: niet cachen, volgende keer opnieuw proberen

    # 3. Cachen
    if result:
        # Canonieke key uit het PDOK-resultaat (postcode + huisnummer); val terug op
        # het genormaliseerde adres als PDOK die onverhoopt niet meegeeft.
        canonical_key = _pc_hnr_key(result.get("postcode"), result.get("huisnummer")) or norm_key
        await _cache_put(canonical_key, adres, result)
        if norm_key != canonical_key:
            # alias zodat exact dit input-adres de volgende keer direct een hit geeft
            await _cache_put(norm_key, adres, result)
    else:
        # negatieve cache op het genormaliseerde adres
        await _cache_put(norm_key, adres, None)

    return result
