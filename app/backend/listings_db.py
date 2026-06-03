"""Listings upsert + query helpers (Supabase listings tabel)."""
from datetime import datetime, timezone

from db import get_db
from shared.cities import stad_voor_db, stad_slugs_uit_pref

UPSERT_BATCH = 200

_SUPABASE_LISTING_FIELDS = {
    "source", "external_id", "url", "adres", "stad",
    "prijs", "oppervlakte", "type_woning", "foto_url", "beschikbaar",
    "postcode", "wijk", "buurt", "lat", "lng",
}

_EXISTING_LISTING_COLS = (
    "id, url, source, beschikbaar, prijs, adres, stad, oppervlakte, type_woning, "
    "foto_url, external_id, postcode, wijk, buurt, lat, lng, eerste_gezien, created_at"
)

_NOTIFICATIE_LIMIT = 1000
_SKIP_TYPE_CHECK = {"funda", "pararius"}
_PARKING_MARKERS = (
    "parkeergelegenheid",
    "parkeerplaats",
    "parking",
    "garage",
)


def _prepare_upsert_row(listing: dict, record: dict | None, nu: str) -> dict | None:
    """Zelfde merge-logica als voorheen upsert_listing; één rij voor bulk upsert op url."""
    if not listing.get("prijs"):
        return None

    supabase_data = {k: v for k, v in listing.items() if k in _SUPABASE_LISTING_FIELDS}
    if supabase_data.get("stad"):
        c = stad_voor_db(supabase_data["stad"])
        if c:
            supabase_data["stad"] = c

    scrape_beschikbaar = listing.get("beschikbaar", True)

    if record:
        updates = {"laatst_gevalideerd": nu, "beschikbaar": scrape_beschikbaar}
        if not record.get("prijs"):
            for field in ("adres", "prijs", "oppervlakte", "type_woning", "foto_url"):
                if listing.get(field) is not None:
                    updates[field] = listing[field]
            c = stad_voor_db(listing.get("stad"))
            if c:
                updates["stad"] = c
        if any(listing.get(f) is not None for f in ("wijk", "lat", "lng", "postcode")):
            for field in ("postcode", "wijk", "buurt", "lat", "lng"):
                if listing.get(field) is not None:
                    updates[field] = listing[field]
            c = stad_voor_db(listing.get("stad"))
            if c:
                updates["stad"] = c
        row = {k: record.get(k) for k in _SUPABASE_LISTING_FIELDS}
        row["url"] = listing["url"]
        row["source"] = record.get("source") or listing.get("source")
        row.update(updates)
        return row

    return {
        **supabase_data,
        "eerste_gezien": nu,
        "created_at": nu,
        "laatst_gevalideerd": nu,
    }


def upsert_listings_batch(listings: list[dict]) -> int:
    """Bulk upsert op url (batch 200); behoudt migratie-stub- en geo-merge gedrag."""
    candidates = [l for l in listings if l.get("prijs") and l.get("url")]
    if not candidates:
        return 0

    db = get_db()
    nu = datetime.now(timezone.utc).isoformat()
    urls = list({l["url"] for l in candidates})
    existing_by_url: dict[str, dict] = {}

    for i in range(0, len(urls), UPSERT_BATCH):
        chunk = urls[i : i + UPSERT_BATCH]
        for row in (
            db.table("listings")
            .select(_EXISTING_LISTING_COLS)
            .in_("url", chunk)
            .execute()
            .data
            or []
        ):
            existing_by_url[row["url"]] = row

    rows: list[dict] = []
    for listing in candidates:
        row = _prepare_upsert_row(listing, existing_by_url.get(listing["url"]), nu)
        if row:
            rows.append(row)

    if not rows:
        return 0

    for i in range(0, len(rows), UPSERT_BATCH):
        db.table("listings").upsert(
            rows[i : i + UPSERT_BATCH], on_conflict="url",
        ).execute()

    return len(rows)


def is_parking_listing(listing: dict) -> bool:
    """Voorkom dat parkeerplaatsen/garages als woning-notificatie worden aangeboden."""
    url = (listing.get("url") or "").lower()
    woning_type = (listing.get("type_woning") or "").lower()
    adres = (listing.get("adres") or "").lower()
    haystack = " ".join((url, woning_type, adres))
    return any(marker in haystack for marker in _PARKING_MARKERS)


def get_listings_for_user(pref: dict) -> list:
    """
    Kandidaat-listings voor notificaties: filter in SQL (stad, prijs, beschikbaar)
    + Python (wijk/type/parking). Dedupe gebeurt via claim_sent_notification (INSERT).
    """
    db = get_db()
    user_id = pref.get("user_id")
    min_prijs = pref.get("min_prijs") or 0
    max_prijs = pref.get("max_prijs") or 9999
    types = pref.get("type_woning") or []

    steden_values = stad_slugs_uit_pref(pref.get("stad") or "")
    if not steden_values:
        return []

    gewenste_wijken = pref.get("gewenste_wijken") or []
    wijk_filter = {w.strip().lower() for w in gewenste_wijken if w and w.strip()}

    listings = (
        db.table("listings")
        .select("*")
        .in_("stad", steden_values)
        .eq("beschikbaar", True)
        .gte("prijs", min_prijs)
        .lte("prijs", max_prijs)
        .order("created_at", desc=True)
        .limit(_NOTIFICATIE_LIMIT)
        .execute()
        .data
        or []
    )

    steden_log = ",".join(stad_slugs_uit_pref(pref.get("stad") or ""))
    print(
        f"[notificaties] Filtered listings via SQL: stad={steden_log} count={len(listings)}",
        flush=True,
    )

    kandidaten = []
    for listing in listings:
        if is_parking_listing(listing):
            continue

        source = listing.get("source", "")
        if source not in _SKIP_TYPE_CHECK:
            listing_type = listing.get("type_woning")
            if listing_type and types and listing_type not in types:
                continue

        if wijk_filter:
            listing_wijk = (listing.get("wijk") or "").strip().lower()
            if listing_wijk not in wijk_filter:
                continue

        kandidaten.append(listing)

    if kandidaten:
        print(
            f"[notificaties] Kandidaten for user={user_id}: count={len(kandidaten)}",
            flush=True,
        )

    return kandidaten
