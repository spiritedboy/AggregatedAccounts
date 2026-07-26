#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
env_file="${ENV_FILE:-$project_dir/.env}"

if [[ ! -f "$env_file" ]]; then
  echo "Environment file not found: $env_file" >&2
  exit 2
fi
for command_name in pg_dump pg_restore sha256sum; do
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

backup_dir="${BACKUP_DIR:-$project_dir/../backups}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
verify_restore="${BACKUP_VERIFY_RESTORE:-1}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$backup_dir/atlas-ledger-$timestamp.dump"
temporary_file="$backup_dir/.atlas-ledger-$timestamp-$$.tmp"

umask 077
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
trap 'rm -f "$temporary_file"' EXIT

pg_dump \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  --file="$temporary_file" \
  "$database_url"
pg_restore --list "$temporary_file" >/dev/null
mv "$temporary_file" "$backup_file"
sha256sum "$backup_file" > "$backup_file.sha256"

if [[ "$verify_restore" == "1" ]]; then
  BACKUP_DATABASE_URL="$database_url" ENV_FILE="$env_file" \
    "$script_dir/verify-postgres-backup.sh" "$backup_file"
fi

find "$backup_dir" -maxdepth 1 -type f \
  \( -name 'atlas-ledger-*.dump' -o -name 'atlas-ledger-*.dump.sha256' \) \
  -mtime "+$retention_days" -delete

echo "Backup completed: $backup_file"
