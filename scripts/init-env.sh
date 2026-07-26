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

chmod 600 "${env_file}"
printf 'Environment ready; encryption material is present and hidden.\n'
