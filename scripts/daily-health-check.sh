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
balance_stale_seconds=$(( ${SYNC_BALANCE_SECONDS:-60} * 3 ))
position_stale_seconds=$(( ${SYNC_POSITION_SECONDS:-15} * 4 ))
closed_stale_seconds=$(( ${SYNC_CLOSED_POSITION_SECONDS:-600} * 2 ))
history_stale_seconds=$(( ${SYNC_HISTORY_SECONDS:-300} * 3 ))
(( balance_stale_seconds < 300 )) && balance_stale_seconds=300
(( position_stale_seconds < 120 )) && position_stale_seconds=120
(( closed_stale_seconds < 1200 )) && closed_stale_seconds=1200
(( history_stale_seconds < 900 )) && history_stale_seconds=900

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
      (SELECT extract(epoch FROM (now() - max(bucket_time)))::bigint FROM portfolio_equity_points),
      (SELECT count(*) FROM portfolio_equity_points),
      (SELECT count(*) FROM sync_jobs),
      (SELECT coalesce(max(recorded_at)::text, 'none') FROM latest_account_balances),
      (SELECT coalesce(max(extract(epoch FROM (now() - coalesce(
        nullif(data_completeness_details->>'last_balance_sync_at', '')::timestamptz,
        last_synced_at))))::bigint, -1) FROM exchange_accounts WHERE is_active),
      (SELECT coalesce(max(extract(epoch FROM (now() - coalesce(
        nullif(data_completeness_details->>'last_position_sync_at', '')::timestamptz,
        last_synced_at))))::bigint, -1) FROM exchange_accounts WHERE is_active),
      (SELECT coalesce(max(extract(epoch FROM (now() - coalesce(
        nullif(data_completeness_details->>'last_closed_position_sync_at', '')::timestamptz,
        last_synced_at))))::bigint, -1) FROM exchange_accounts WHERE is_active),
      (SELECT coalesce(max(extract(epoch FROM (now() - coalesce(
        nullif(data_completeness_details->>'last_history_sync_at', '')::timestamptz,
        last_synced_at))))::bigint, -1)
        FROM exchange_accounts
        WHERE is_active AND (
          coalesce(data_completeness_details->>'income', 'UNKNOWN') <> 'UNSUPPORTED'
          OR coalesce(data_completeness_details->>'funding', 'UNKNOWN') <> 'UNSUPPORTED'
          OR coalesce(data_completeness_details->>'fees', 'UNKNOWN') <> 'UNSUPPORTED'
          OR coalesce(data_completeness_details->>'cash_flows', 'UNKNOWN') <> 'UNSUPPORTED'
        )),
      (SELECT count(*) FROM operational_read_models),
      (SELECT coalesce(extract(epoch FROM (now() - min(calculated_at)))::bigint, -1)
        FROM operational_read_models),
      (SELECT count(*) FROM accounting_daily_summaries),
      (SELECT count(*) FROM app_settings
        WHERE key = 'daily_pnl_reporting_calendar'
          AND value->>'version' = '2'
          AND value->>'timezone' = 'Asia/Shanghai'),
      (SELECT count(*) FROM sync_jobs
        WHERE status = 'SUCCESS' AND started_at >= now() - interval '24 hours'
          AND job_type LIKE '%POSITIONS%'),
      (SELECT count(*) FROM sync_jobs
        WHERE status = 'SUCCESS' AND started_at >= now() - interval '24 hours'
          AND job_type LIKE '%HISTORY%'),
      (SELECT count(*) FROM sync_jobs
        WHERE status = 'SUCCESS' AND started_at >= now() - interval '24 hours'
          AND job_type LIKE '%CLOSED%'),
      (SELECT count(*) FROM sync_jobs
        WHERE status = 'SUCCESS' AND started_at >= now() - interval '24 hours'
          AND job_type LIKE '%BALANCE%');
  " 2>/dev/null || true)"
fi

if [[ -z "$db_result" ]]; then
  critical "PostgreSQL 查询失败"
else
  IFS='|' read -r db_bytes active_accounts latest_accounts stale_accounts failed_jobs \
    jobs_24h successful_jobs average_duration recent_errors translation_queue daily_accounts \
    daily_assets daily_positions current_positions closed_positions \
    equity_lag_seconds equity_point_count sync_job_count latest_at \
    balance_lag_seconds position_lag_seconds closed_lag_seconds history_lag_seconds \
    read_model_count read_model_lag_seconds accounting_summary_count calendar_marker_count \
    position_jobs history_jobs closed_jobs balance_jobs <<< "$db_result"
  db_megabytes=$((db_bytes / 1024 / 1024))
  if (( jobs_24h > 0 )); then
    success_rate="$(awk -v success="$successful_jobs" -v total="$jobs_24h" 'BEGIN {printf "%.2f", success * 100 / total}')"
  else
    success_rate="0.00"
  fi
  data_details+=("数据库：${db_megabytes}MB；同步任务累计 ${sync_job_count} 条")
  data_details+=("24小时同步：${successful_jobs}/${jobs_24h} 成功（${success_rate}%），平均 ${average_duration}ms")
  data_details+=("实时账户：${latest_accounts}/${active_accounts}；当前仓位 ${current_positions}；历史仓位 ${closed_positions}")
  data_details+=("今日快照：账户 ${daily_accounts}、资产 ${daily_assets}、持仓 ${daily_positions}")
  data_details+=("同步流：余额 ${balance_lag_seconds}秒、仓位 ${position_lag_seconds}秒、平仓 ${closed_lag_seconds}秒、账务 ${history_lag_seconds}秒")
  data_details+=("24小时分流任务：余额 ${balance_jobs}、仓位 ${position_jobs}、平仓 ${closed_jobs}、账务 ${history_jobs}")
  data_details+=("读取模型：${read_model_count}/5，最旧延迟 ${read_model_lag_seconds}秒；财务日汇总 ${accounting_summary_count} 条")
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
  if (( balance_lag_seconds < 0 || balance_lag_seconds > balance_stale_seconds )); then
    critical "余额同步流已延迟 ${balance_lag_seconds} 秒"
  fi
  if (( position_lag_seconds < 0 || position_lag_seconds > position_stale_seconds )); then
    critical "当前仓位同步流已延迟 ${position_lag_seconds} 秒"
  fi
  if (( closed_lag_seconds < 0 || closed_lag_seconds > closed_stale_seconds )); then
    critical "已平仓同步流已延迟 ${closed_lag_seconds} 秒"
  fi
  if (( history_lag_seconds < 0 || history_lag_seconds > history_stale_seconds )); then
    critical "账务历史同步流已延迟 ${history_lag_seconds} 秒"
  fi
  if (( read_model_count != 5 )); then
    critical "读取模型数量异常：${read_model_count}/5"
  elif (( read_model_lag_seconds < 0 || read_model_lag_seconds > 300 )); then
    critical "读取模型最旧数据已延迟 ${read_model_lag_seconds} 秒"
  fi
  if (( accounting_summary_count == 0 )); then
    critical "财务日汇总为空"
  fi
  if (( calendar_marker_count != 1 )); then
    critical "北京时间日快照迁移标记缺失或版本异常"
  fi
  if (( position_jobs == 0 || closed_jobs == 0 || balance_jobs == 0 )); then
    warn "最近24小时存在未执行成功的核心同步流"
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
  card_template="red"
  exit_code=2
elif (( ${#warnings[@]} > 0 )); then
  status="需要关注"
  icon="🟡"
  card_template="orange"
  exit_code=1
else
  status="正常"
  icon="🟢"
  card_template="green"
  exit_code=0
fi

report_time="$(TZ=Asia/Shanghai date '+%F %T %Z')"
report="$icon Atlas Ledger 每日巡检：$status
时间：$report_time"
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
  card_args=(
    --status "$status"
    --icon "$icon"
    --timestamp "$report_time"
    --template "$card_template"
    --public-url "$public_url"
  )
  for line in "${criticals[@]}"; do card_args+=(--critical "$line"); done
  for line in "${warnings[@]}"; do card_args+=(--warning "$line"); done
  for line in "${system_details[@]}"; do card_args+=(--system "$line"); done
  for line in "${service_details[@]}"; do card_args+=(--service "$line"); done
  for line in "${data_details[@]}"; do card_args+=(--data "$line"); done
  for line in "${backup_details[@]}"; do card_args+=(--backup "$line"); done
  payload="$(python3 "$script_dir/build-feishu-health-card.py" "${card_args[@]}")"
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
