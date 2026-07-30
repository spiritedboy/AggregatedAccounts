# 部署说明

## 本地 WSL

前置条件：

- Docker Engine 与 Docker Compose
- WSL 宿主机 PostgreSQL 16
- 与 PostgreSQL 版本匹配的 TimescaleDB
- 正式数据库 `exchange_aggregator`
- 测试数据库 `exchange_aggregator_test`
- PostgreSQL 允许项目 Docker 子网 `172.30.42.0/24` 以
  `scram-sha-256` 连接上述两个数据库

启动：

```bash
cd /home/yyf/codex/AggregatedAccounts
make dev-up
```

开发覆盖文件把 gateway 映射为：

```yaml
ports:
  - "0.0.0.0:8000:80"
```

## 远程服务器

1. 将项目放入远程 Linux 文件系统。
2. 创建 PostgreSQL 正式库与测试库，并仅放行项目 Docker 子网。
3. 安装与 PostgreSQL 主版本匹配的 TimescaleDB；先备份
   `/etc/postgresql/<version>/main/postgresql.conf`，再配置
   `shared_preload_libraries = 'timescaledb'` 并重启 PostgreSQL。
4. 复制 `.env.example` 为 `.env`，填写数据库密码、主加密密钥和已启用账户引用的环境变量。
5. 运行 `make init` 自动生成缺失的主加密密钥和会话密钥。
6. 将 `COOKIE_SECURE=true`、`APP_ENV=production`、`DEMO_MODE=false` 写入 `.env`。
7. 如需启用 Polymarket 简体中文标题，在 `.env` 中配置百度 LLM 翻译：

```dotenv
BAIDU_TRANSLATION_ENABLED=true
BAIDU_TRANSLATION_APPID=<server-only-appid>
BAIDU_TRANSLATION_API_KEY=<server-only-api-key>
```

   凭证只保存在服务器 `.env`，文件权限应为 `600`，不得提交 Git 或写入日志。
8. 永久保留生产数据库数据：

```dotenv
SYNC_JOB_RETENTION_DAYS=0
BALANCE_SNAPSHOT_RETENTION_DAYS=0
```

9. 启动生产覆盖：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  run --rm backend alembic upgrade head

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d --build
```

生产覆盖仅绑定：

```yaml
ports:
  - "127.0.0.1:8000:80"
```

项目不会占用宿主机 80/443，不管理 Let's Encrypt，也不会覆盖现有 Nginx。

## 账户配置

编辑 `backend/config/exchange_accounts.json`，启用需要的平台。真实凭证放在服务器
`.env` 中，由 JSON 的 `api_key_env`、`api_secret_env`、`passphrase_env` 或
`wallet_address_env` 引用。不要把真实密钥直接写入仓库。

backend 每次启动都会读取配置：

- 禁用项直接跳过；
- 同交易所、同连接名称的启用账户保持不变；
- 仅为缺失的启用账户测试只读权限并创建初始快照；
- 不会因为配置项缺失或禁用而删除数据库中的已有账户和历史数据。

Polymarket 翻译结果保存在独立的 `polymarket_translations` 表，迁移只新增表和索引，
不修改账户、当前仓位或历史仓位。首次启用后可安全回填存量市场：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  exec -T backend python scripts/backfill_polymarket_translations.py
```

脚本先按正常只读流程同步 Polymarket，再翻译尚未缓存的 outcome token。失败项保留
英文原文并由后续任务重试；已成功的译文在仓位平仓后继续复用。

网站为公开只读模式，不需要访问密码；添加、删除、连接测试和手动同步只能通过服务器
配置、后台调度或运维流程完成，公网页面和对应写 API 均不能触发。

## 宿主机 Nginx 示例

以下配置仅供手工合并，不应自动覆盖服务器现有配置：

```nginx
server {
    listen 80;
    server_name portfolio.example.com;

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name portfolio.example.com;

    ssl_certificate /etc/letsencrypt/live/portfolio.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/portfolio.example.com/privkey.pem;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
```

## 上线检查

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  ps

curl -f http://127.0.0.1:8000/api/health
make security-check
```

确认：

- gateway 仅绑定 `127.0.0.1:8000`
- backend 与 frontend 没有宿主机端口
- 没有 PostgreSQL 容器
- `.env` 权限是 `600` 且未被 Git 跟踪
- `/api/auth/login` 不存在，读取接口无需登录，写接口返回 403
- 宿主机防火墙没有对公网开放 8000 或 5432
- `timescaledb` 和 `timescaledb_toolkit` 扩展版本可查询
- `portfolio_equity_points` 位于 `timescaledb_information.hypertables`
- 四个 `portfolio_equity_*` 连续聚合存在
- `SYNC_JOB_RETENTION_DAYS=0`、`BALANCE_SNAPSHOT_RETENTION_DAYS=0`

## 备份与密钥

先手工执行并验证一次：

```bash
./scripts/backup-postgres.sh
```

脚本执行 `pg_dump` custom format、SHA-256 校验和 `pg_restore --list`，随后将备份
恢复到随机命名的 `atlas_restore_check_*` 临时数据库。恢复过程先创建 TimescaleDB
扩展并执行 `timescaledb_pre_restore()`，完成后执行
`timescaledb_post_restore()` 与 `ANALYZE`，再验证业务表与 Alembic 版本并删除临时库。
恢复验证失败的文件不会保留。默认备份目录是仓库同级的 `backups`，默认保留 90 天。

确认成功后，以 root 安装每日 03:17 的 cron、90 天备份保留与 7 天备份日志轮换：

```bash
sudo ./scripts/install-backup-cron.sh
cat /etc/cron.d/aggregated-accounts-backup
```

主加密密钥必须与数据库备份分开保管；丢失主密钥后，已保存的交易所凭证无法恢复。
轮换主密钥需要先实现专用的离线重加密流程，不能直接替换 `.env` 中的值。

## 运行数据与日志保留

生产数据库永久保留，相关环境变量必须为：

```dotenv
SYNC_JOB_RETENTION_DAYS=0
BALANCE_SNAPSHOT_RETENTION_DAYS=0
MAINTENANCE_HOUR_UTC=4
MAINTENANCE_MINUTE_UTC=20
```

`0` 会跳过对应删除语句。备份文件独立保留 90 天，不等同于数据库只保留 90 天。

项目容器使用 Docker `journald` 日志驱动。生产服务器应设置
`MaxRetentionSec=7day`，并把 Nginx、PostgreSQL 和项目备份日志的 logrotate 配置为
`daily`、`rotate 7`。修改后执行：

```bash
systemctl restart systemd-journald
journalctl --vacuum-time=7d
logrotate -d /etc/logrotate.conf
```

日志清理不得匹配 PostgreSQL 数据目录、备份目录或项目上传文件目录。

## 无数据丢失升级顺序

1. 记录升级前 Git 提交、容器状态、Alembic 版本和核心表行数。
2. 执行 `backup-postgres.sh`，检查 SHA-256，并完成临时库恢复验证。
3. 备份 PostgreSQL 配置；安装 TimescaleDB 后仅重启 PostgreSQL，不重建数据库。
4. 验证原有核心表行数未减少。
5. 执行 Alembic 增量迁移。迁移只新增净值表、hypertable 和连续聚合。
6. 运行 `backfill_portfolio_equity.py`；脚本只读取既有余额快照并向新表 UPSERT。
7. 先更新 backend，验证健康检查和新旧 API，再更新 frontend/gateway。
8. 验证五个交易所账户、当前仓位、历史仓位、账务流水、净值曲线和自动同步。

应用回滚时切回升级前 Git 提交并重建容器；不要执行 Alembic downgrade。新增净值表
可以留在数据库中，旧版本会忽略它们，避免回滚过程删除任何已写入数据。

## Polymarket 重复记录维护

先预览，不写数据库：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  run --rm backend python scripts/cleanup_polymarket_duplicates.py
```

仅在备份和预览确认后执行：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  run --rm backend python scripts/cleanup_polymarket_duplicates.py --apply
```

命令只处理 `POLYMARKET` 已平仓记录，按稳定 outcome token 合并旧的
`asset:timestamp` 记录，保留最新一条并重算受影响日期的已实现收益。

## OKX 分批平仓重复记录维护

旧版本曾把 OKX `positions-history` 的 `uTime` 写进来源 ID，导致同一 `posId` 的部分
平仓和最终平仓显示为多条。先只读预览：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  exec -T backend python scripts/cleanup_okx_partial_closes.py
```

确认并完成数据库备份后执行：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  exec -T backend python scripts/cleanup_okx_partial_closes.py --apply
```

脚本按 `instType + posId` 分组，保留关闭时间最新的 OKX 累计记录、删除旧阶段快照，
规范化来源 ID，并使用账务流水重新计算受影响日期的已实现收益。它不会把阶段金额相加，
也不会处理其他交易所的数据。
