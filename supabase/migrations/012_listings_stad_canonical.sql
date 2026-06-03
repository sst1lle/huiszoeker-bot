-- Backfill legacy listings.stad naar canonical slugs (shared/cities.py)
UPDATE listings SET stad = 'den-haag' WHERE stad IN (
  '''s-Gravenhage', 's-Gravenhage', 's-gravenhage', 'Den Haag', 'den haag', 'DEN HAAG'
);
UPDATE listings SET stad = 'utrecht' WHERE stad IN ('Utrecht', 'UTRECHT');
UPDATE listings SET stad = 'amsterdam' WHERE stad IN ('Amsterdam', 'AMSTERDAM');
UPDATE listings SET stad = 'rotterdam' WHERE stad IN ('Rotterdam', 'ROTTERDAM');
