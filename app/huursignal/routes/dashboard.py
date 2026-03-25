from flask import Blueprint, session, redirect, url_for, request, render_template

from db import get_db
from ..decorators import login_required

dash_bp = Blueprint("dash", __name__)


@dash_bp.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    db = get_db()

    pref_result = db.table("user_preferences").select("*").eq("user_id", user_id).execute()
    pref = pref_result.data[0] if pref_result.data else None

    if not pref:
        return redirect(url_for("pref.onboarding"))

    page     = request.args.get("page", 1, type=int)
    per_page = 20
    offset   = (page - 1) * per_page

    stad      = pref.get("stad", "")
    min_prijs = pref.get("min_prijs") or 0
    max_prijs = pref.get("max_prijs") or 9999
    types     = pref.get("type_woning") or []

    result = (db.table("listings")
              .select("*", count="exact")
              .eq("stad", stad)
              .eq("beschikbaar", True)
              .gte("prijs", min_prijs)
              .lte("prijs", max_prijs)
              .order("eerste_gezien", desc=True)
              .range(offset, offset + per_page - 1)
              .execute())

    raw    = result.data or []
    totaal = result.count or 0

    # Pararius heeft type_woning=None → altijd tonen
    listings = [l for l in raw
                if not (l.get("type_woning") and types and l["type_woning"] not in types)]

    totaal_paginas = max(1, (totaal + per_page - 1) // per_page)

    filter_info = f"{stad} \u00b7 \u20ac\u00a0{min_prijs}\u2013{max_prijs}/maand"
    if types:
        filter_info += " \u00b7 " + ", ".join(types)

    return render_template(
        "dashboard.html",
        listings=listings,
        totaal=totaal,
        filter_info=filter_info,
        page=page,
        totaal_paginas=totaal_paginas,
    )
