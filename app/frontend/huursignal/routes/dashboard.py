import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, session, redirect, url_for, request, render_template

from db import get_db
from shared.wijken import stad_db_variants
from ..decorators import login_required

dash_bp = Blueprint("dash", __name__)
logger = logging.getLogger(__name__)

LEEFTIJD_OPTIES = [
    ("", "Alles"),
    ("1", "Vandaag"),
    ("3", "Laatste 3 dagen"),
    ("7", "Laatste week"),
]


_HIDDEN_STATUSES = {"sold_out", "rented_out", "under_option", "registration_closed"}


def _query_nieuwbouw(db, stad: str) -> list[dict]:
    """
    Zoek actieve nieuwbouwprojecten op stad.
    Verbergt projecten met uitverkochte/verhuurd/optie/gesloten status.
    """
    stad_search = stad.replace("-", " ").strip()

    projecten = (
        db.table("nieuwbouw_projects")
          .select("*")
          .ilike("city", f"%{stad_search}%")
          .eq("is_active", True)
          .order("scraped_at", desc=True)
          .execute()
          .data or []
    )

    # Filter verborgen statussen in Python (is_active vangt lifecycle op, status vangt beschikbaarheid)
    zichtbaar = [p for p in projecten if p.get("status") not in _HIDDEN_STATUSES]
    verborgen = len(projecten) - len(zichtbaar)

    logger.info(
        f"[dashboard] nieuwbouw query stad='{stad}' → zoekterm='{stad_search}' → "
        f"{len(projecten)} actief, {verborgen} verborgen op status → {len(zichtbaar)} getoond"
    )

    if not projecten:
        sample = (
            db.table("nieuwbouw_projects")
              .select("city, source, is_active")
              .limit(10)
              .execute()
              .data or []
        )
        logger.warning(
            f"[dashboard] 0 nieuwbouw resultaten voor '{stad_search}'. "
            f"Steden in DB (steekproef): {[r.get('city') for r in sample]}"
        )

    for p in zichtbaar:
        if p.get("type"):
            p["type"] = p["type"].lower()

    return zichtbaar


@dash_bp.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    db = get_db()

    pref_result = db.table("user_preferences").select("*").eq("user_id", user_id).execute()
    pref = pref_result.data[0] if pref_result.data else None
    if not pref:
        return redirect(url_for("pref.onboarding"))

    tab      = request.args.get("tab", "huurwoningen")
    page     = request.args.get("page", 1, type=int)
    leeftijd = request.args.get("leeftijd", "", type=str)
    per_page = 20
    offset   = (page - 1) * per_page

    stad      = pref.get("stad", "")
    min_prijs = pref.get("min_prijs") or 0
    max_prijs = pref.get("max_prijs") or 9999
    types     = pref.get("type_woning") or []

    # ── Huurwoningen ──────────────────────────────────────────────────────────
    # Match op de echte (PDOK-)stad: slug + officiële gemeentenaam (bv. den-haag + 's-Gravenhage),
    # zodat listings uit omliggende steden (Delft/Rotterdam) niet meegenomen worden.
    query = (db.table("listings")
               .select("*", count="exact")
               .in_("stad", stad_db_variants(stad))
               .eq("beschikbaar", True)
               .gte("prijs", min_prijs)
               .lte("prijs", max_prijs)
               .order("eerste_gezien", desc=True)
               .range(offset, offset + per_page - 1))

    if leeftijd in ("1", "3", "7"):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(leeftijd))).isoformat()
        query = query.gte("eerste_gezien", cutoff)

    result   = query.execute()
    raw      = result.data or []
    totaal   = result.count or 0
    listings = [l for l in raw
                if not (l.get("type_woning") and types and l["type_woning"] not in types)]

    totaal_paginas = max(1, (totaal + per_page - 1) // per_page)

    filter_info = f"{stad} · €\u00a0{min_prijs}–{max_prijs}/maand"
    if types:
        filter_info += " · " + ", ".join(types)

    # ── Nieuwbouw ─────────────────────────────────────────────────────────────
    projecten = _query_nieuwbouw(db, stad)

    return render_template(
        "dashboard.html",
        tab=tab,
        listings=listings,
        totaal=totaal,
        filter_info=filter_info,
        page=page,
        totaal_paginas=totaal_paginas,
        leeftijd=leeftijd,
        leeftijd_opties=LEEFTIJD_OPTIES,
        projecten=projecten,
        stad=stad,
    )
