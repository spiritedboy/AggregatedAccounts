#!/usr/bin/env bash
set -euo pipefail

: "${PGPASSWORD:?Set PGPASSWORD for the local PostgreSQL administrator}"
db_user="${POSTGRES_USER:-postgres}"
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
