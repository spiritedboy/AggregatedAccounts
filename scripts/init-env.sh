#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${project_dir}/.env"

if [[ ! -f "${env_file}" ]]; then
  cp "${project_dir}/.env.example" "${env_file}"
fi

upsert_secret() {
  local name="$1"
  local value
  if grep -Eq "^${name}=.{16,}$" "${env_file}"; then
    return
  fi
  value="$(openssl rand -base64 48 | tr -d '\n')"
  if grep -q "^${name}=" "${env_file}"; then
    sed -i "s|^${name}=.*|${name}=${value}|" "${env_file}"
  else
    printf '%s=%s\n' "${name}" "${value}" >> "${env_file}"
  fi
}

upsert_secret APP_ENCRYPTION_KEY
upsert_secret SESSION_SECRET

if grep -q '^APP_ACCESS_PASSWORD=CHANGE_ME$' "${env_file}"; then
  access_password="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-18)"
  sed -i "s|^APP_ACCESS_PASSWORD=CHANGE_ME$|APP_ACCESS_PASSWORD=${access_password}|" "${env_file}"
  printf 'Generated a local access password in .env (value intentionally not printed).\n'
fi

chmod 600 "${env_file}"
printf 'Environment ready; encryption material is present and hidden.\n'
