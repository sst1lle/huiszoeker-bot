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
  name       TEXT PRIMARY KEY,
  enabled    BOOLEAN DEFAULT TRUE,
  last_run   TIMESTAMPTZ,          -- tijdstip laatste succesvolle scrape-ronde
  last_count INT,                  -- aantal listings gevonden in laatste ronde
  created_at TIMESTAMPTZ DEFAULT NOW()
);
-- Geen RLS-policies nodig: service_role bypasses RLS; authenticated users hebben geen toegang
ALTER TABLE scraper_config ENABLE ROW LEVEL SECURITY;

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

-- Nieuwbouwprojecten (gevuld door een aparte scraper)
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
  url TEXT UNIQUE NOT NULL,
  scraped_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE nieuwbouw_projects ENABLE ROW LEVEL SECURITY;
CREATE POLICY "nieuwbouw leesbaar voor ingelogden"
  ON nieuwbouw_projects FOR SELECT
  TO authenticated
  USING (true);

CREATE INDEX idx_nieuwbouw_city ON nieuwbouw_projects(city);

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
