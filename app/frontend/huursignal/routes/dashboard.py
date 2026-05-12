from datetime import datetime, timezone, timedelta
from flask import Blueprint, session, redirect, url_for, request, render_template

from db import get_db
from ..decorators import login_required

dash_bp = Blueprint("dash", __name__)

LEEFTIJD_OPTIES = [
    ("", "Alles"),
    ("1", "Vandaag"),
    ("3", "Laatste 3 dagen"),
    ("7", "Laatste week"),
]


def _get_pref(user_id, db):
    result = db.table("user_preferences").select("*").eq("user_id", user_id).execute()
    return result.data[0] if result.data else None


@dash_bp.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    db = get_db()

    pref = _get_pref(user_id, db)
    if not pref:
        return redirect(url_for("pref.onboarding"))

    tab = request.args.get("tab", "woningen")

    if tab == "nieuwbouw":
        return _render_nieuwbouw(pref, db)
    return _render_woningen(pref, db)


def _render_woningen(pref, db):
    page     = request.args.get("page", 1, type=int)
    leeftijd = request.args.get("leeftijd", "", type=str)
    per_page = 20
    offset   = (page - 1) * per_page

    stad      = pref.get("stad", "")
    min_prijs = pref.get("min_prijs") or 0
    max_prijs = pref.get("max_prijs") or 9999
    types     = pref.get("type_woning") or []

    query = (db.table("listings")
               .select("*", count="exact")
               .eq("stad", stad)
               .eq("beschikbaar", True)
               .gte("prijs", min_prijs)
               .lte("prijs", max_prijs)
               .order("eerste_gezien", desc=True)
               .range(offset, offset + per_page - 1))

    if leeftijd in ("1", "3", "7"):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(leeftijd))).isoformat()
        query = query.gte("eerste_gezien", cutoff)

    result = query.execute()
    raw    = result.data or []
    totaal = result.count or 0

    listings = [l for l in raw
                if not (l.get("type_woning") and types and l["type_woning"] not in types)]

    totaal_paginas = max(1, (totaal + per_page - 1) // per_page)

    filter_info = f"{stad} · €\u00a0{min_prijs}–{max_prijs}/maand"
    if types:
        filter_info += " · " + ", ".join(types)

    return render_template(
        "dashboard.html",
        tab="woningen",
        listings=listings,
        totaal=totaal,
        filter_info=filter_info,
        page=page,
        totaal_paginas=totaal_paginas,
        leeftijd=leeftijd,
        leeftijd_opties=LEEFTIJD_OPTIES,
    )


def _render_nieuwbouw(pref, db):
    stad = pref.get("stad", "")

    # Filter op stad — radius vereist coördinaten die de tabel niet heeft
    result = (db.table("nieuwbouw_projects")
                .select("*")
                .ilike("city", stad)
                .order("scraped_at", desc=True)
                .execute())
    projecten = result.data or []

    return render_template(
        "dashboard.html",
        tab="nieuwbouw",
        projecten=projecten,
        filter_info=stad,
    )
