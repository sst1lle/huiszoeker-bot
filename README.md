# Huursignal

Huursignal is a Dutch rental housing notification system. It scrapes rental sites once per site/city, stores listings in Supabase, and sends Telegram notifications when SQL-filtered listings match a user's profile. It also includes a multi-user Flask dashboard, admin tooling, nieuwbouw tracking, and a motivation letter generator.

## Features

- Scrapes Funda, Pararius, and Kamernet for rental listings.
- Scrapes realtime rental sites every 7 minutes; nieuwbouw scrapers run weekly.
- Runs each realtime scraper once per `(site, stad)` instead of once per user/profile.
- Uses Supabase as the central filter layer for city, price, availability, geo fields, and scheduler state.
- Sends Telegram notifications only after a successful DB claim in `sent_notifications` (idempotent, no duplicate sends after deploy/restart).
- Supports per-user city, price, woningtype, Telegram, and desired-wijk preferences.
- Geocodes listings via PDOK and stores canonical `stad`, `postcode`, `wijk`, `buurt`, `lat`, and `lng`.
- Filters parking/garage listings out of user notifications.
- Provides a Flask dashboard for listings, preferences, admin scraper toggles, and motivation letters.
- Uses Byparr for Cloudflare-protected sites (Funda and Pararius).
- Saves historical scrape snapshots as Parquet files for later analysis.

## Architecture

Three Docker services are defined in `docker-compose.yml`:

- `huiszoeker` — backend bot (`app/backend/main.py` → `pipeline.scheduler_loop`)
- `huiszoeker-web` — Flask web interface (`app/frontend/web.py`) served by Gunicorn
- `byparr` — browser-based Cloudflare bypass (patched image in `docker/byparr/`)

### Backend modules

| Module | Role |
|--------|------|
| `main.py` | Entrypoint: load scrapers, start async daemon loop |
| `pipeline.py` | `run_cycle`: validate → scrape → geocode → upsert → notify |
| `validation.py` | Stale listing HTTP checks, `scraper_config` schema checks |
| `listings_db.py` | Bulk upsert on `url`, SQL candidate queries for notifications |
| `notifications.py` | Telegram send + DB claim (`claim_sent_notification`) |
| `scrape_plan.py` | One scrape task per `(scraper, canonical stad)` |
| `scheduler/` | Supabase-backed run schedule and TTL locks |

### Backend flow

The bot runs one persistent asyncio loop (7-minute interval):

1. **Validate** stale listings in parallel (`404` → `beschikbaar=false`), batch upsert by `id`.
2. **Scrape** via scheduler: build plan from all user cities (canonical slugs), run realtime scrapers with TTL locks.
3. **Deduplicate**, **geocode** (PDOK, in-memory cache + batch flush), **Parquet snapshot**, **bulk upsert** listings (`on_conflict=url`, batches of 200).
4. **Notify**: for each user, load SQL-filtered candidates, **claim** each `(user_id, listing_id)` in the DB, send Telegram only when the claim insert succeeds.

Example scrape plan:

```text
3 scrapers x 4 cities = 12 scrape tasks
funda + utrecht
pararius + utrecht
kamernet + utrecht
...
```

### City normalization

All `listings.stad` values and SQL filters use **canonical slugs** from `app/shared/cities.py` (e.g. `'s-Gravenhage` → `den-haag`). User preferences are normalized on save (`stad_pref_opslaan`). Nieuwbouw uses `stad_nieuwbouw_city()` for free-text `city` columns.

Migration `012_listings_stad_canonical.sql` backfills legacy `listings.stad` values.

### Notification filtering

**SQL-first** candidate selection (`listings_db.get_listings_for_user`):

```sql
SELECT *
FROM listings
WHERE stad IN (:canonical_slugs)
  AND prijs BETWEEN :min_prijs AND :max_prijs
  AND beschikbaar = true
ORDER BY created_at DESC
LIMIT 1000;
```

Python only applies parking markers, woningtype (except Funda/Pararius), and wijk filters.

**Dedupe is DB-only** — no reads from `sent_notifications` for filtering:

```sql
INSERT INTO sent_notifications (user_id, listing_id)
VALUES (...)
ON CONFLICT (user_id, listing_id) DO NOTHING
RETURNING id;
```

Implemented via RPC `claim_sent_notification` / `claim_sent_notifications_batch` (migration `013`). If the insert returns a row → send Telegram; otherwise log `status=duplicate` and skip.

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

### Byparr traffic

Protected scrapers use `byparr_traffic.submit()` (queue, rate limits, circuit breaker) → `byparr_client.fetch()` (health, retries). Busy Byparr is not treated as offline.

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
- `listings` — canonical rental listings, unique by `url`; `stad` is a canonical slug
- `sent_notifications` — `UNIQUE(user_id, listing_id)`; source of truth for sent state
- `scraper_config` — enable/disable state and scraper metadata
- `scrape_runs` / `scrape_locks` — scheduler state
- `geocode_cache` — PDOK geocoding cache
- `wijken_cache` — cached CBS/PDOK wijk data
- `nieuwbouw_projects` — tracked new-build projects

Recent migrations:

- `011_listings_query_indexes.sql` — listing query indexes
- `012_listings_stad_canonical.sql` — backfill legacy `stad` to canonical slugs
- `013_claim_sent_notification.sql` — idempotent notification RPCs

Apply migrations in the Supabase SQL Editor, or use:

```bash
./scripts/run_supabase_migration.sh supabase/migrations/013_claim_sent_notification.sql
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

Optional Byparr tuning (see `docker-compose.yml` / `byparr_client.py`):

```env
BYPARR_MAX_INFLIGHT=1
BYPARR_MIN_GAP_SEC=3
BYPARR_MAX_TIMEOUT_SEC=25
BYPARR_READ_TIMEOUT=50
BYPARR_REQUEST_RETRIES=2
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

Test admin Telegram + idempotent notifications (sends one test message):

```bash
docker cp scripts/test_admin_telegram.py huiszoeker:/app/scripts/
docker exec huiszoeker python3 /app/scripts/test_admin_telegram.py
```

## Project Structure

```text
app/
  backend/
    main.py                  # bot entrypoint
    pipeline.py              # run_cycle, scrape orchestration, geocoding glue
    validation.py            # listing validation, schema checks
    listings_db.py           # bulk upsert, notification candidate queries
    notifications.py         # Telegram + DB claim dedupe
    scrape_plan.py           # one scrape task per site/city
    scheduler/               # Supabase-backed run schedule and TTL locks
    scrapers/                # Funda, Pararius, Kamernet, nieuwbouw, Byparr client
    deduplicator.py
    storage.py               # Parquet snapshots
  frontend/
    web.py                   # Flask entrypoint
    huursignal/
      routes/                # auth, dashboard, preferences, admin, motivatiebrief
      templates/
      static/
  shared/
    cities.py                # canonical city slugs (single source of truth)
    geocoder.py              # PDOK geocoding + cache
    wijken.py                # CBS/PDOK wijk lookup + cache
  db.py                      # shared Supabase client
supabase/
  schema.sql
  migrations/
docker/
  byparr/                   # patched Byparr image (no networkidle wait)
scripts/
  run_supabase_migration.sh
  test_admin_telegram.py
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
