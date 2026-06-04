import os
from datetime import datetime, timezone
import requests as req

WONING_TYPES = ["kamer", "appartement", "studio", "anti-kraak", "studentenwoning", "gemeubileerd"]


def get_bot_username() -> str | None:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        return None
    try:
        r = req.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        if r.ok:
            return r.json().get("result", {}).get("username")
    except Exception:
        pass
    return None


def fmt_prijs(p):
    if not p:
        return "?"
    return "\u20ac\u00a0" + f"{p:,}".replace(",", ".")


_MAANDEN_KORT = {
    1: "jan", 2: "feb", 3: "mrt", 4: "apr", 5: "mei", 6: "jun",
    7: "jul", 8: "aug", 9: "sep", 10: "okt", 11: "nov", 12: "dec",
}


def _parse_ts(ts):
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        dt = ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def listing_eerste_gezien_ts(listing: dict) -> str | None:
    """Timestamp voor 'Online sinds' — fallback als eerste_gezien ontbreekt in DB."""
    return (
        listing.get("eerste_gezien")
        or listing.get("created_at")
        or listing.get("laatst_gevalideerd")
    )


def fmt_datum_kort(ts) -> str:
    """Geeft datum terug als '3 apr' (Nederlandse korte notatie)."""
    if not ts:
        return ""
    try:
        dt = _parse_ts(ts)
        return f"{dt.day} {_MAANDEN_KORT[dt.month]}"
    except Exception:
        return ""


def listing_leeftijd(ts) -> dict:
    """
    Geeft leeftijdslabel, CSS-klasse en emoji terug op basis van eerste_gezien timestamp.
    Klassen: age-new (< 3d, groen), age-recent (3-14d, oranje), age-old (> 14d, rood).
    """
    if not ts:
        return {"label": "onbekend", "klasse": "age-old", "emoji": "🔴"}
    try:
        dt = _parse_ts(ts)
        uren = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if uren < 1:
            return {"label": "< 1u geleden", "klasse": "age-new", "emoji": "🟢"}
        if uren < 24:
            return {"label": f"{int(uren)}u geleden", "klasse": "age-new", "emoji": "🟢"}
        dagen = int(uren / 24)
        if dagen == 1:
            label = "1 dag geleden"
        else:
            label = f"{dagen} dagen geleden"
        if dagen < 3:
            return {"label": label, "klasse": "age-new", "emoji": "🟢"}
        if dagen <= 14:
            return {"label": label, "klasse": "age-recent", "emoji": "🟠"}
        return {"label": label, "klasse": "age-old", "emoji": "🔴"}
    except Exception:
        return {"label": "onbekend", "klasse": "age-old", "emoji": "🔴"}
