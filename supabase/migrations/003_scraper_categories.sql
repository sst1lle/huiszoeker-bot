-- Migration 003: scraper category grouping + status tracking
-- Run manually in Supabase SQL Editor (Project > SQL Editor > New query)

ALTER TABLE scraper_config ADD COLUMN IF NOT EXISTS category      TEXT DEFAULT 'huurwoningen';
ALTER TABLE scraper_config ADD COLUMN IF NOT EXISTS status        TEXT DEFAULT 'onbekend';
ALTER TABLE scraper_config ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Categoriseer bestaande scrapers
UPDATE scraper_config
SET category = 'nieuwbouw'
WHERE name IN ('nieuwbouw_nederland', 'nieuwbouw_nl');

UPDATE scraper_config
SET category = 'huurwoningen'
WHERE name IN ('pararius', 'kamernet', 'funda')
   OR category IS NULL;

-- Verwijder verouderde aggregatie-entry (vervangen door aparte scrapers)
DELETE FROM scraper_config WHERE name = 'nieuwbouw';
