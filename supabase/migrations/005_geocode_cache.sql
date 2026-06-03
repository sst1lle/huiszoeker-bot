-- Migration 005: geocode_cache — cache voor PDOK-geocoding van adressen
-- Run handmatig in Supabase SQL Editor (Project > SQL Editor > New query)

create table if not exists geocode_cache (
  cache_key   text primary key,                -- genormaliseerd adres, of "postcode huisnummer" indien afleidbaar; voorkomt dubbele PDOK-calls
  query       text not null,                   -- origineel opgevraagd adres (inspectie/debug)
  found       boolean not null default false,  -- ook misses cachen → niet-gevonden adressen worden niet telkens opnieuw opgezocht
  straat      text,
  huisnummer  text,
  postcode    text,
  wijk        text,
  buurt       text,
  stad        text,
  lat         double precision,
  lng         double precision,
  created_at  timestamptz not null default now()
);

-- Snel opvragen/dedupliceren op fysiek adres (postcode + huisnummer)
create index if not exists geocode_cache_postcode_huisnummer_idx
  on geocode_cache (postcode, huisnummer);
