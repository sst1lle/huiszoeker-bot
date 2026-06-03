-- Migration 008: geo-velden op listings (PDOK-geocoding t.b.v. wijken-filter)
-- Run handmatig in Supabase SQL Editor (Project > SQL Editor > New query)

ALTER TABLE listings
  ADD COLUMN IF NOT EXISTS postcode TEXT,
  ADD COLUMN IF NOT EXISTS wijk     TEXT,
  ADD COLUMN IF NOT EXISTS buurt    TEXT,
  ADD COLUMN IF NOT EXISTS lat      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS lng      DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_listings_wijk ON listings(wijk);
