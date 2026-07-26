#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_dir}"

if git ls-files .env | grep -q .; then
  printf '.env is tracked by Git\n' >&2
  exit 1
fi

if find . -path ./.git -prune -o \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) -print | grep -q .; then
  printf 'SQLite artifact detected\n' >&2
  exit 1
fi

if git grep -nE '(APP_ENCRYPTION_KEY=[A-Za-z0-9+/]{20,}|postgres:[^@[:space:]]+@)' -- \
  ':!.env.example' ':!scripts/security-check.sh'; then
  printf 'Potential committed secret detected\n' >&2
  exit 1
fi

if git grep -nEi '(place_order|create_order|cancel_order|close_position|set_leverage|/withdraw|/transfer)' -- \
  backend frontend ':!scripts/security-check.sh'; then
  printf 'Potential write/trading implementation detected\n' >&2
  exit 1
fi

printf 'Security checks passed: no tracked env, SQLite, committed secrets, or trading calls.\n'
