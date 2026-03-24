# scripts/test_kamernet.py
# Tijdelijk testscript — stuurt Kamernet resultaten alleen naar Sam's Telegram
# Raakt main.py of bestaande gebruikers NIET aan

import sys
import os
import requests

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'app'))
from scrapers.kamernet import scrape_kamernet

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TEST_CHAT_ID = "1497723745"

def stuur_telegram(chat_id: str, tekst: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": chat_id,
        "text": tekst,
        "parse_mode": "HTML"
    })

def main():
    print("🔍 Kamernet test — Den Haag, €0-1200, appartement + studio")
    listings = scrape_kamernet(
        stad="den-haag",
        min_prijs=0,
        max_prijs=1200,
        types=["appartement", "studio"]
    )

    print(f"✅ {len(listings)} woningen gevonden")

    if not listings:
        stuur_telegram(TEST_CHAT_ID, "⚠️ Kamernet test: 0 woningen gevonden voor Den Haag.")
        return

    # Stuur max 5 ter test zodat je niet gespammd wordt
    for w in listings[:5]:
        bericht = (
            f"🏠 <b>Kamernet test</b>\n\n"
            f"📍 {w.get('adres') or 'onbekend'}, {w.get('stad')}\n"
            f"💶 €{w.get('prijs') or '?'}/maand\n"
            f"📐 {w.get('oppervlakte') or '?'}m²\n"
            f"🏷️ {w.get('type_woning') or '?'}\n\n"
            f"🔗 {w.get('url')}"
        )
        stuur_telegram(TEST_CHAT_ID, bericht)
        print(f"  → Verstuurd: {w.get('url')}")

    stuur_telegram(TEST_CHAT_ID, f"✅ Kamernet test klaar — {len(listings)} woningen gevonden, 5 verstuurd.")

if __name__ == "__main__":
    main()
