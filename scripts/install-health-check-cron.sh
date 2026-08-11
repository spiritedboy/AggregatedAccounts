#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer as root" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
health_env_file="${HEALTH_ENV_FILE:-$project_dir/.env}"
cron_file="/etc/cron.d/aggregated-accounts-health-check"
logrotate_file="/etc/logrotate.d/aggregated-accounts-health-check"
temporary_cron="$(mktemp /tmp/aggregated-accounts-health-cron.XXXXXX)"
temporary_logrotate="$(mktemp /tmp/aggregated-accounts-health-logrotate.XXXXXX)"
trap 'rm -f "$temporary_cron" "$temporary_logrotate"' EXIT

printf '%s\n' \
  'SHELL=/bin/bash' \
  'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
  "30 3 * * * root cd $project_dir && ENV_FILE=$health_env_file ./scripts/daily-health-check.sh >> /var/log/aggregated-accounts-health-check.log 2>&1" \
  > "$temporary_cron"
install -m 0644 "$temporary_cron" "$cron_file"

printf '%s\n' \
  '/var/log/aggregated-accounts-health-check.log {' \
  '  daily' \
  '  rotate 7' \
  '  compress' \
  '  missingok' \
  '  notifempty' \
  '  copytruncate' \
  '}' \
  > "$temporary_logrotate"
install -m 0644 "$temporary_logrotate" "$logrotate_file"

if command -v systemctl >/dev/null 2>&1; then
  systemctl enable --now cron
fi

echo "Installed daily health-check schedule: $cron_file"
