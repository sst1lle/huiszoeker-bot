"""
Migratiescript: JSON-bestanden → Supabase

Leest data/users/*.json en maakt per gebruiker:
  - Een Supabase Auth account (tijdelijk wachtwoord, te resetten via e-mail)
  - Een rij in user_preferences
  - sent_notifications voor alle URLs in data/seen/{uid}.json
    (als minimale listing met beschikbaar=False, zodat de bot ze niet opnieuw stuurt)

Idempotent: bestaande accounts/preferences/notifications worden overgeslagen.

Gebruik:
    python scripts/migrate_json_to_supabase.py
"""

import os
import sys
import json
import glob
import re
import secrets
import string
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
USERS_DIR    = os.path.join(os.path.dirname(__file__), "..", "data", "users")
SEEN_DIR     = os.path.join(os.path.dirname(__file__), "..", "data", "seen")

db = create_client(SUPABASE_URL, SUPABASE_KEY)


def tijdelijk_wachtwoord() -> str:
    chars = string.ascii_letters + string.digits
    return "Hs-" + "".join(secrets.choice(chars) for _ in range(12))


def user_bestaat_in_auth(email: str) -> str | None:
    """Geeft user_id terug als het account al bestaat, anders None."""
    try:
        result = db.auth.admin.list_users()
        for user in result:
            if user.email == email:
                return user.id
    except Exception as e:
        print(f"  ⚠️  Kon Auth-gebruikers niet ophalen: {e}")
    return None


def preference_bestaat(user_id: str) -> bool:
    result = db.table("user_preferences").select("id").eq("user_id", user_id).execute()
    return bool(result.data)


def migreer_user(uid: str, data: dict) -> bool:
    naam        = data.get("naam", uid)
    telegram_id = data.get("telegram_chat_id", "")
    stad        = data.get("stad", "")
    min_prijs   = data.get("min_prijs", 0)
    max_prijs   = data.get("max_prijs", 1500)

    # Gebruik naam@huursignaal.local als nep-e-mail als er geen echte is
    email = data.get("email") or f"{uid}@migratie.huursignaal.local"
    ww    = tijdelijk_wachtwoord()

    print(f"\n→ {naam} ({uid})")
    print(f"  e-mail: {email}")

    # ── Stap 1: Auth account aanmaken ──────────────────────────────────────
    user_id = user_bestaat_in_auth(email)

    if user_id:
        print(f"  ✅ Auth account bestaat al (id: {user_id[:8]}…)")
    else:
        try:
            result = db.auth.admin.create_user({
                "email": email,
                "password": ww,
                "email_confirm": True,
            })
            user_id = result.user.id
            print(f"  ✅ Auth account aangemaakt (id: {user_id[:8]}…)")
            print(f"  🔑 Tijdelijk wachtwoord: {ww}  ← sla op of stuur naar gebruiker")
        except Exception as e:
            print(f"  ❌ Auth aanmaken mislukt: {e}")
            return False

    # ── Stap 2: user_preferences upsert ────────────────────────────────────
    if preference_bestaat(user_id):
        print(f"  ✅ user_preferences bestaat al, overgeslagen")
        return True

    try:
        db.table("user_preferences").insert({
            "user_id":          user_id,
            "naam":             naam,
            "telegram_chat_id": telegram_id,
            "stad":             stad,
            "min_prijs":        min_prijs,
            "max_prijs":        max_prijs,
            "type_woning":      [],
        }).execute()
        print(f"  ✅ user_preferences aangemaakt (stad: {stad}, €{min_prijs}–{max_prijs})")
        return True
    except Exception as e:
        print(f"  ❌ user_preferences insert mislukt: {e}")
        return False


def laad_uid_naar_user_id() -> dict[str, str]:
    """Bouw een mapping van oud JSON-uid → Supabase user_id op basis van e-mail patroon."""
    mapping = {}
    try:
        users = db.auth.admin.list_users()
        for user in users:
            m = re.match(r"^([0-9a-f]+)@migratie\.huursignaal\.local$", user.email or "")
            if m:
                mapping[m.group(1)] = user.id
    except Exception as e:
        print(f"⚠️  Kon Auth-gebruikers niet ophalen: {e}")
    return mapping


def upsert_minimale_listing(url: str) -> str | None:
    """Zoek listing op URL of insert een minimale stub met beschikbaar=False."""
    bestaand = db.table("listings").select("id").eq("url", url).execute()
    if bestaand.data:
        return bestaand.data[0]["id"]

    # Leid source en stad af uit de URL
    source = "pararius" if "pararius" in url else "kamernet"
    stad = None
    m = re.search(r"/(appartement|kamer|studio|woning)-te-huur/([^/]+)/", url)
    if m:
        stad = m.group(2)

    nu = datetime.now(timezone.utc).isoformat()
    try:
        result = db.table("listings").insert({
            "source":            source,
            "url":               url,
            "stad":              stad,
            "beschikbaar":       False,
            "eerste_gezien":     nu,
            "created_at":        nu,
            "laatst_gevalideerd": nu,
        }).execute()
        return result.data[0]["id"] if result.data else None
    except Exception:
        return None


def migreer_gezien(uid_naar_user_id: dict[str, str]):
    """Migreer data/seen/*.json naar sent_notifications."""
    print("\n── Stap 2: seen-URLs migreren ──────────────────────────────")

    bestanden = sorted(glob.glob(os.path.join(SEEN_DIR, "*.json")))
    if not bestanden:
        print("Geen seen-bestanden gevonden, overgeslagen.")
        return

    totaal_notifs = 0
    totaal_listings = 0

    for pad in bestanden:
        uid = os.path.basename(pad).replace(".json", "")
        user_id = uid_naar_user_id.get(uid)

        try:
            with open(pad) as f:
                urls = json.load(f)
        except Exception as e:
            print(f"  ⚠️  Kan {pad} niet lezen: {e}")
            continue

        if not user_id:
            print(f"\n→ {uid}: geen Auth-account gevonden, overgeslagen ({len(urls)} URLs)")
            continue

        print(f"\n→ {uid[:8]}… ({len(urls)} URLs)")

        notifs = 0
        for url in urls:
            url = url.rstrip("/")
            listing_id = upsert_minimale_listing(url)
            if not listing_id:
                continue

            totaal_listings += 1
            try:
                db.table("sent_notifications").insert({
                    "user_id":    user_id,
                    "listing_id": listing_id,
                }).execute()
                notifs += 1
                totaal_notifs += 1
            except Exception:
                pass  # UNIQUE constraint — al aanwezig

        print(f"  ✅ {notifs} sent_notifications aangemaakt")

    print(f"\nTotaal: {totaal_listings} listings, {totaal_notifs} notificaties gemigreerd")


def main():
    bestanden = sorted(glob.glob(os.path.join(USERS_DIR, "*.json")))

    if not bestanden:
        print(f"❌ Geen gebruikersbestanden gevonden in {USERS_DIR}")
        sys.exit(1)

    print(f"Huursignaal migratie: {len(bestanden)} gebruikers gevonden\n")
    print("── Stap 1: gebruikers & voorkeuren ─────────────────────────")

    geslaagd = 0
    mislukt  = 0

    for pad in bestanden:
        uid = os.path.basename(pad).replace(".json", "")
        try:
            with open(pad) as f:
                data = json.load(f)
        except Exception as e:
            print(f"\n❌ Kan {pad} niet lezen: {e}")
            mislukt += 1
            continue

        if migreer_user(uid, data):
            geslaagd += 1
        else:
            mislukt += 1

    print("\n" + "─" * 60)
    print(f"Gebruikers: ✅ {geslaagd}  ❌ {mislukt}")

    # Stap 2: seen-URLs migreren
    uid_naar_user_id = laad_uid_naar_user_id()
    migreer_gezien(uid_naar_user_id)

    print("\n" + "─" * 60)
    print("Migratie klaar.")
    print("Volgende stap: laat gebruikers inloggen via de webinterface")
    print("en een nieuw wachtwoord instellen via Supabase → Auth → Users.")


if __name__ == "__main__":
    main()
