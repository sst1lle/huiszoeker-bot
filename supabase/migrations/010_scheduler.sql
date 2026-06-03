-- Migration 010: scheduler-state (scrape_runs + scrape_locks)
-- Run handmatig in Supabase SQL Editor (Project > SQL Editor > New query)
--
-- next_run_at is de single source of truth voor scheduling (UTC).
-- scrape_locks zijn TTL-locks (lock_until) → crash-safe, geen pg advisory locks.

create table if not exists scrape_runs (
  scraper_name text primary key,
  last_run_at  timestamptz,
  next_run_at  timestamptz,
  status       text,            -- 'ok' | 'failed'
  run_id       text,
  updated_at   timestamptz not null default now()
);

create table if not exists scrape_locks (
  scraper_name text primary key,
  lock_until   timestamptz not null
);
