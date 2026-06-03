-- Migration 007: gewenste_wijken — wijken/buurten-filter per gebruiker
-- Vervangt de radius-filter (zie 006). Run handmatig in Supabase SQL Editor.
--
-- Leeg array ('{}') = geen wijk-filter → notificaties voor alle wijken binnen
-- de gewenste stad(en). Voorbeeld gevulde waarde: ARRAY['Centrum','Laakkwartier'].

ALTER TABLE user_preferences
  ADD COLUMN IF NOT EXISTS gewenste_wijken TEXT[] DEFAULT '{}';
