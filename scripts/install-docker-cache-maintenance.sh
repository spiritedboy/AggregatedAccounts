#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cron_file="/etc/cron.d/aggregated-accounts-docker-cache"
logrotate_file="/etc/logrotate.d/aggregated-accounts-docker-cache"

chmod +x "$project_dir/scripts/prune-docker-build-cache.sh"
printf '%s\n' \
  'SHELL=/bin/bash' \
  'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
  "40 4 * * * root flock -n /run/aggregated-accounts-docker-cache.lock $project_dir/scripts/prune-docker-build-cache.sh >> /var/log/aggregated-accounts-docker-cache.log 2>&1" \
  > "$cron_file"
chmod 0644 "$cron_file"

printf '%s\n' \
  '/var/log/aggregated-accounts-docker-cache.log {' \
  '    daily' \
  '    rotate 7' \
  '    compress' \
  '    delaycompress' \
  '    missingok' \
  '    notifempty' \
  '    create 0640 root adm' \
  '}' \
  > "$logrotate_file"
chmod 0644 "$logrotate_file"

echo "Installed Docker build-cache maintenance: $cron_file"
