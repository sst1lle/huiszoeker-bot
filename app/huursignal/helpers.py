import os
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
