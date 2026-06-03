"""Telegram-notificaties — idempotent via DB claim (INSERT ON CONFLICT DO NOTHING)."""
import os

from telegram import Bot

from crypto import safe_decrypt  # PRIVACY-FIX: decrypt PII fields before use
from db import get_db
from listings_db import UPSERT_BATCH, get_listings_for_user


def resolve_listing_id(db, listing: dict) -> str | None:
    """listing_id uit record, anders lookup op url (legacy)."""
    lid = listing.get("id")
    if lid:
        return str(lid)
    url = (listing.get("url") or "").strip()
    if not url:
        return None
    rows = db.table("listings").select("id").eq("url", url).limit(1).execute().data or []
    return str(rows[0]["id"]) if rows else None


def _log_notif(user_id: str, listing_id: str | None, status: str, url: str = "") -> None:
    extra = f" url={url}" if url and status != "new" else ""
    if status == "new" and url:
        extra = f" url={url}"
    lid = listing_id or "?"
    print(f"[notif] user_id={user_id} listing_id={lid} status={status}{extra}", flush=True)


def claim_notification(db, user_id: str, listing_id: str) -> bool:
    """
    Claim (user_id, listing_id) in sent_notifications.
    True = nieuw geclaimd → Telegram mag verstuurd worden.
    """
    try:
        r = db.rpc(
            "claim_sent_notification",
            {"p_user_id": user_id, "p_listing_id": listing_id},
        ).execute()
        data = r.data
        if data is None:
            return False
        if isinstance(data, list):
            return len(data) > 0 and data[0] is not None
        return bool(data)
    except Exception as e:
        if "claim_sent_notification" not in str(e) and "PGRST202" not in str(e):
            raise
        return _claim_notification_insert_fallback(db, user_id, listing_id)


def _claim_notification_insert_fallback(db, user_id: str, listing_id: str) -> bool:
    """Fallback vóór migratie 013 (geen RPC)."""
    try:
        r = db.table("sent_notifications").insert({
            "user_id": user_id,
            "listing_id": listing_id,
        }).execute()
        return bool(r.data)
    except Exception as e:
        err = str(e).lower()
        if "23505" in str(e) or "duplicate" in err or "unique" in err:
            return False
        raise


def claim_notifications_batch(db, pairs: list[dict]) -> list[dict]:
    """
    Batch-claim; retourneert alleen nieuw ingevoegde (user_id, listing_id, id).
    pairs: [{"user_id": "...", "listing_id": "..."}, ...]
    """
    if not pairs:
        return []
    try:
        r = db.rpc(
            "claim_sent_notifications_batch",
            {"p_pairs": pairs},
        ).execute()
        return r.data or []
    except Exception as e:
        if "claim_sent_notifications_batch" not in str(e) and "PGRST202" not in str(e):
            raise
        claimed = []
        for p in pairs:
            if claim_notification(db, p["user_id"], p["listing_id"]):
                claimed.append(p)
        return claimed


async def stuur_telegram(chat_id: str, bericht: str):
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    try:
        await bot.send_message(chat_id=chat_id, text=bericht)
    except Exception as e:
        print(f"[telegram] Fout voor {chat_id}: {e}", flush=True)


async def stuur_warning(bericht: str):
    chat_id = os.getenv('ADMIN_CHAT_ID', '').strip()
    if not chat_id:
        return
    bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
    try:
        await bot.send_message(chat_id=chat_id, text=bericht)
    except Exception as e:
        print(f"[telegram] Warning fout: {e}", flush=True)


def maak_bericht(listing: dict) -> str:
    adres = listing.get("adres") or "Onbekend adres"
    stad = listing.get("stad") or ""
    prijs = listing.get("prijs")
    oppervlakte = listing.get("oppervlakte")
    type_woning = listing.get("type_woning")
    url = listing.get("url", "")

    regels = ["🏠 Nieuwe woning gevonden!\n"]
    regels.append(f"📍 {adres}{', ' + stad if stad else ''}")
    if prijs:
        regels.append(f"💶 €{prijs}/maand")
    if oppervlakte:
        regels.append(f"📐 {oppervlakte}m²")
    if type_woning:
        regels.append(f"🏷️ {type_woning}")
    regels.append(f"\n🔗 {url}")

    return "\n".join(regels)


async def verwerk_notificaties(prefs: list) -> int:
    db = get_db()
    gestuurd = 0

    for pref in prefs:
        user_id = pref.get("user_id")
        chat_id = (safe_decrypt(pref.get("telegram_chat_id")) or "").strip()
        naam = safe_decrypt(pref.get("naam")) or user_id

        if not chat_id or not user_id:
            continue

        kandidaten = get_listings_for_user(pref)
        by_listing_id: dict[str, dict] = {}
        pairs: list[dict] = []
        for listing in kandidaten:
            listing_id = resolve_listing_id(db, listing)
            if not listing_id:
                _log_notif(user_id, None, "skip_no_id", listing.get("url", ""))
                continue
            by_listing_id[listing_id] = listing
            pairs.append({"user_id": user_id, "listing_id": listing_id})

        for i in range(0, len(pairs), UPSERT_BATCH):
            chunk = pairs[i : i + UPSERT_BATCH]
            claimed = claim_notifications_batch(db, chunk)
            claimed_ids = {str(row.get("listing_id")) for row in claimed}

            for p in chunk:
                lid = p["listing_id"]
                if lid not in claimed_ids:
                    _log_notif(user_id, lid, "duplicate")
                    continue
                listing = by_listing_id[lid]
                _log_notif(user_id, lid, "new", listing.get("url", ""))
                await stuur_telegram(chat_id, maak_bericht(listing))
                gestuurd += 1
                print(f"[notificaties] → {naam}: {listing.get('url')}", flush=True)

    return gestuurd
