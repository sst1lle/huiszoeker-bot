import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, session, redirect, url_for, request, render_template

from db import get_db
from shared.cities import stad_ilike_zoekterm, stad_slugs_uit_pref
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


def _query_nieuwbouw(db, stad_raw: str) -> list[dict]:
    """
    Zoek actieve nieuwbouwprojecten op canonical stad-slugs uit voorkeur.
    Verbergt projecten met uitverkochte/verhuurd/optie/gesloten status.
    """
    slugs = stad_slugs_uit_pref(stad_raw)
    if not slugs:
        return []

    seen_ids: set[str] = set()
    projecten: list[dict] = []

    for slug in slugs:
        stad_search = stad_ilike_zoekterm(slug)
        rows = (
            db.table("nieuwbouw_projects")
            .select("*")
            .ilike("city", f"%{stad_search}%")
            .eq("is_active", True)
            .order("scraped_at", desc=True)
            .execute()
            .data
            or []
        )
        for p in rows:
            pid = p.get("id")
            if pid and pid in seen_ids:
                continue
            if pid:
                seen_ids.add(pid)
            projecten.append(p)

    zichtbaar = [p for p in projecten if p.get("status") not in _HIDDEN_STATUSES]
    verborgen = len(projecten) - len(zichtbaar)

    logger.info(
        f"[dashboard] nieuwbouw slugs={','.join(slugs)} → "
        f"{len(projecten)} actief, {verborgen} verborgen op status → {len(zichtbaar)} getoond",
        flush=True,
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
            f"[dashboard] 0 nieuwbouw voor slugs={slugs}. "
            f"Steden in DB (steekproef): {[r.get('city') for r in sample]}",
            flush=True,
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
    steden = stad_slugs_uit_pref(stad)
    if not steden:
        raw, totaal = [], 0
    else:
        query = (db.table("listings")
                   .select("*", count="exact")
                   .in_("stad", steden)
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
