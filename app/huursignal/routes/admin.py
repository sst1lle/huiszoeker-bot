from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, render_template

from db import get_db
from ..decorators import admin_required
from ..helpers import WONING_TYPES

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin")
@admin_required
def admin_page():
    db = get_db()
    users = db.table("user_preferences").select("*").order("naam").execute().data or []
    return render_template("admin.html", users=users, woning_types=WONING_TYPES)


@admin_bp.route("/api/admin/users/<user_id>", methods=["PUT"])
@admin_required
def api_admin_user_put(user_id):
    data = request.json or {}
    db = get_db()
    db.table("user_preferences").update({
        "naam":             data.get("naam"),
        "telegram_chat_id": data.get("telegram_chat_id"),
        "stad":             data.get("stad"),
        "min_prijs":        data.get("min_prijs"),
        "max_prijs":        data.get("max_prijs"),
        "type_woning":      data.get("type_woning", []),
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }).eq("user_id", user_id).execute()
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/users/<user_id>", methods=["DELETE"])
@admin_required
def api_admin_user_delete(user_id):
    db = get_db()
    db.table("user_preferences").delete().eq("user_id", user_id).execute()
    return jsonify({"ok": True})
