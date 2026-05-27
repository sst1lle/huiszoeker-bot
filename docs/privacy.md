# Privacy & Gegevensbescherming — Huursignal

## Welke gegevens worden opgeslagen?

| Gegeven | Tabel | Doel | Versleuteld |
|---|---|---|---|
| E-mailadres | `auth.users` (Supabase Auth) | Inloggen, wachtwoord reset | Ja (Supabase intern) |
| Naam | `user_preferences` | Personalisatie motivatiebrief, Telegram-berichten | **Ja (Fernet)** |
| Telegram chat ID | `user_preferences` | Verzenden van meldingen | **Ja (Fernet)** |
| Stad, huurrange, woningtype | `user_preferences` | Filteren van woningaanbod | Nee (niet-identificerend) |
| Motivatiebrief-inhoud | `motivation_letters` | Opgeslagen brief opnieuw inzien | **Ja (Fernet)** |
| Verstuurde meldingen (listing IDs) | `sent_notifications` | Voorkomen van dubbele meldingen | Nee (alleen UUID-referenties) |
| Woningadres, prijs, foto | `listings` | Dashboard weergave | Nee (publiek beschikbare data) |

## Waarom wordt dit opgeslagen?

- **Naam + Telegram chat ID**: nodig om gepersonaliseerde woningmeldingen via Telegram te versturen
- **Zoekvoorkeuren**: nodig om relevante woningen te filteren en te tonen
- **Motivatiebrieven**: alleen opgeslagen als de gebruiker dit expliciet aanvinkt ("Sla deze brief op")
- **Verstuurde meldingen**: bijhouden welke woningen al gemeld zijn, zodat gebruikers geen duplicaten ontvangen
- **Woningdata**: gescraped van publieke bronnen (Pararius, Kamernet) — geen persoonsgegevens

## Hoe lang wordt data bewaard?

| Gegeven | Bewaartermijn |
|---|---|
| Account & voorkeuren | Tot verwijdering door gebruiker |
| Motivatiebrieven | **90 dagen** (automatisch verwijderd via pg_cron) |
| Verstuurde meldingen | **180 dagen** (automatisch verwijderd via pg_cron) |
| Woningdata (listings) | Onbepaald (publieke data, geen persoonsgegevens) |

## Versleuteling

De volgende velden worden versleuteld opgeslagen met Fernet symmetric encryption (`cryptography` library):

- `user_preferences.naam`
- `user_preferences.telegram_chat_id`
- `motivation_letters.letter_text`

De encryptiesleutel (`ENCRYPTION_KEY`) staat in het `.env` bestand op de server en wordt nooit opgeslagen in de database of gelogged.

**Sleutel genereren:**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Hoe kan een gebruiker zijn data verwijderen?

### Zelf verwijderen via de app
1. Log in op Huursignal
2. Ga naar **Instellingen**
3. Scroll naar het gedeelte "Account verwijderen"
4. Klik op **Account permanent verwijderen** en bevestig

Dit verwijdert:
- Je account uit Supabase Auth
- Al je zoekvoorkeuren
- Al je opgeslagen motivatiebrieven
- Je meldingsgeschiedenis

De verwijdering is onmiddellijk en onomkeerbaar.

### Verzoek via e-mail
Stuur een e-mail naar de beheerder. Data wordt binnen 5 werkdagen verwijderd.

## Gegevens die NIET worden opgeslagen

- Wachtwoorden (beheerd door Supabase Auth, opgeslagen als bcrypt hash)
- LLM-prompts of -antwoorden die niet door de gebruiker zijn opgeslagen
- IP-adressen of browserdata
- Activiteitslogs per gebruiker

## Derde partijen

| Partij | Doel | Data |
|---|---|---|
| **Supabase** | Database & authenticatie | E-mail, versleutelde voorkeuren |
| **Telegram** | Meldingen sturen | Telegram chat ID (decrypted on-the-fly) |
| **Groq / LLaMA** | Motivatiebrief genereren | Ingevoerde gegevens per verzoek (niet bewaard door Huursignal tenzij opt-in) |
| **Nominatim (OSM)** | Geocodering nieuwbouw | Stadsnamen (geen persoonsgegevens) |
