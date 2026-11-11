#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer as root" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
env_file="${ENV_FILE:-$project_dir/.env}"
if [[ ! -f "$env_file" ]]; then
  echo "Environment file not found: $env_file" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
if [[ -z "${FEISHU_DAILY_PNL_WEBHOOK_URL:-}" || "$FEISHU_DAILY_PNL_WEBHOOK_URL" == "${FEISHU_HEALTH_WEBHOOK_URL:-}" ]]; then
  echo "Configure a distinct FEISHU_DAILY_PNL_WEBHOOK_URL before installing the schedule" >&2
  exit 2
fi

cron_file="/etc/cron.d/aggregated-accounts-daily-pnl"
logrotate_file="/etc/logrotate.d/aggregated-accounts-daily-pnl"
temporary_cron="$(mktemp /tmp/aggregated-accounts-daily-pnl-cron.XXXXXX)"
temporary_logrotate="$(mktemp /tmp/aggregated-accounts-daily-pnl-logrotate.XXXXXX)"
trap 'rm -f "$temporary_cron" "$temporary_logrotate"' EXIT

# Ubuntu cron uses host time for scheduling. Check Beijing time in the command
# so the report runs at 01:00 even when the host is configured for UTC.
printf '%s\n' \
  'SHELL=/bin/bash' \
  'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
  "0 * * * * root [ \$(TZ=Asia/Shanghai date +\\%H) = 01 ] && cd $project_dir && ENV_FILE=$env_file ./scripts/daily-pnl-report.sh >> /var/log/aggregated-accounts-daily-pnl.log 2>&1" \
  > "$temporary_cron"
install -m 0644 "$temporary_cron" "$cron_file"

printf '%s\n' \
  '/var/log/aggregated-accounts-daily-pnl.log {' \
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

echo "Installed Beijing-time 01:00 daily PnL schedule: $cron_file"
