from flask import Blueprint, session, jsonify, render_template

from db import get_db
# PRIVACY-FIX: decrypt letter_text before rendering (stored encrypted)
from crypto import safe_decrypt
from ..decorators import login_required

mijn_brieven_bp = Blueprint("mijn_brieven", __name__)


@mijn_brieven_bp.route("/mijn-brieven")
@login_required
def mijn_brieven():
    db = get_db()
    brieven = (
        db.table("motivation_letters")
        .select("*")
        .eq("user_id", session["user_id"])
        .order("created_at", desc=True)
        .execute()
        .data or []
    )
    # PRIVACY-FIX: decrypt letter_text for each row before passing to template
    for b in brieven:
        b["letter_text"] = safe_decrypt(b.get("letter_text"))
    return render_template("mijn_brieven.html", brieven=brieven)


@mijn_brieven_bp.route("/api/mijn-brieven/<brief_id>", methods=["DELETE"])
@login_required
def verwijder_brief(brief_id):
    db = get_db()
    db.table("motivation_letters").delete().eq("id", brief_id).eq("user_id", session["user_id"]).execute()
    return jsonify({"ok": True})
