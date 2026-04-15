# Huursignal

A Dutch rental housing notification bot. Scrapes Pararius, Kamernet, and Funda every 15 minutes and sends Telegram messages when new listings match a user's criteria. Includes a multi-user web dashboard for managing preferences and browsing listings.

## Features

- Scrapes Pararius, Kamernet, and Funda for rental listings
- Sends Telegram notifications for new matches per user
- Web dashboard with listing cards, filtering, and pagination
- Multi-user: each user sets their own city, price range, housing types, and search radius
- Admin panel to manage users and toggle scrapers on/off
- Cloudflare bypass via FlareSolverr (required for Pararius and Funda)
- Historical snapshots stored as Parquet files (queryable with DuckDB)
- Listing availability validated every 6 hours (404 → marked unavailable)

## Tech Stack

| Layer | Technology |
|---|---|
| Bot loop | Python 3.11 |
| Web app | Flask + Gunicorn |
| Database & Auth | Supabase (PostgreSQL + Row Level Security) |
| Telegram | python-telegram-bot |
| Scraping | requests + BeautifulSoup4 |
| Cloudflare bypass | FlareSolverr |
| Data lake | Parquet via pandas + PyArrow |
| Deployment | Docker Compose |

## Architecture

Two processes share a single Docker image:

**`backend/main.py`** — runs every 15 minutes:
1. Validates existing listings (HEAD request → 404 = mark unavailable)
2. Scrapes Pararius, Kamernet, and Funda for each unique `stad + prijs + radius` combination across all users
3. Upserts listings to Supabase and saves a Parquet snapshot
4. Sends Telegram notifications for new matches, recording each in `sent_notifications`

**`frontend/web.py`** — Flask app served by Gunicorn:
- Auth via Supabase (`sign_in_with_password`, `sign_up`)
- Dashboard with listing cards filtered to the user's preferences
- Onboarding and settings for search criteria + Telegram setup
- Admin panel (identified by `ADMIN_EMAIL` env var)

**Scrapers** (`backend/scrapers/`) extend `BaseScraper` and are auto-discovered — dropping a new file in the directory is enough to add a scraper.

## Database

Four tables in Supabase (schema in `supabase/schema.sql`):

- `user_preferences` — per-user search criteria + Telegram chat ID
- `listings` — scraped listings with availability tracking
- `sent_notifications` — which listings have been sent to which users (prevents duplicates)
- `scraper_config` — enabled/disabled state per scraper, updated after each run

Apply the schema manually via the Supabase SQL Editor.

## Setup

### Environment variables (`.env`)

```env
TELEGRAM_TOKEN=        # Bot token from @BotFather
ADMIN_CHAT_ID=         # Your Telegram chat ID (receives error warnings)
SECRET_KEY=            # Flask session secret (any random string)
SUPABASE_URL=          # Project URL from Supabase dashboard
SUPABASE_KEY=          # service_role key (bypasses RLS for server-side ops)
ADMIN_EMAIL=           # Email of the admin user
DATA_DIR=              # Base path for Parquet datalake (default: /mnt/ssd)
```

### Run

```bash
docker compose up --build
```

Web interface available at `http://localhost:5000`.

### Rebuild only one service

```bash
docker compose up --build huiszoeker     # bot only
docker compose up --build webinterface   # web only
```

## Project Structure

```
app/
  backend/          # bot loop + scrapers
    main.py
    scrapers/       # pararius.py, kamernet.py, funda.py, base.py
    deduplicator.py
    storage.py
  frontend/         # Flask web app
    web.py
    huursignal/     # blueprints, templates, static assets
  db.py             # shared Supabase client
  requirements.txt
supabase/
  schema.sql        # run manually in Supabase SQL Editor
scripts/
  migrate_json_to_parquet.py   # one-time migration from legacy JSON
  migrate_json_to_supabase.py  # one-time user migration
data/
  datalake/         # Parquet snapshots (mounted from NVMe on Pi)
```

## Adding a Scraper

1. Create `app/backend/scrapers/yoursite.py`
2. Define a class that extends `BaseScraper` and implements `scrape()`
3. Restart the bot — it auto-discovers and registers the scraper in `scraper_config`
