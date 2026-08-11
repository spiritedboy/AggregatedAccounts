#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
env_file="${ENV_FILE:-$project_dir/.env}"
public_url="${HEALTH_CHECK_PUBLIC_URL:-https://www.bitboy.cn}"
send_message=1
if [[ "${1:-}" == "--no-send" ]]; then
  send_message=0
fi

if [[ ! -f "$env_file" ]]; then
  echo "Environment file not found: $env_file" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

database_url="${DATABASE_URL_SYNC:-}"
database_url="${database_url/postgresql+psycopg:/postgresql:}"
database_url="${database_url/postgresql+asyncpg:/postgresql:}"
database_url="${database_url/host.docker.internal/127.0.0.1}"
backup_dir="${BACKUP_DIR:-$project_dir/../backups}"
webhook_url="${FEISHU_HEALTH_WEBHOOK_URL:-}"
warning_disk_percent="${HEALTH_CHECK_WARNING_DISK_PERCENT:-80}"
critical_disk_percent="${HEALTH_CHECK_CRITICAL_DISK_PERCENT:-90}"

warnings=()
criticals=()
system_details=()
service_details=()
data_details=()
backup_details=()

warn() { warnings+=("$1"); }
critical() { criticals+=("$1"); }

for command_name in curl docker openssl psql python3 sha256sum timeout; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    critical "缺少命令：$command_name"
  fi
done

health_body="$(curl -fsS --max-time 10 http://127.0.0.1:8000/api/health 2>/dev/null || true)"
if [[ "$health_body" != *'"status":"healthy"'* ]]; then
  critical "本机健康接口异常"
  service_details+=("本机接口：异常")
else
  service_details+=("本机接口：正常，数据库已连接")
fi
if ! curl -fsS --max-time 15 "$public_url" >/dev/null 2>&1; then
  critical "公网网站无法访问：$public_url"
  service_details+=("公网访问：异常（$public_url）")
else
  service_details+=("公网访问：正常（$public_url）")
fi

public_host="$(PUBLIC_URL="$public_url" python3 -c \
  'import os, urllib.parse; print(urllib.parse.urlparse(os.environ["PUBLIC_URL"]).hostname or "")')"
if [[ -n "$public_host" ]]; then
  certificate_end="$(timeout 15 openssl s_client -servername "$public_host" \
    -connect "$public_host:443" </dev/null 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2- || true)"
  if [[ -z "$certificate_end" ]]; then
    critical "无法读取 HTTPS 证书"
  else
    certificate_days=$(( ($(date -d "$certificate_end" +%s) - $(date +%s)) / 86400 ))
    certificate_date="$(TZ=Asia/Shanghai date -d "$certificate_end" '+%F')"
    service_details+=("HTTPS证书：${certificate_date} 到期，剩余 ${certificate_days} 天")
    if (( certificate_days < 7 )); then
      critical "HTTPS证书仅剩 ${certificate_days} 天"
    elif (( certificate_days < 30 )); then
      warn "HTTPS证书仅剩 ${certificate_days} 天"
    fi
  fi
fi

expected_services=3
healthy_services=0
for service in backend frontend gateway; do
  container_id="$(cd "$project_dir" && docker compose \
    -f docker-compose.yml -f docker-compose.prod.yml ps -q "$service" 2>/dev/null || true)"
  if [[ -z "$container_id" ]]; then
    critical "$service 容器不存在"
    continue
  fi
  state="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
  if [[ "$state" == "running healthy" ]]; then
    healthy_services=$((healthy_services + 1))
  else
    critical "$service 状态异常：${state:-unknown}"
  fi
  restart_count="$(docker inspect --format '{{.RestartCount}}' "$container_id" 2>/dev/null || echo 0)"
  container_status="$(docker ps --filter "id=$container_id" --format '{{.Status}}' 2>/dev/null || true)"
  service_details+=("$service：${state:-unknown}，${container_status:-状态未知}，重启 ${restart_count} 次")
  if (( restart_count > 0 )); then
    warn "$service 累计重启 $restart_count 次"
  fi
done
service_details+=("服务汇总：$healthy_services/$expected_services 健康")

disk_percent="$(df -P / | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
disk_available="$(df -hP / | awk 'NR==2 {print $4}')"
memory_line="$(free -m | awk '/^Mem:/ {printf "内存：已用 %dMB/%dMB，可用 %dMB", $3, $2, $7}')"
swap_line="$(free -m | awk '/^Swap:/ {printf "Swap：已用 %dMB/%dMB", $3, $2}')"
load_line="$(awk '{printf "负载：1分钟 %s，5分钟 %s，15分钟 %s", $1, $2, $3}' /proc/loadavg)"
uptime_line="$(uptime -p 2>/dev/null || true)"
if (( disk_percent >= critical_disk_percent )); then
  critical "磁盘使用率 ${disk_percent}%"
elif (( disk_percent >= warning_disk_percent )); then
  warn "磁盘使用率 ${disk_percent}%"
fi
system_details+=("运行时间：${uptime_line#up }")
system_details+=("$load_line")
system_details+=("$memory_line；$swap_line")
system_details+=("磁盘：已用 ${disk_percent}%，可用 $disk_available")

db_result=""
if [[ -z "$database_url" ]]; then
  critical "未配置 DATABASE_URL_SYNC"
else
  db_result="$(psql "$database_url" -AtF '|' -v ON_ERROR_STOP=1 -c "
    SELECT
      pg_database_size(current_database()),
      (SELECT count(*) FROM exchange_accounts WHERE is_active = true),
      (SELECT count(*) FROM latest_account_balances),
      (SELECT count(*) FROM latest_account_balances
        WHERE recorded_at < now() - interval '5 minutes'),
      (SELECT count(*) FROM sync_jobs
        WHERE status = 'FAILED' AND started_at >= now() - interval '24 hours'),
      (SELECT count(*) FROM sync_jobs WHERE started_at >= now() - interval '24 hours'),
      (SELECT count(*) FROM sync_jobs
        WHERE status = 'SUCCESS' AND started_at >= now() - interval '24 hours'),
      (SELECT coalesce(avg(duration_ms), 0)::bigint FROM sync_jobs
        WHERE status = 'SUCCESS' AND started_at >= now() - interval '24 hours'),
      (SELECT count(*) FROM sync_errors
        WHERE occurred_at >= now() - interval '24 hours'),
      (SELECT count(*) FROM polymarket_translations WHERE status IN ('PENDING', 'FAILED')),
      (SELECT count(*) FROM account_balance_snapshots
        WHERE source_record_id = 'balance-daily-' || to_char(now() AT TIME ZONE 'Asia/Shanghai', 'YYYYMMDD')),
      (SELECT count(*) FROM asset_balance_snapshots
        WHERE source_record_id LIKE 'asset-daily-' || to_char(now() AT TIME ZONE 'Asia/Shanghai', 'YYYYMMDD') || '%'),
      (SELECT count(*) FROM position_snapshots
        WHERE source_record_id LIKE 'position-daily-' || to_char(now() AT TIME ZONE 'Asia/Shanghai', 'YYYYMMDD') || '%'),
      (SELECT count(*) FROM current_positions),
      (SELECT count(*) FROM closed_positions),
      (SELECT count(*) FROM income_records),
      (SELECT count(*) FROM funding_records),
      (SELECT count(*) FROM trading_fee_records),
      (SELECT count(*) FROM cash_flow_records),
      (SELECT extract(epoch FROM (now() - max(bucket_time)))::bigint FROM portfolio_equity_points),
      (SELECT count(*) FROM portfolio_equity_points),
      (SELECT count(*) FROM sync_jobs),
      (SELECT coalesce(max(recorded_at)::text, 'none') FROM latest_account_balances);
  " 2>/dev/null || true)"
fi

if [[ -z "$db_result" ]]; then
  critical "PostgreSQL 查询失败"
else
  IFS='|' read -r db_bytes active_accounts latest_accounts stale_accounts failed_jobs \
    jobs_24h successful_jobs average_duration recent_errors translation_queue daily_accounts \
    daily_assets daily_positions current_positions closed_positions income_records \
    funding_records fee_records cash_flow_records equity_lag_seconds equity_point_count \
    sync_job_count latest_at <<< "$db_result"
  db_megabytes=$((db_bytes / 1024 / 1024))
  if (( jobs_24h > 0 )); then
    success_rate="$(awk -v success="$successful_jobs" -v total="$jobs_24h" 'BEGIN {printf "%.2f", success * 100 / total}')"
  else
    success_rate="0.00"
  fi
  data_details+=("数据库：${db_megabytes}MB；同步任务累计 ${sync_job_count} 条")
  data_details+=("24小时同步：${successful_jobs}/${jobs_24h} 成功（${success_rate}%），平均 ${average_duration}ms")
  data_details+=("实时账户：${latest_accounts}/${active_accounts}；当前仓位 ${current_positions}；历史仓位 ${closed_positions}")
  data_details+=("财务明细：收益 ${income_records}、资金费 ${funding_records}、手续费 ${fee_records}、流水 ${cash_flow_records}")
  data_details+=("今日快照：账户 ${daily_accounts}、资产 ${daily_assets}、持仓 ${daily_positions}")
  if [[ "$equity_lag_seconds" =~ ^[0-9]+$ ]]; then
    data_details+=("净值曲线：${equity_point_count} 点，延迟 $((equity_lag_seconds / 60)) 分钟")
  else
    data_details+=("净值曲线：${equity_point_count} 点，无法确定最新采样时间")
    critical "无法确定净值曲线最新采样时间"
  fi
  data_details+=("最近账户更新：$latest_at")
  if (( latest_accounts != active_accounts )); then
    critical "实时账户数 ${latest_accounts} 与启用账户数 ${active_accounts} 不一致"
  fi
  if (( stale_accounts > 0 )); then
    critical "$stale_accounts 个账户超过5分钟未更新"
  fi
  if (( failed_jobs > 0 )); then
    warn "最近24小时有 $failed_jobs 个同步任务失败"
  fi
  if (( recent_errors > 0 )); then
    warn "最近24小时记录了 $recent_errors 个同步错误"
  fi
  if (( translation_queue > 0 )); then
    warn "Polymarket 待处理或失败翻译 $translation_queue 条"
  fi
  if (( daily_accounts != active_accounts )); then
    warn "今日账户快照 ${daily_accounts}/${active_accounts}"
  fi
  if [[ "$equity_lag_seconds" =~ ^[0-9]+$ ]] && (( equity_lag_seconds > 900 )); then
    critical "净值曲线已延迟 $((equity_lag_seconds / 60)) 分钟"
  fi
fi

latest_backup="$(find "$backup_dir" -maxdepth 1 -type f -name 'atlas-ledger-*.dump' \
  -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2- || true)"
if [[ -z "$latest_backup" ]]; then
  critical "未找到数据库备份"
else
  backup_age_hours=$(( ($(date +%s) - $(stat -c %Y "$latest_backup")) / 3600 ))
  backup_size="$(du -h "$latest_backup" | awk '{print $1}')"
  backup_time="$(TZ=Asia/Shanghai date -d "@$(stat -c %Y "$latest_backup")" '+%F %T')"
  backup_details+=("最新备份：$(basename "$latest_backup")")
  backup_details+=("生成时间：$backup_time，距今 ${backup_age_hours} 小时，大小 $backup_size")
  if (( backup_age_hours > 30 )); then
    critical "最新备份已超过30小时"
  fi
  if [[ ! -f "$latest_backup.sha256" ]] || ! (
    cd "$(dirname "$latest_backup")" && sha256sum -c "$(basename "$latest_backup").sha256" >/dev/null 2>&1
  ); then
    critical "最新备份校验失败"
    backup_details+=("SHA-256：失败")
  else
    backup_details+=("SHA-256：通过")
  fi
  if [[ -f /var/log/aggregated-accounts-backup.log ]] && ! \
    tail -80 /var/log/aggregated-accounts-backup.log | grep -q 'Restore verification passed'; then
    warn "备份日志中未找到最近的恢复验证成功记录"
    backup_details+=("恢复验证：未确认")
  else
    backup_details+=("恢复验证：通过")
  fi
fi

if (( ${#criticals[@]} > 0 )); then
  status="异常"
  icon="🔴"
  exit_code=2
elif (( ${#warnings[@]} > 0 )); then
  status="需要关注"
  icon="🟡"
  exit_code=1
else
  status="正常"
  icon="🟢"
  exit_code=0
fi

report="$icon Atlas Ledger 每日巡检：$status
时间：$(TZ=Asia/Shanghai date '+%F %T %Z')"
for section in "系统资源:system_details" "服务与网络:service_details" \
  "数据库与业务数据:data_details" "备份:backup_details"; do
  section_title="${section%%:*}"
  array_name="${section#*:}"
  declare -n section_lines="$array_name"
  report+=$'\n\n'"【$section_title】"
  for line in "${section_lines[@]}"; do
    report+=$'\n'"- $line"
  done
done
if (( ${#criticals[@]} > 0 )); then
  report+=$'\n\n'"严重问题："
  for line in "${criticals[@]}"; do report+=$'\n'"- $line"; done
fi
if (( ${#warnings[@]} > 0 )); then
  report+=$'\n\n'"注意事项："
  for line in "${warnings[@]}"; do report+=$'\n'"- $line"; done
fi

printf '%s\n' "$report"

if (( send_message == 1 )); then
  if [[ -z "$webhook_url" ]]; then
    echo "FEISHU_HEALTH_WEBHOOK_URL is not configured" >&2
    exit 2
  fi
  payload="$(REPORT_TEXT="$report" python3 -c \
    'import json, os; print(json.dumps({"msg_type":"text","content":{"text":os.environ["REPORT_TEXT"]}}, ensure_ascii=False))')"
  response="$(curl -fsS --max-time 15 -H 'Content-Type: application/json; charset=utf-8' \
    -d "$payload" "$webhook_url" 2>/dev/null || true)"
  if ! RESPONSE_BODY="$response" python3 -c \
    'import json, os, sys; data=json.loads(os.environ["RESPONSE_BODY"]); sys.exit(0 if data.get("code", data.get("StatusCode")) == 0 else 1)' \
    2>/dev/null; then
    echo "Feishu delivery failed: ${response:-no response}" >&2
    exit 2
  fi
fi

exit "$exit_code"
