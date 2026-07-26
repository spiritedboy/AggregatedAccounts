#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL_SYNC:?DATABASE_URL_SYNC is required}"
database_auth="${DATABASE_URL_SYNC#*://}"
database_auth="${database_auth%%@*}"
db_user="${database_auth%%:*}"
export PGPASSWORD="${database_auth#*:}"
db_host="${POSTGRES_HOST:-127.0.0.1}"

for database in exchange_aggregator exchange_aggregator_test; do
  if ! psql -h "${db_host}" -U "${db_user}" -d postgres -Atqc \
    "SELECT 1 FROM pg_database WHERE datname='${database}'" | grep -q 1; then
    createdb -h "${db_host}" -U "${db_user}" "${database}"
  fi
  psql -h "${db_host}" -U "${db_user}" -d "${database}" -Atqc 'SELECT 1' >/dev/null
done

docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e PGPASSWORD \
  postgres:alpine \
  psql -h host.docker.internal -U "${db_user}" -d exchange_aggregator -Atqc 'SELECT 1' >/dev/null

printf 'PostgreSQL host and container connectivity verified.\n'
