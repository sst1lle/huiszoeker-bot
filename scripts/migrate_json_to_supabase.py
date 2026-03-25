"""
Migratiescript: JSON-bestanden → Supabase

Leest data/users/*.json en maakt per gebruiker:
  - Een Supabase Auth account (tijdelijk wachtwoord, te resetten via e-mail)
  - Een rij in user_preferences

Idempotent: als een e-mail al bestaat in Auth, wordt die overgeslagen.
data/seen/ wordt NIET gemigreerd — fresh start.

Gebruik:
    SUPABASE_URL=... SUPABASE_KEY=... python scripts/migrate_json_to_supabase.py

Of via Docker:
    docker exec huiszoeker python /app/scripts/migrate_json_to_supabase.py
"""

import os
import sys
import json
import glob
import secrets
import string

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
USERS_DIR    = os.path.join(os.path.dirname(__file__), "..", "data", "users")

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


def main():
    bestanden = sorted(glob.glob(os.path.join(USERS_DIR, "*.json")))

    if not bestanden:
        print(f"❌ Geen gebruikersbestanden gevonden in {USERS_DIR}")
        sys.exit(1)

    print(f"Huursignaal migratie: {len(bestanden)} gebruikers gevonden\n")
    print("⚠️  data/seen/ wordt NIET gemigreerd — gebruikers starten fris.")
    print("─" * 60)

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
    print(f"✅ Geslaagd: {geslaagd}  |  ❌ Mislukt: {mislukt}")
    print("\nVolgende stap: laat gebruikers inloggen via de webinterface")
    print("en een nieuw wachtwoord instellen via Supabase → Auth → Users.")


if __name__ == "__main__":
    main()
