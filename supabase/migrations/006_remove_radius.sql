-- Migration 006: radius-filter verwijderd (vervangen door wijken-filter)
-- Run handmatig in Supabase SQL Editor (Project > SQL Editor > New query)

ALTER TABLE user_preferences DROP COLUMN IF EXISTS radius_km;
