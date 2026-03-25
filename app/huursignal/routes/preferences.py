from datetime import datetime, timezone
from flask import Blueprint, session, redirect, url_for, request, jsonify, render_template

from db import get_db
from ..decorators import login_required
from ..helpers import WONING_TYPES

pref_bp = Blueprint("pref", __name__)


@pref_bp.route("/onboarding")
@login_required
def onboarding():
    naam = session.pop("naam", "")
    return render_template("onboarding.html", pref={"naam": naam}, woning_types=WONING_TYPES)


@pref_bp.route("/instellingen")
@login_required
def instellingen():
    db = get_db()
    result = db.table("user_preferences").select("*").eq("user_id", session["user_id"]).execute()
    pref = result.data[0] if result.data else {}
    return render_template("instellingen.html", pref=pref, woning_types=WONING_TYPES)


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
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }

    existing = db.table("user_preferences").select("id").eq("user_id", user_id).execute()
    if existing.data:
        db.table("user_preferences").update(pref_data).eq("user_id", user_id).execute()
    else:
        db.table("user_preferences").insert(pref_data).execute()

    return jsonify({"ok": True})
