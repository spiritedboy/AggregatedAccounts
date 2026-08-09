# Atlas Ledger 生产部署手册

本文面向第一次接触 Atlas Ledger 的 Linux 运维人员。按顺序执行后，可在全新的
Ubuntu 24.04 LTS 服务器上完成 PostgreSQL、TimescaleDB、Docker、应用、Nginx、TLS、
备份、日志维护和升级回滚配置。

## 1. 部署约定与要求

| 项目 | 本文示例 |
|---|---|
| 域名 | `assets.example.com` |
| 项目目录 | `/opt/atlas-ledger/app` |
| 应用系统用户 | `atlas` |
| 数据库 / 用户 | `exchange_aggregator` / `atlas_app` |
| 应用源站 | `127.0.0.1:8000` |
| Docker 内部网段 | `172.30.42.0/24` |

请替换域名和密码。建议至少 2 vCPU、4 GB RAM、40 GB SSD。服务器需有公网域名、
root/sudo 权限、准确 NTP 时间，并能出站访问 GitHub、Docker Hub 和交易所 API。

公网只开放 SSH、80 和 443，不开放 5432、8000、8001 或 3000。

```bash
timedatectl status
df -h
free -h
```

## 2. 安装基础软件与 PostgreSQL 16

先添加 PostgreSQL 官方仓库，避免 Ubuntu 默认版本不一致：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git gnupg jq openssl cron logrotate
sudo install -d -m 0755 /usr/share/postgresql-common/pgdg
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
  | sudo gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo \"$VERSION_CODENAME\")-pgdg main" \
  | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update
sudo apt install -y postgresql-16 postgresql-client-16 postgresql-common
sudo systemctl enable --now postgresql
```

## 3. 安装 TimescaleDB

```bash
curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/timescaledb.gpg
echo "deb [signed-by=/usr/share/keyrings/timescaledb.gpg] https://packagecloud.io/timescale/timescaledb/ubuntu/ $(. /etc/os-release && echo \"$VERSION_CODENAME\") main" \
  | sudo tee /etc/apt/sources.list.d/timescaledb.list
sudo apt update
sudo apt install -y timescaledb-2-postgresql-16
sudo timescaledb-tune --quiet --yes
sudo systemctl restart postgresql
sudo -u postgres psql -Atqc \
  "SELECT default_version FROM pg_available_extensions WHERE name='timescaledb';"
```

最后一条命令必须输出版本号。再确认预加载：

```bash
sudo -u postgres psql -Atqc "SHOW shared_preload_libraries;"
```

输出应包含 `timescaledb`。

## 4. 创建数据库

先生成强密码：

```bash
openssl rand -base64 36
```

进入 PostgreSQL，并替换密码占位符：

```bash
sudo -u postgres psql
```

```sql
CREATE ROLE atlas_app LOGIN PASSWORD 'REPLACE_WITH_STRONG_PASSWORD';
CREATE DATABASE exchange_aggregator OWNER atlas_app;
\connect exchange_aggregator
CREATE EXTENSION IF NOT EXISTS timescaledb;
GRANT ALL ON SCHEMA public TO atlas_app;
\q
```

## 5. 允许容器访问宿主机数据库

应用使用固定 Docker 网段 `172.30.42.0/24`。定位配置文件：

```bash
sudo -u postgres psql -Atqc "SHOW config_file; SHOW hba_file;"
```

在 `postgresql.conf` 设置：

```conf
listen_addresses = '127.0.0.1,172.30.42.1'
```

在 `pg_hba.conf` 追加：

```conf
host  exchange_aggregator  atlas_app  172.30.42.0/24  scram-sha-256
```

然后重启：

```bash
sudo systemctl restart postgresql
sudo systemctl --no-pager --full status postgresql
sudo ss -lntp | grep 5432
```

如果 Docker 网桥尚未创建，PostgreSQL 可能无法绑定 `172.30.42.1`。可暂时使用
`listen_addresses='*'`，但必须通过 `pg_hba.conf` 和防火墙限制访问；应用首次启动创建
网桥后再改回明确地址。

## 6. 安装 Docker Engine 与 Compose

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
docker compose version
```

## 7. 获取代码

```bash
sudo useradd --system --create-home --home-dir /opt/atlas-ledger --shell /bin/bash atlas
sudo -u atlas git clone https://github.com/spiritedboy/AggregatedAccounts.git /opt/atlas-ledger/app
cd /opt/atlas-ledger/app
git rev-parse --short HEAD
git status --short
```

最后一条命令应无输出。

## 8. 创建生产 `.env`

```bash
sudo -u atlas cp .env.example .env
sudo -u atlas bash scripts/init-env.sh
sudo chmod 600 .env
sudo chown atlas:atlas .env
sudo -u atlas nano .env
```

生产关键配置：

```dotenv
APP_ENV=production
APP_ENCRYPTION_KEY=保留脚本自动生成的值
COOKIE_SECURE=true
DATABASE_URL=postgresql+asyncpg://atlas_app:URL_ENCODED_PASSWORD@host.docker.internal:5432/exchange_aggregator
DATABASE_URL_SYNC=postgresql+psycopg://atlas_app:URL_ENCODED_PASSWORD@host.docker.internal:5432/exchange_aggregator
TEST_DATABASE_URL=postgresql+asyncpg://atlas_app:URL_ENCODED_PASSWORD@host.docker.internal:5432/exchange_aggregator_test
DEMO_MODE=false
SYNC_BALANCE_SECONDS=60
SYNC_POSITION_SECONDS=15
SYNC_HISTORY_SECONDS=300
SYNC_CLOSED_POSITION_SECONDS=600
SYNC_HEALTH_SECONDS=60
SYNC_JOB_RETENTION_DAYS=0
BALANCE_SNAPSHOT_RETENTION_DAYS=0
EQUITY_CURVE_CACHE_SECONDS=30
MAINTENANCE_HOUR_UTC=4
MAINTENANCE_MINUTE_UTC=20
REQUEST_TIMEOUT_SECONDS=12
EXCHANGE_ACCOUNTS_CONFIG=/app/config/exchange_accounts.local.json
```

数据库密码必须 URL 编码：

```bash
python3 -c 'import urllib.parse; print(urllib.parse.quote(input("Password: "), safe=""))'
```

注意：

- `DEMO_MODE=false` 确保生产环境不生成测试数据
- 两个 retention 值为 `0` 时业务数据永久保留
- `APP_ENCRYPTION_KEY` 必须离线备份，并与数据库备份分开保存
- 丢失加密密钥会导致已保存的交易所凭证无法解密
- `.env` 不得提交 Git、复制到工单或输出到日志

## 9. 配置交易所账户

不要直接修改仓库跟踪的模板，否则后续 `git pull` 可能冲突。复制为已被 `.gitignore`
忽略的生产配置：

```bash
sudo -u atlas cp \
  backend/config/exchange_accounts.json \
  backend/config/exchange_accounts.local.json
sudo -u atlas nano backend/config/exchange_accounts.local.json
```

同一交易所的 `connection_name` 必须唯一。启用账户时只写环境变量名称：

```json
{
  "exchange": "OKX",
  "connection_name": "OKX 主账户",
  "enabled": true,
  "api_key_env": "OKX_API_KEY",
  "api_secret_env": "OKX_API_SECRET",
  "passphrase_env": "OKX_PASSPHRASE"
}
```

真实值写入 `.env`：

```dotenv
OKX_API_KEY=
OKX_API_SECRET=
OKX_PASSPHRASE=
HYPERLIQUID_WALLET_ADDRESS=0x...
POLYMARKET_WALLET_ADDRESS=0x...
```

中心化交易所 API 必须只允许读取，建议绑定服务器出口 IP。Hyperliquid 和 Polymarket
只使用公开钱包地址。详细权限见 [交易所 API 参考](exchange-api-reference.md)。

启用 Polymarket 大模型翻译时填写：

```dotenv
BAIDU_TRANSLATION_ENABLED=true
BAIDU_TRANSLATION_APPID=
BAIDU_TRANSLATION_API_KEY=
BAIDU_TRANSLATION_ENDPOINT=https://fanyi-api.baidu.com/ait/api/aiTextTranslate
```

## 10. 首次构建和启动

建议在有测试数据库的构建机执行验证：

```bash
make test-fast       # 无需 PostgreSQL：适配器、公式和前端测试
make test-exchanges  # 五个交易所专项测试
make test            # 发布前完整回归，需要 TEST_DATABASE_URL 可连接
```

生产 Compose 固定构建 backend 的 `runtime` 阶段，不会把测试源码、pytest、Ruff
或覆盖率工具打入运行镜像。

```bash
cd /opt/atlas-ledger/app
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/tmp/atlas-ledger-compose.yml
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml build
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

backend 启动前自动执行 `alembic upgrade head`，首次运行会创建表、索引、TimescaleDB
hypertable 和连续聚合。不要同时启动多个执行迁移的 backend 副本。

等待并验证：

```bash
sleep 20
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8000/api/health | jq .
```

backend、frontend、gateway 都应为 `healthy`。

## 11. 验证数据库初始化

```bash
sudo -u postgres psql -d exchange_aggregator -c "SELECT version_num FROM alembic_version;"
sudo -u postgres psql -d exchange_aggregator -c \
  "SELECT extname, extversion FROM pg_extension WHERE extname='timescaledb';"
sudo -u postgres psql -d exchange_aggregator -c \
  "SELECT hypertable_name FROM timescaledb_information.hypertables;"
sudo -u postgres psql -d exchange_aggregator -c \
  "SELECT view_name FROM timescaledb_information.continuous_aggregates;"
```

应存在 `portfolio_equity_points` hypertable 和四个组合净值连续聚合。

```bash
curl -fsS http://127.0.0.1:8000/api/accounts/bootstrap | jq .
```

首次接入时没有历史快照正常；等待一至两个同步周期后再检查页面。

## 12. 配置 Nginx 与 HTTPS

安装 Nginx 和 Certbot：

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

创建 `/etc/nginx/sites-available/atlas-ledger`：

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name assets.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/atlas-ledger /etc/nginx/sites-enabled/atlas-ledger
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
curl -I http://assets.example.com
sudo certbot --nginx -d assets.example.com
sudo certbot renew --dry-run
curl -fsS https://assets.example.com/api/health | jq .
```

Cloudflare 不应缓存 `/api/*`。HTML 应绕过缓存或使用短 TTL；带内容哈希的
`/_next/static/*` 可以长期缓存。

## 13. 防火墙

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status verbose
sudo ss -lntp
```

确认 8000 只监听 `127.0.0.1`，5432 没有监听公网地址。

## 14. 每日备份与恢复验证

脚本会创建 custom-format 备份、SHA-256 校验，并恢复到随机临时数据库验证完整性，
最后删除临时库和超过 90 天的备份。

恢复验证需要创建临时数据库及 TimescaleDB 扩展。创建一个仅供宿主机备份脚本使用的独立
角色，不要给应用角色提权：

```bash
openssl rand -base64 36
sudo -u postgres psql -c \
  "CREATE ROLE atlas_backup LOGIN SUPERUSER PASSWORD 'REPLACE_WITH_SEPARATE_BACKUP_PASSWORD';"
```

此角色权限很高，只允许从本机 `127.0.0.1` 使用；不得写入应用 `.env`、不得用于应用
`DATABASE_URL`，也不得开放远程访问。创建独立备份环境文件：

```bash
sudo install -m 0600 -o root -g root /dev/null /etc/atlas-ledger-backup.env
sudo nano /etc/atlas-ledger-backup.env
```

内容如下，密码需要 URL 编码：

```dotenv
BACKUP_DATABASE_URL=postgresql://atlas_backup:URL_ENCODED_BACKUP_PASSWORD@127.0.0.1:5432/exchange_aggregator
BACKUP_DIR=/var/backups/aggregated-accounts
BACKUP_RETENTION_DAYS=90
BACKUP_VERIFY_RESTORE=1
```

```bash
sudo install -d -m 0700 -o atlas -g atlas /var/backups/aggregated-accounts
sudo ENV_FILE=/etc/atlas-ledger-backup.env ./scripts/backup-postgres.sh
sudo ls -lh /var/backups/aggregated-accounts
sudo BACKUP_ENV_FILE=/etc/atlas-ledger-backup.env ./scripts/install-backup-cron.sh
sudo cat /etc/cron.d/aggregated-accounts-backup
sudo systemctl enable --now cron
```

高安全环境可进一步使用 sudo/peer authentication 或外部备份系统替代密码型超级用户，
但必须保留“实际恢复到独立数据库并验证”的步骤，不能只检查 `pg_dump` 是否退出成功。

备份保留 90 天只影响备份文件，生产数据库业务数据仍永久保留。

## 15. 日志和 Docker 缓存

项目容器使用 journald。编辑 `/etc/systemd/journald.conf`：

```ini
[Journal]
MaxRetentionSec=7day
SystemMaxUse=1G
```

```bash
sudo systemctl restart systemd-journald
sudo journalctl --vacuum-time=7d
sudo ./scripts/install-docker-cache-maintenance.sh
sudo ./scripts/prune-docker-build-cache.sh
```

缓存脚本将构建缓存控制在约 5 GB，不删除运行中的容器、镜像或卷。不要运行
`docker system prune --volumes`。

查看日志：

```bash
sudo journalctl -t atlas-ledger-backend -f
sudo journalctl -t atlas-ledger-frontend -f
sudo journalctl -t atlas-ledger-gateway -f
sudo journalctl -u nginx --since today
sudo journalctl -u postgresql --since today
```

## 16. 开机自启动

容器配置了 `restart: unless-stopped`。启用宿主机服务：

```bash
sudo systemctl enable docker postgresql nginx cron
sudo systemctl is-enabled docker postgresql nginx cron
```

可安排重启测试，重新登录后执行：

```bash
cd /opt/atlas-ledger/app
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8000/api/health
```

## 17. 日常无损升级

```bash
cd /opt/atlas-ledger/app

# 记录版本和迁移状态
git rev-parse HEAD
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
sudo -u postgres psql -d exchange_aggregator -Atqc "SELECT version_num FROM alembic_version;"

# 先创建并恢复验证备份
sudo ENV_FILE=/etc/atlas-ledger-backup.env ./scripts/backup-postgres.sh

# 确认服务器无本地代码改动，再仅快进更新
sudo -u atlas git status --short
sudo -u atlas git pull --ff-only origin main

# 构建并更新，backend 自动执行增量迁移
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml build backend frontend gateway
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 验证
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8000/api/health | jq .
curl -fsS https://assets.example.com/api/health | jq .
```

不要使用 `git reset --hard`、删除 PostgreSQL 数据目录、重新创建生产数据库或执行
`docker compose down -v`。

## 18. 回滚原则

优先只回滚应用代码和镜像，不执行 Alembic downgrade：

```bash
cd /opt/atlas-ledger/app
git log --oneline -10
sudo -u atlas git checkout PREVIOUS_COMMIT
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml build backend frontend gateway
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
curl -fsS http://127.0.0.1:8000/api/health
```

直接降级数据库可能删除新数据。只有数据库损坏且无法前向修复时才从备份恢复；恢复前应
停止应用、保留故障库，并先在独立数据库验证备份，不能覆盖唯一生产库。

## 19. 故障排查

### 容器不健康

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
sudo journalctl -t atlas-ledger-backend -n 200 --no-pager
sudo journalctl -t atlas-ledger-frontend -n 200 --no-pager
sudo journalctl -t atlas-ledger-gateway -n 200 --no-pager
```

gateway 会等待 backend 和 frontend 健康，应先检查两个上游。

### backend 无法连接 PostgreSQL

```bash
sudo systemctl status postgresql
sudo ss -lntp | grep 5432
sudo grep -n '172.30.42.0/24' /etc/postgresql/16/main/pg_hba.conf
sudo docker run --rm --network exchange-portfolio_internal \
  --add-host=host.docker.internal:host-gateway \
  postgres:16-alpine pg_isready -h host.docker.internal -p 5432
```

检查数据库 URL 编码、密码、`listen_addresses`、`pg_hba.conf` 和 Docker 网段。

### 迁移失败

```bash
sudo journalctl -t atlas-ledger-backend -n 300 --no-pager
sudo -u postgres psql -d exchange_aggregator -c "SELECT version_num FROM alembic_version;"
```

不要删除数据库重试。先保存日志和备份，确认失败迁移是否已部分执行。

### 页面没有账户或数据

- JSON 账户必须为 `enabled: true`
- JSON 引用的环境变量必须在 `.env` 有值
- 中心化交易所 API 必须只读并绑定正确出口 IP
- 修改后重启 backend 并查看日志

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps backend
sudo journalctl -t atlas-ledger-backend -f
```

平仓统计要在交易所历史同步后更新。默认平仓同步周期 10 分钟，浏览器每 60 秒刷新；
上游历史接口本身也可能延迟。

### 磁盘增长

```bash
df -h
sudo du -sh /var/lib/postgresql /var/backups/aggregated-accounts
sudo journalctl --disk-usage
sudo docker system df
```

可清理过期日志、90 天前备份和 Docker 构建缓存，不能删除 PostgreSQL 数据文件。

## 20. 上线验收清单

- [ ] 域名 HTTPS 正常，证书自动续期通过
- [ ] gateway 仅监听 `127.0.0.1:8000`
- [ ] 5432、3000、8001 未暴露公网
- [ ] backend、frontend、gateway 均为 `healthy`
- [ ] `/api/health` 返回数据库已连接
- [ ] Alembic、TimescaleDB hypertable 和连续聚合正常
- [ ] `DEMO_MODE=false`，页面没有测试数据
- [ ] 启用账户符合预期，中心化交易所 API 均为只读
- [ ] 当前仓位、历史仓位、流水、收益分析和净值曲线能读取
- [ ] `.env` 权限为 600，未被 Git 跟踪
- [ ] `APP_ENCRYPTION_KEY` 已离线保存且与数据库备份分离
- [ ] 手工数据库备份和临时库恢复验证成功
- [ ] 每日备份、7 天日志和 Docker 缓存维护已安装
- [ ] Docker、PostgreSQL、Nginx、cron 均已开机启动
- [ ] `make security-check` 通过

全部完成后，部署才算结束。
