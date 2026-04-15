import os
from flask import Blueprint, session, request, render_template

from db import get_db
from ..decorators import login_required

motivatiebrief_bp = Blueprint("motivatiebrief", __name__)

_SYSTEEM_PROMPT = (
    "Je bent een assistent die motivatiebrieven schrijft voor woningzoekers. "
    "Schrijf altijd in professioneel Nederlands. De brief mag maximaal 200 woorden zijn. "
    "Gebruik een vriendelijke maar formele toon. "
    "Schrijf de brief direct, zonder uitleg of inleiding vooraf."
)


def _get_naam():
    try:
        db = get_db()
        result = db.table("user_preferences").select("naam").eq("user_id", session["user_id"]).execute()
        if result.data:
            return result.data[0].get("naam") or ""
    except Exception:
        pass
    return ""


@motivatiebrief_bp.route("/motivatiebrief", methods=["GET", "POST"])
@login_required
def motivatiebrief():
    naam = _get_naam()

    if request.method == "GET":
        return render_template("motivatiebrief.html", naam=naam)

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return render_template(
            "motivatiebrief.html",
            naam=naam,
            form=request.form,
            error=(
                "Geen GROQ_API_KEY gevonden. "
                "Voeg GROQ_API_KEY=your-key-here toe aan je .env bestand en herstart de container."
            ),
        )

    f = request.form
    onderdelen = []
    if f.get("naam"):
        onderdelen.append(f"Naam: {f['naam']}")
    if f.get("woonsituatie"):
        onderdelen.append(f"Huidige woonsituatie: {f['woonsituatie']}")
    if f.get("reden"):
        onderdelen.append(f"Reden voor verhuizing: {f['reden']}")
    if f.get("bijzonderheden"):
        onderdelen.append(f"Bijzonderheden: {f['bijzonderheden']}")
    if f.get("woning"):
        onderdelen.append(f"Specifieke woning: {f['woning']}")

    gebruiker_prompt = (
        "Schrijf een motivatiebrief voor een huurwoning op basis van de volgende gegevens:\n\n"
        + "\n".join(onderdelen)
    )

    try:
        from groq import Groq
        client = Groq(api_key=api_key, timeout=30.0)
        response = client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=[
                {"role": "system", "content": _SYSTEEM_PROMPT},
                {"role": "user", "content": gebruiker_prompt},
            ],
            max_tokens=400,
        )
        brief = response.choices[0].message.content.strip()
        return render_template("motivatiebrief.html", naam=naam, form=f, brief=brief)

    except Exception as e:
        err_msg = str(e)
        if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
            err_msg = "De aanvraag heeft te lang geduurd (timeout). Probeer het opnieuw."
        return render_template("motivatiebrief.html", naam=naam, form=f, error=err_msg)
