# Huursignal

Huursignal is a Dutch rental housing notification system. It scrapes rental sites once per site/city, stores listings in Supabase, and sends Telegram notifications when SQL-filtered listings match a user's profile. It also includes a multi-user Flask dashboard, admin tooling, nieuwbouw tracking, and a motivation letter generator.

## Features

- Scrapes Funda, Pararius, and Kamernet for rental listings.
- Scrapes realtime rental sites every 7 minutes; nieuwbouw scrapers run weekly.
- Runs each realtime scraper once per `(site, stad)` instead of once per user/profile.
- Uses Supabase as the central filter layer for city, price, availability, sent-notification state, geo fields, and scheduler state.
- Sends Telegram notifications for new matches and records them in `sent_notifications`.
- Supports per-user city, price, woningtype, Telegram, and desired-wijk preferences.
- Geocodes listings via PDOK and stores `stad`, `postcode`, `wijk`, `buurt`, `lat`, and `lng`.
- Filters parking/garage listings out of user notifications.
- Provides a Flask dashboard for listings, preferences, admin scraper toggles, and motivation letters.
- Uses Byparr for Cloudflare-protected sites (Funda and Pararius).
- Saves historical scrape snapshots as Parquet files for later analysis.

## Architecture

Three Docker services are defined in `docker-compose.yml`:

- `huiszoeker` — backend bot loop (`app/backend/main.py`)
- `huiszoeker-web` — Flask web interface (`app/frontend/web.py`) served by Gunicorn
- `byparr` — browser-based Cloudflare bypass service used by protected scrapers

### Backend Flow

The bot loop runs every 7 minutes:

1. Validate stale listings (`404` marks `beschikbaar=false`).
2. Load active user preferences.
3. Build a scrape plan from all user cities:
   - one task per `(scraper, stad)`
   - no per-user scrape loops
   - no per-profile duplicate scrapes
4. Run realtime scrapers through the scheduler gate and TTL locks.
5. Deduplicate, geocode, save a Parquet snapshot, and upsert listings by unique `url`.
6. Query listings per user using SQL filters.
7. Apply only lightweight Python checks (sent state, parking markers, wijk/type checks) and send Telegram notifications.

Example scrape plan:

```text
3 scrapers x 4 cities = 12 scrape tasks
funda + utrecht
pararius + utrecht
kamernet + utrecht
...
```

### Notification Filtering

User notification queries are SQL-first:

```sql
SELECT *
FROM listings
WHERE stad = ANY(:user_steden)
  AND prijs BETWEEN :min_prijs AND :max_prijs
  AND beschikbaar = true
ORDER BY created_at DESC
LIMIT 1000;
```

The implementation uses Supabase/PostgREST filters (`.in_`, `.gte`, `.lte`, `.eq`) in `get_listings_for_user()`.

### Scheduler

Scheduler state is stored in Supabase:

- `scrape_runs` — `last_run_at`, `next_run_at`, status, run ID
- `scrape_locks` — TTL locks to prevent duplicate/overlapping scraper runs

Realtime scrapers:

- interval: 7 minutes
- failure backoff: 30 minutes
- lock TTL: 20 minutes

Nieuwbouw scrapers:

- interval: weekly
- anchor: Monday 05:00 Europe/Amsterdam
- lock TTL: 6 hours

## Scrapers

Scrapers live in `app/backend/scrapers/` and extend `BaseScraper`.

Current realtime scrapers:

- `funda`
- `pararius`
- `kamernet`

Current nieuwbouw scrapers:

- `nieuwbouw_nederland`
- `nieuwbouw_nl`

Important behavior:

- Funda and Pararius do not use price filters in their URLs; price filtering happens in SQL per user.
- Kamernet still uses price/type URL filters because they are cheap and useful on that site.
- Parking/garage listings are filtered before notification using URL/type/address markers.
- Scrapers are auto-discovered at startup and registered in `scraper_config`.

## Database

The canonical schema is in `supabase/schema.sql`; incremental changes are in `supabase/migrations/`.

Core tables:

- `user_preferences` — per-user criteria and encrypted personal/Telegram fields
- `listings` — canonical rental listings, unique by `url`
- `sent_notifications` — one row per sent user/listing notification
- `scraper_config` — enable/disable state and scraper metadata
- `scrape_runs` / `scrape_locks` — scheduler state
- `geocode_cache` — PDOK geocoding cache
- `wijken_cache` — cached CBS/PDOK wijk data
- `nieuwbouw_projects` — tracked new-build projects

Useful listing indexes:

- `idx_listings_stad`
- `idx_listings_price`
- `idx_listings_active`
- `idx_listings_filter (stad, prijs, beschikbaar)`
- `idx_listings_wijk`

Apply migrations manually in the Supabase SQL Editor, or use:

```bash
./scripts/run_supabase_migration.sh supabase/migrations/011_listings_query_indexes.sql
```

That script requires `SUPABASE_DB_PASSWORD` in `.env`.

## Environment Variables

```env
TELEGRAM_TOKEN=          # Bot token from @BotFather
ADMIN_CHAT_ID=           # Admin Telegram chat ID for warnings
SECRET_KEY=              # Flask session secret
SUPABASE_URL=            # Supabase project URL
SUPABASE_KEY=            # service_role key for server-side operations
SUPABASE_ANON_KEY=       # anon key for frontend/auth flows if needed
SUPABASE_DB_PASSWORD=    # optional; only needed for scripts/run_supabase_migration.sh
ADMIN_EMAIL=             # Admin user email
ADMIN_PASSWORD=          # Optional bootstrap/admin credential
DATA_DIR=                # Base path for datalake mount; default /mnt/ssd
ENCRYPTION_KEY=          # Fernet key for encrypted PII fields
GROQ_API_KEY=            # Required for motivation letter generation
MAX_PAGES=3              # Max pages per realtime scraper
SITE_URL=                # Public web URL if needed
```

## Run

```bash
docker compose up --build -d
```

Web interface:

```text
http://localhost:5000
```

Rebuild one service:

```bash
docker compose build huiszoeker && docker compose up -d huiszoeker
docker compose build webinterface && docker compose up -d webinterface
```

Inspect logs:

```bash
docker logs -f huiszoeker
docker logs -f byparr
docker logs -f huiszoeker-web
```

## Project Structure

```text
app/
  backend/
    main.py                  # bot loop: scrape, geocode, upsert, notify
    scrape_plan.py           # one scrape task per site/city
    scheduler/               # Supabase-backed run schedule and TTL locks
    scrapers/                # Funda, Pararius, Kamernet, nieuwbouw scrapers
    deduplicator.py
    storage.py               # Parquet snapshots
  frontend/
    web.py                   # Flask entrypoint
    huursignal/
      routes/                # auth, dashboard, preferences, admin, motivatiebrief
      templates/
      static/
  shared/
    cities.py                # city normalization
    geocoder.py              # PDOK geocoding + cache
    wijken.py                # CBS/PDOK wijk lookup + cache
  db.py                      # shared Supabase client
supabase/
  schema.sql
  migrations/
scripts/
  run_supabase_migration.sh
  migrate_json_to_parquet.py
  migrate_json_to_supabase.py
data/
  datalake/
```

## Adding a Scraper

1. Create `app/backend/scrapers/yoursite.py`.
2. Define a `BaseScraper` subclass with a unique `name`.
3. Implement `_scrape_impl(stad, min_prijs, max_prijs, types)`.
4. Set class attributes such as `uses_types`, `uses_price_filter`, `flaresolverr_only`, and `category`.
5. Restart the bot; it auto-discovers and registers the scraper in `scraper_config`.
