#!/usr/bin/env python3
"""Eenmalige test: admin Telegram + idempotente notificatie-pipeline."""
import asyncio
import os
import sys

from db import get_db
from crypto import safe_decrypt
from notifications import stuur_telegram, verwerk_notificaties
from listings_db import get_listings_for_user


async def main() -> int:
    db = get_db()
    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if not admin_email:
        print("FAIL: ADMIN_EMAIL niet gezet", flush=True)
        return 1

    admin_id = None
    for u in db.auth.admin.list_users():
        if (u.email or "").strip().lower() == admin_email:
            admin_id = u.id
            break

    if not admin_id:
        print(f"FAIL: geen auth user voor {admin_email}", flush=True)
        return 1

    rows = db.table("user_preferences").select("*").eq("user_id", admin_id).execute().data
    if not rows:
        print(f"FAIL: geen user_preferences voor {admin_id}", flush=True)
        return 1

    pref = rows[0]
    chat_id = (safe_decrypt(pref.get("telegram_chat_id")) or "").strip()
    naam = safe_decrypt(pref.get("naam")) or admin_email
    print(f"Admin: {naam} user_id={admin_id} chat_id={'ja' if chat_id else 'NEE'}", flush=True)

    if not chat_id:
        print("FAIL: geen telegram_chat_id in profiel", flush=True)
        return 1

    await stuur_telegram(chat_id, "🧪 Huiszoeker test — idempotente notificatie-pipeline (admin)")
    print("OK: test Telegram verstuurd", flush=True)

    print(f"Kandidaten: {len(get_listings_for_user(pref))}", flush=True)

    n1 = await verwerk_notificaties([pref])
    print(f"Run 1: {n1} nieuwe Telegram(s)", flush=True)

    n2 = await verwerk_notificaties([pref])
    print(f"Run 2: {n2} nieuwe (verwacht 0)", flush=True)

    return 0 if n2 == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
