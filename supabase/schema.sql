-- Huursignal — Supabase schema
-- Voer dit uit in de Supabase SQL editor (Project > SQL Editor > New query)
-- Gebruikers worden beheerd via Supabase Auth (ingebouwd)
-- Onderstaande tabellen zijn applicatiedata

-- Zoekvoorkeuren per gebruiker
CREATE TABLE user_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  naam TEXT,
  telegram_chat_id TEXT,
  stad TEXT NOT NULL,
  min_prijs INT,
  max_prijs INT,
  type_woning TEXT[] DEFAULT '{}', -- array: ['kamer','appartement','studio','anti-kraak','studentenwoning','gemeubileerd']
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Gescrapete woningaanbiedingen
CREATE TABLE listings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,              -- 'pararius' | 'kamernet'
  external_id TEXT,                  -- unieke ID op de bronsite indien beschikbaar
  url TEXT UNIQUE NOT NULL,
  adres TEXT,
  stad TEXT,
  prijs INT,
  oppervlakte INT,                   -- in m²
  type_woning TEXT,                  -- kamer / appartement / studio / etc.
  foto_url TEXT,                     -- eerste foto URL
  beschikbaar BOOLEAN DEFAULT TRUE,  -- false = niet meer op de site
  eerste_gezien TIMESTAMPTZ DEFAULT NOW(),
  laatst_gevalideerd TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Bijhouden welke listings al naar welke gebruiker gestuurd zijn (Telegram)
CREATE TABLE sent_notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  listing_id UUID REFERENCES listings(id) ON DELETE CASCADE,
  sent_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, listing_id)
);

-- Aan/uit-schakelaar per scraper (beheerd via /admin/scrapers)
CREATE TABLE scraper_config (
  name          TEXT PRIMARY KEY,
  enabled       BOOLEAN DEFAULT TRUE,
  category      TEXT DEFAULT 'huurwoningen',  -- 'huurwoningen' | 'nieuwbouw'
  last_run      TIMESTAMPTZ,
  last_count    INT,
  status        TEXT DEFAULT 'onbekend',       -- 'actief' | 'fout' | 'onbekend'
  error_message TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);
-- Geen RLS-policies nodig: service_role bypasses RLS; authenticated users hebben geen toegang
ALTER TABLE scraper_config ENABLE ROW LEVEL SECURITY;

-- Migratie (uitvoeren in Supabase SQL editor als tabel al bestaat):
-- ALTER TABLE scraper_config ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'huurwoningen';
-- ALTER TABLE scraper_config ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'onbekend';
-- ALTER TABLE scraper_config ADD COLUMN IF NOT EXISTS error_message TEXT;
-- UPDATE scraper_config SET category = 'nieuwbouw' WHERE name IN ('nieuwbouw_nederland', 'nieuwbouw_nl');
-- DELETE FROM scraper_config WHERE name = 'nieuwbouw';

-- Gegenereerde motivatiebrieven per gebruiker
CREATE TABLE motivation_letters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  listing_url TEXT,
  listing_title TEXT,
  letter_text TEXT NOT NULL,
  system_prompt_used TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE motivation_letters ENABLE ROW LEVEL SECURITY;
CREATE POLICY "eigen brieven"
  ON motivation_letters FOR ALL
  TO authenticated
  USING (auth.uid() = user_id);

-- Nieuwbouwprojecten (gevuld door een aparte scraper, wekelijks via APScheduler)
-- type is altijd lowercase: 'huur' of 'koop'
-- city bevat de naam zoals die op de bronsite staat, bijv. "Den Haag"
-- source: 'nieuwbouw-nederland.nl' of 'nieuwbouw.nl'
-- latitude/longitude: optioneel, voor toekomstige radius-filtering
CREATE TABLE nieuwbouw_projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  developer TEXT,
  city TEXT,
  type TEXT CHECK (type IN ('huur', 'koop')),
  price_min INT,
  price_max INT,
  units INT,
  expected_date TEXT,
  source TEXT,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  url TEXT UNIQUE NOT NULL,
  scraped_at TIMESTAMPTZ DEFAULT NOW(),
  -- lifecycle & status (migratie: zie ALTER TABLE hieronder)
  status TEXT DEFAULT 'available',
  status_text TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  first_seen_at TIMESTAMPTZ DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ DEFAULT NOW(),
  consecutive_missing INT DEFAULT 0
);

ALTER TABLE nieuwbouw_projects ENABLE ROW LEVEL SECURITY;
CREATE POLICY "nieuwbouw leesbaar voor ingelogden"
  ON nieuwbouw_projects FOR SELECT
  TO authenticated
  USING (true);

CREATE INDEX idx_nieuwbouw_city     ON nieuwbouw_projects(city);
CREATE INDEX idx_nieuwbouw_is_active ON nieuwbouw_projects(is_active);
CREATE INDEX idx_nieuwbouw_status    ON nieuwbouw_projects(status);

-- ============================================================
-- Migratie: voer uit in Supabase SQL editor als tabel al bestaat
-- ============================================================
-- ALTER TABLE nieuwbouw_projects ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'available';
-- ALTER TABLE nieuwbouw_projects ADD COLUMN IF NOT EXISTS status_text TEXT;
-- ALTER TABLE nieuwbouw_projects ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
-- ALTER TABLE nieuwbouw_projects ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ DEFAULT NOW();
-- ALTER TABLE nieuwbouw_projects ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ DEFAULT NOW();
-- ALTER TABLE nieuwbouw_projects ADD COLUMN IF NOT EXISTS consecutive_missing INT DEFAULT 0;
-- CREATE INDEX IF NOT EXISTS idx_nieuwbouw_is_active ON nieuwbouw_projects(is_active);
-- CREATE INDEX IF NOT EXISTS idx_nieuwbouw_status ON nieuwbouw_projects(status);

-- Index voor snelle lookups
CREATE INDEX idx_listings_stad ON listings(stad);
CREATE INDEX idx_listings_beschikbaar ON listings(beschikbaar);
CREATE INDEX idx_listings_bron ON listings(source);
CREATE INDEX idx_user_prefs_user ON user_preferences(user_id);

-- ============================================================
-- Row Level Security (RLS)
-- ============================================================

-- Listings zijn leesbaar voor alle ingelogde gebruikers
ALTER TABLE listings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "listings leesbaar voor ingelogden"
  ON listings FOR SELECT
  TO authenticated
  USING (true);

-- Preferences alleen voor eigen gebruiker
ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
CREATE POLICY "eigen preferences lezen"
  ON user_preferences FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);
CREATE POLICY "eigen preferences aanpassen"
  ON user_preferences FOR ALL
  TO authenticated
  USING (auth.uid() = user_id);

-- Sent notifications alleen voor eigen gebruiker
ALTER TABLE sent_notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY "eigen notificaties"
  ON sent_notifications FOR ALL
  TO authenticated
  USING (auth.uid() = user_id);
