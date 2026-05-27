import os
import requests as req
from datetime import datetime, timezone
from flask import Blueprint, session, redirect, url_for, request, jsonify, render_template

from db import get_db
# PRIVACY-FIX: PII fields (naam, telegram_chat_id) encrypted at rest using Fernet
from crypto import encrypt, safe_decrypt
from ..decorators import login_required
from ..helpers import WONING_TYPES, get_bot_username

pref_bp = Blueprint("pref", __name__)


def _decrypt_pref(pref: dict) -> dict:
    """Decrypt PII fields in a user_preferences row before returning to UI."""
    # PRIVACY-FIX: always decrypt before rendering or using for API calls
    pref["naam"] = safe_decrypt(pref.get("naam"))
    pref["telegram_chat_id"] = safe_decrypt(pref.get("telegram_chat_id"))
    return pref


@pref_bp.route("/onboarding")
@login_required
def onboarding():
    naam = session.pop("naam", "")
    return render_template("onboarding.html", pref={"naam": naam}, woning_types=WONING_TYPES,
                           bot_username=get_bot_username())


@pref_bp.route("/instellingen")
@login_required
def instellingen():
    db = get_db()
    result = db.table("user_preferences").select("*").eq("user_id", session["user_id"]).execute()
    pref = result.data[0] if result.data else {}
    # PRIVACY-FIX: decrypt PII fields before passing to template
    pref = _decrypt_pref(pref)
    return render_template("instellingen.html", pref=pref, woning_types=WONING_TYPES,
                           bot_username=get_bot_username())


@pref_bp.route("/api/preferences", methods=["POST"])
@login_required
def api_preferences():
    data = request.json or {}
    user_id = session["user_id"]
    db = get_db()

    pref_data = {
        "user_id":          user_id,
        # PRIVACY-FIX: encrypt naam and telegram_chat_id before storing in database
        "naam":             encrypt(data.get("naam")),
        "telegram_chat_id": encrypt(data.get("telegram_chat_id")),
        "stad":             data.get("stad"),
        "min_prijs":        data.get("min_prijs"),
        "max_prijs":        data.get("max_prijs"),
        "type_woning":      data.get("type_woning", []),
        "radius_km":        data.get("radius_km") or None,
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }

    existing = db.table("user_preferences").select("id").eq("user_id", user_id).execute()
    if existing.data:
        db.table("user_preferences").update(pref_data).eq("user_id", user_id).execute()
    else:
        db.table("user_preferences").insert(pref_data).execute()

    return jsonify({"ok": True})


@pref_bp.route("/onboarding/validate")
@login_required
def onboarding_validate():
    db = get_db()
    result = db.table("user_preferences").select("telegram_chat_id").eq("user_id", session["user_id"]).execute()
    # PRIVACY-FIX: decrypt before displaying in template
    raw = result.data[0].get("telegram_chat_id") if result.data else None
    chat_id = safe_decrypt(raw)
    return render_template("onboarding_validate.html", chat_id=chat_id, bot_username=get_bot_username())


@pref_bp.route("/api/telegram/validate", methods=["POST"])
@login_required
def api_telegram_validate():
    data = request.json or {}

    chat_id = (data.get("chat_id") or "").strip()
    if not chat_id:
        db = get_db()
        result = db.table("user_preferences").select("telegram_chat_id").eq("user_id", session["user_id"]).execute()
        # PRIVACY-FIX: decrypt before using for Telegram API call
        raw = (result.data[0].get("telegram_chat_id") or "") if result.data else ""
        chat_id = (safe_decrypt(raw) or "").strip()

    if not chat_id:
        return jsonify({"ok": False, "error": "Geen Telegram chat ID ingesteld"})

    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        return jsonify({"ok": False, "error": "Bot token niet geconfigureerd"})

    try:
        r = req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "✅ Setup correct! De Huursignal-bot kan jou bereiken. Je ontvangt binnenkort meldingen over nieuwe woningen."},
            timeout=10,
        )
        resp = r.json()
        if resp.get("ok"):
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": resp.get("description", "Onbekende Telegram-fout")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@pref_bp.route("/instellingen/verwijder-account", methods=["POST"])
@login_required
def verwijder_account():
    """
    PRIVACY-FIX: Hard-delete all user data.
    Deleting from auth.users cascades to user_preferences, sent_notifications, motivation_letters.
    """
    user_id = session["user_id"]
    db = get_db()
    db.auth.admin.delete_user(user_id)
    session.clear()
    return jsonify({"ok": True})
