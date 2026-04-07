import os
import requests as req
from datetime import datetime, timezone
from flask import Blueprint, session, redirect, url_for, request, jsonify, render_template

from db import get_db
from ..decorators import login_required
from ..helpers import WONING_TYPES, get_bot_username

pref_bp = Blueprint("pref", __name__)


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
        "naam":             data.get("naam"),
        "telegram_chat_id": data.get("telegram_chat_id"),
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
    chat_id = result.data[0].get("telegram_chat_id") if result.data else None

    return render_template("onboarding_validate.html", chat_id=chat_id, bot_username=get_bot_username())


@pref_bp.route("/api/telegram/validate", methods=["POST"])
@login_required
def api_telegram_validate():
    data = request.json or {}

    # Gebruik meegegeven chat_id (inline test vanuit form), anders lees uit DB
    chat_id = (data.get("chat_id") or "").strip()
    if not chat_id:
        db = get_db()
        result = db.table("user_preferences").select("telegram_chat_id").eq("user_id", session["user_id"]).execute()
        chat_id = (result.data[0].get("telegram_chat_id") or "") if result.data else ""

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
        desc = resp.get("description", "Onbekende Telegram-fout")
        return jsonify({"ok": False, "error": desc})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
