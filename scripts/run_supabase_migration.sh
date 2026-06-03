#!/usr/bin/env bash
# Voer één of meer SQL-migraties uit tegen Supabase Postgres.
# Vereist in .env: SUPABASE_DB_PASSWORD (Database password uit Supabase Dashboard → Settings → Database)
#
# Usage:
#   ./scripts/run_supabase_migration.sh supabase/migrations/011_listings_query_indexes.sql
#   ./scripts/run_supabase_migration.sh supabase/migrations/*.sql

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${SUPABASE_URL:-}" ]]; then
  echo "SUPABASE_URL ontbreekt in .env" >&2
  exit 1
fi

if [[ -z "${SUPABASE_DB_PASSWORD:-}" ]]; then
  echo "SUPABASE_DB_PASSWORD ontbreekt in .env" >&2
  echo "Haal het database-wachtwoord op: Supabase Dashboard → Project Settings → Database → Database password" >&2
  exit 1
fi

REF="${SUPABASE_URL#https://}"
REF="${REF%%.supabase.co*}"
HOST="db.${REF}.supabase.co"

if [[ $# -lt 1 ]]; then
  echo "Geef minstens één .sql bestand op." >&2
  exit 1
fi

export PGPASSWORD="$SUPABASE_DB_PASSWORD"
for f in "$@"; do
  echo "→ $f"
  psql "postgresql://postgres@${HOST}:5432/postgres" -v ON_ERROR_STOP=1 -f "$f"
done
echo "Klaar."
