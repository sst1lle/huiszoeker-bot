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

    # Alle auth-gebruikers ophalen (inclusief zonder voorkeuren)
    auth_users = db.auth.admin.list_users()

    # Voorkeuren indexeren op user_id
    prefs = db.table("user_preferences").select("*").execute().data or []
    prefs_by_uid = {p["user_id"]: p for p in prefs}

    users = []
    for u in auth_users:
        pref = prefs_by_uid.get(u.id, {})
        users.append({
            "user_id":        u.id,
            "email":          u.email or "",
            "naam":           pref.get("naam") or "",
            "stad":           pref.get("stad") or "",
            "min_prijs":      pref.get("min_prijs") or 0,
            "max_prijs":      pref.get("max_prijs") or 0,
            "type_woning":    pref.get("type_woning") or [],
            "telegram_chat_id": pref.get("telegram_chat_id") or "",
            "radius_km":      pref.get("radius_km"),
            "has_prefs":      bool(pref),
        })

    users.sort(key=lambda u: (u["naam"] or u["email"]).lower())

    return render_template("admin.html", users=users, woning_types=WONING_TYPES)


@admin_bp.route("/api/admin/users/<user_id>", methods=["PUT"])
@admin_required
def api_admin_user_put(user_id):
    data = request.json or {}
    db = get_db()

    pref_data = {
        "user_id":          user_id,
        "naam":             data.get("naam"),
        "telegram_chat_id": data.get("telegram_chat_id"),
        "stad":             data.get("stad") or "",
        "min_prijs":        data.get("min_prijs"),
        "max_prijs":        data.get("max_prijs"),
        "type_woning":      data.get("type_woning", []),
        "radius_km":        data.get("radius_km") or None,
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }

    email = data.get("email", "").strip()
    if email:
        db.auth.admin.update_user_by_id(user_id, {"email": email})

    existing = db.table("user_preferences").select("id").eq("user_id", user_id).execute()
    if existing.data:
        db.table("user_preferences").update(pref_data).eq("user_id", user_id).execute()
    else:
        db.table("user_preferences").insert(pref_data).execute()

    return jsonify({"ok": True})


@admin_bp.route("/api/admin/users/<user_id>", methods=["DELETE"])
@admin_required
def api_admin_user_delete(user_id):
    db = get_db()
    db.auth.admin.delete_user(user_id)  # cascades naar user_preferences en sent_notifications
    return jsonify({"ok": True})


_SCRAPER_DISPLAY = {
    "pararius":           "Pararius",
    "kamernet":           "Kamernet",
    "funda":              "Funda",
    "nieuwbouw_nederland": "nieuwbouw-nederland.nl",
    "nieuwbouw_nl":       "nieuwbouw.nl",
}

_CAT_ORDER = ["huurwoningen", "nieuwbouw"]
_CAT_LABELS = {
    "huurwoningen": "Huurwoningen",
    "nieuwbouw":    "Nieuwbouw",
}
_COUNT_LABEL = {
    "huurwoningen": "listings",
    "nieuwbouw":    "projecten",
}


@admin_bp.route("/admin/scrapers")
@admin_required
def admin_scrapers():
    db = get_db()
    rows = db.table("scraper_config").select("*").order("name").execute().data or []

    for r in rows:
        r["display_name"] = _SCRAPER_DISPLAY.get(r["name"], r["name"])
        cat = r.get("category") or "huurwoningen"
        r["category"] = cat
        r["count_label"] = _COUNT_LABEL.get(cat, "items")

    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["category"], []).append(r)

    grouped = [
        (_CAT_LABELS.get(cat, cat.title()), groups[cat])
        for cat in _CAT_ORDER if cat in groups
    ]
    for cat, scrapers in groups.items():
        if cat not in _CAT_ORDER:
            grouped.append((cat.title(), scrapers))

    return render_template("admin_scrapers.html", grouped=grouped, total=len(rows))


@admin_bp.route("/api/admin/scrapers/<name>", methods=["POST"])
@admin_required
def api_admin_scraper_toggle(name):
    data = request.json or {}
    enabled = bool(data.get("enabled", True))
    db = get_db()

    bestaand = db.table("scraper_config").select("name").eq("name", name).execute()
    if bestaand.data:
        db.table("scraper_config").update({"enabled": enabled}).eq("name", name).execute()
    else:
        db.table("scraper_config").insert({"name": name, "enabled": enabled}).execute()

    return jsonify({"ok": True, "name": name, "enabled": enabled})
