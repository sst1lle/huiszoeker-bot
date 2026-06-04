-- Backfill ontbrekende eerste_gezien / created_at (o.a. legacy upserts zonder timestamp)
UPDATE listings
SET
  eerste_gezien = COALESCE(eerste_gezien, laatst_gevalideerd, NOW()),
  created_at    = COALESCE(created_at, eerste_gezien, laatst_gevalideerd, NOW())
WHERE eerste_gezien IS NULL OR created_at IS NULL;
