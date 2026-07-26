#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
env_file="${ENV_FILE:-$project_dir/.env}"
backup_file="${1:-}"

if [[ -z "$backup_file" || ! -f "$backup_file" ]]; then
  echo "Usage: $0 /absolute/path/to/backup.dump" >&2
  exit 2
fi
if [[ ! -f "$env_file" ]]; then
  echo "Environment file not found: $env_file" >&2
  exit 2
fi
for command_name in psql pg_restore; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 2
  fi
done

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

database_url="${BACKUP_DATABASE_URL:-${DATABASE_URL_SYNC:-}}"
if [[ -z "$database_url" ]]; then
  echo "BACKUP_DATABASE_URL or DATABASE_URL_SYNC is required" >&2
  exit 2
fi
database_url="${database_url/postgresql+psycopg:/postgresql:}"
database_url="${database_url/postgresql+asyncpg:/postgresql:}"
database_url="${database_url/host.docker.internal/127.0.0.1}"
database_base="${database_url%/*}"
verify_database="atlas_restore_check_$(date -u +%Y%m%d%H%M%S)_$$"
verify_url="$database_base/$verify_database"

cleanup() {
  psql "$database_url" -v ON_ERROR_STOP=1 -q -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$verify_database' AND pid <> pg_backend_pid();" \
    >/dev/null 2>&1 || true
  psql "$database_url" -v ON_ERROR_STOP=1 -q -c \
    "DROP DATABASE IF EXISTS \"$verify_database\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

pg_restore --list "$backup_file" >/dev/null
psql "$database_url" -v ON_ERROR_STOP=1 -q -c \
  "CREATE DATABASE \"$verify_database\";" >/dev/null
pg_restore \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  --dbname="$verify_url" \
  "$backup_file"

table_count="$(
  psql "$verify_url" -v ON_ERROR_STOP=1 -Atq -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';"
)"
schema_version="$(
  psql "$verify_url" -v ON_ERROR_STOP=1 -Atq -c \
    "SELECT version_num FROM alembic_version LIMIT 1;"
)"
if [[ "$table_count" -lt 10 || -z "$schema_version" ]]; then
  echo "Restore verification failed: incomplete schema" >&2
  exit 1
fi

echo "Restore verification passed: tables=$table_count schema=$schema_version"
