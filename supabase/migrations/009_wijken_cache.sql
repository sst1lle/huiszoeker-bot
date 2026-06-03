-- Migration 009: wijken_cache — beschikbare CBS-wijken per stad (PDOK WFS), gecachet
-- Run handmatig in Supabase SQL Editor (Project > SQL Editor > New query)

create table if not exists wijken_cache (
  stad         text primary key,             -- stad-slug zoals in user_preferences (bv. 'den-haag')
  gemeentenaam text,                          -- opgeloste CBS-gemeentenaam (bv. '''s-Gravenhage')
  wijken       text[] not null default '{}',  -- exacte CBS-wijknamen (zoals 'Wijk 07 Scheveningen')
  updated_at   timestamptz not null default now()
);
