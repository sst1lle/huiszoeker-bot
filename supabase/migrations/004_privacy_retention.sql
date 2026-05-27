-- Migration 004: data retention via pg_cron
-- Run in Supabase SQL Editor (Project > SQL Editor > New query)
--
-- Requires pg_cron extension. Enable via:
--   Supabase Dashboard > Database > Extensions > pg_cron → Enable
--
-- Verify pg_cron is active:
--   SELECT * FROM pg_extension WHERE extname = 'pg_cron';

-- Delete motivation_letters older than 90 days (runs daily at 03:00 UTC)
SELECT cron.schedule(
  'delete-old-motivation-letters',
  '0 3 * * *',
  $$DELETE FROM motivation_letters WHERE created_at < NOW() - INTERVAL '90 days';$$
);

-- Delete sent_notifications older than 180 days (runs weekly on Sunday at 03:30 UTC)
SELECT cron.schedule(
  'delete-old-sent-notifications',
  '30 3 * * 0',
  $$DELETE FROM sent_notifications WHERE sent_at < NOW() - INTERVAL '180 days';$$
);

-- Verify scheduled jobs:
--   SELECT * FROM cron.job;
