#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer as root" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
cron_file="/etc/cron.d/aggregated-accounts-backup"
logrotate_file="/etc/logrotate.d/aggregated-accounts-backup"
temporary_cron="$(mktemp /tmp/aggregated-accounts-cron.XXXXXX)"
temporary_logrotate="$(mktemp /tmp/aggregated-accounts-logrotate.XXXXXX)"
trap 'rm -f "$temporary_cron" "$temporary_logrotate"' EXIT

printf '%s\n' \
  'SHELL=/bin/bash' \
  'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
  "17 3 * * * root cd $project_dir && BACKUP_RETENTION_DAYS=14 BACKUP_VERIFY_RESTORE=1 ./scripts/backup-postgres.sh >> /var/log/aggregated-accounts-backup.log 2>&1" \
  > "$temporary_cron"
install -m 0644 "$temporary_cron" "$cron_file"

printf '%s\n' \
  '/var/log/aggregated-accounts-backup.log {' \
  '  weekly' \
  '  rotate 8' \
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

echo "Installed daily backup schedule: $cron_file"
