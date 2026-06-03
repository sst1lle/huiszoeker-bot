from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, render_template, session

from db import get_db
# PRIVACY-FIX: decrypt naam before displaying in admin UI
from crypto import safe_decrypt
from ..decorators import admin_required
from ..helpers import WONING_TYPES
from shared.cities import stad_pref_opslaan, stad_slugs_uit_pref

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
            # PRIVACY-FIX: decrypt naam and telegram_chat_id before displaying in admin UI
            "naam":           safe_decrypt(pref.get("naam")) or "",
            "stad":           pref.get("stad") or "",
            "min_prijs":      pref.get("min_prijs") or 0,
            "max_prijs":      pref.get("max_prijs") or 0,
            "type_woning":    pref.get("type_woning") or [],
            "telegram_chat_id": safe_decrypt(pref.get("telegram_chat_id")) or "",
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
        "stad":             stad_pref_opslaan(data.get("stad") or ""),
        "min_prijs":        data.get("min_prijs"),
        "max_prijs":        data.get("max_prijs"),
        "type_woning":      data.get("type_woning", []),
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
        r.setdefault("status", "onbekend")
        r.setdefault("error_message", None)

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


@admin_bp.route("/admin/test-scraper/<name>", methods=["POST"])
@admin_required
def api_admin_test_scraper(name):
    """
    Voer één scraper eenmalig uit met het admin-profiel (test-knop).
    Slaat NIETS op in de DB en stuurt GEEN notificaties; voert wél PDOK-verrijking uit
    zodat de wijk per listing zichtbaar is. Geeft alleen preview-resultaten terug.
    """
    import time
    import asyncio
    import requests as _req

    db = get_db()
    pref_rows = db.table("user_preferences").select("*").eq("user_id", session["user_id"]).execute().data
    if not pref_rows:
        return jsonify({"ok": False, "error": "Geen admin-profiel ingesteld."}), 400
    pref = pref_rows[0]
    steden = stad_slugs_uit_pref(pref.get("stad") or "")
    if not steden:
        return jsonify({"ok": False, "error": "Profiel heeft geen stad ingesteld."}), 400
    min_p = pref.get("min_prijs") or 0
    max_p = pref.get("max_prijs") or 1500
    types = pref.get("type_woning") or []

    try:
        from main import load_scrapers, verrijk_met_geocoding
    except Exception as e:
        return jsonify({"ok": False, "error": f"Kon scraper-module niet laden: {e}"}), 500

    scraper = next((s for s in load_scrapers() if s.name == name), None)
    if scraper is None:
        return jsonify({"ok": False, "error": f"Onbekende scraper '{name}'."}), 404

    byparr_needed = bool(getattr(scraper, "flaresolverr_only", False))
    # Onderscheid 'echt offline' (verbinding geweigerd) van 'online maar bezig'
    # (Byparr is serieel → /health time-out tijdens een scrape betekent NIET offline).
    try:
        _req.get("http://byparr:8191/health", timeout=(3, 8))
        byparr_ok = True
    except _req.exceptions.ReadTimeout:
        byparr_ok = True   # poort open, byparr is bezig → wel online
    except Exception:
        byparr_ok = False  # ConnectionError/ConnectTimeout → echt offline

    t0 = time.time()
    listings, errors = [], []
    for stad in steden:
        try:
            # _scrape_impl: directe test buiten de scheduler-gateway om (geen DB-opslag/notificaties)
            listings += scraper._scrape_impl(stad=stad, min_prijs=min_p, max_prijs=max_p, types=types)
        except Exception as e:
            errors.append(f"{stad}: {e}")
    try:
        asyncio.run(verrijk_met_geocoding(listings))  # wijk zichtbaar maken (faalt zacht)
    except Exception as e:
        errors.append(f"geocoding: {e}")
    seconden = round(time.time() - t0, 1)

    preview = [{
        "titel": l.get("adres") or "—",
        "prijs": l.get("prijs"),
        "wijk":  l.get("wijk"),
        "stad":  l.get("stad"),
        "url":   l.get("url"),
    } for l in listings[:5]]

    return jsonify({
        "ok": True,
        "aantal": len(listings),
        "preview": preview,
        "byparr_needed": byparr_needed,
        "byparr_ok": byparr_ok,
        "errors": errors,
        "seconden": seconden,
    })


@admin_bp.route("/scheduler/status")
@admin_required
def scheduler_status():
    """Scheduler-status per scraper: last/next run, lock en waaróm wel/niet draaien."""
    from scheduler.scrape_scheduler import status_info
    from main import load_scrapers
    db = get_db()
    enabled = {c["name"]: c.get("enabled", True)
               for c in (db.table("scraper_config").select("name,enabled").execute().data or [])}
    names = sorted({s.name for s in load_scrapers()})
    return jsonify({"scrapers": [status_info(n, enabled.get(n, True)) for n in names]})
