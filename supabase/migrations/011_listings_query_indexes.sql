-- Migration 011: indexes voor SQL-gefilterde user/listing queries
-- Run in Supabase SQL Editor

CREATE INDEX IF NOT EXISTS idx_listings_stad ON listings(stad);
CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(prijs);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(beschikbaar);

CREATE INDEX IF NOT EXISTS idx_listings_filter
  ON listings (stad, prijs, beschikbaar);
