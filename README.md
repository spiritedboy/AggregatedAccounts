# Atlas Ledger：多交易所账户资产聚合平台

Atlas Ledger 是面向个人使用的只读数字资产看板，将 Binance、OKX、Bitget 与
Hyperliquid 的账户权益、余额、仓位和统计周期收益聚合到一个响应式 Web 界面。
项目不包含下单、撤单、平仓、划转、提币、修改杠杆或其他交易能力。

## 已实现

- 单访问密码登录、登录限频、HttpOnly 会话 Cookie、SameSite=Lax 与 CSRF 防护
- API Key、Secret 和 Passphrase 使用 AES-256-GCM 分字段认证加密
- Hyperliquid 只接收公开钱包地址，不接收私钥、助记词或密码
- 凭证响应严格脱敏；密文、Nonce、认证标签和主密钥不会返回前端
- 每个连接独立的 `tracking_started_at`、初始权益快照和初始仓位收益基线
- 15 张以上 PostgreSQL 业务、安全和同步表，包含索引、唯一约束和幂等来源 ID
- Binance、OKX、Bitget 和 Hyperliquid 独立只读 Adapter
- 账户摘要、余额、当前仓位、历史仓位、日/周/月收益和交易所收益贡献 API
- 历史仓位 CSV 导出及公式注入防护
- APScheduler 定时同步、账户级互斥、隔离失败、耗时/记录数/安全错误日志
- Server-Sent Events 同步心跳
- 四交易所 Demo 账户、当前仓位、历史仓位和 30 天净值数据
- 深浅主题、金额隐藏、桌面侧栏和移动端底部导航
- 375px、768px 和 1440px 重点响应式布局
- 本地与生产 Compose 覆盖文件、三服务健康检查和内部 Docker 网络

## 架构

```text
Windows 浏览器
    ↓ http://172.26.95.199:8000
gateway (nginx:alpine, 唯一暴露端口)
    ├── /api/* → backend:8001 (FastAPI)
    └── /*     → frontend:3000 (Next.js)
                         ↓
              WSL 宿主机 PostgreSQL:5432
              via host.docker.internal
```

PostgreSQL 不在 Docker 中。`backend` 和 `frontend` 不发布宿主机端口，只有
`gateway` 在开发环境发布 `0.0.0.0:8000`，生产环境仅发布
`127.0.0.1:8000`。

## 快速启动

项目当前目录位于 WSL Linux 文件系统：

```text
/home/yyf/codex/AggregatedAccounts
```

首次或日常本地启动：

```bash
make dev-up
```

这个目标会检查 Docker/Compose、初始化缺失的本地密钥、验证正式库和测试库、
验证容器访问 PostgreSQL、构建镜像、执行 Alembic 迁移、启动服务，并检查本机和
WSL IP 地址。

也可以执行标准 Compose 命令：

```bash
docker compose up -d --build
```

或显式指定开发覆盖文件：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  up -d --build
```

访问：

- 平台：`http://172.26.95.199:8000`
- 健康检查：`http://172.26.95.199:8000/api/health`
- WSL 本机：`http://127.0.0.1:8000`

本地访问密码保存在权限为 `600` 的 `.env` 文件中：

```bash
grep '^APP_ACCESS_PASSWORD=' .env
```

`.env` 被 Git 忽略。不要将该密码或任何密钥复制到文档、提交或日志中。

## 常用命令

```bash
make init
make build
make up
make down
make restart
make logs
make ps
make migrate
make test
make lint
make dev-up
make prod-up
make health
make security-check
```

## 添加 API Key

登录后打开导航中的“交易所账户”，点击“添加账户”：

- Binance：连接名称、API Key、API Secret
- OKX：连接名称、API Key、API Secret、Passphrase
- Bitget：连接名称、API Key、API Secret、Passphrase
- Hyperliquid：连接名称、42 位公开钱包地址

平台先调用只读接口测试连接并尽量检查权限。检测到现货交易、合约交易、划转或
提币权限时拒绝保存。成功后才创建统计周期、加密凭证和保存初始快照。

敏感字段不会写入 localStorage、sessionStorage 或 URL，成功提交后表单状态会
被清空。

## 统计规则

统计起点是连接测试成功且凭证加密保存完成后的服务器时间。平台不会读取、同步、
保存、展示或统计该时间之前的数据。

```text
净资金流 = 充值 - 提现
统计周期投资收益 = 当前权益 - 初始权益 - 净资金流
交易净收益 = 已实现收益 + 资金费 - 手续费
初始仓位未实现收益变化 = 当前未实现收益 - 添加时未实现收益
```

交易所覆盖不足时显示“统计不完整”，本地重建历史仓位标记为
`RECONSTRUCTED`，不会伪装成交易所原始数据。

## 测试与质量

所有后端集成测试使用 `exchange_aggregator_test` PostgreSQL 数据库，不使用
SQLite。

```bash
make lint
make test
make security-check
```

后端覆盖凭证加密、篡改检测、脱敏、Symbol 标准化、收益公式、字段校验、认证、
CSRF、Demo 查询、仓位筛选和 CSV。前端覆盖登录、总览、当前仓位、历史仓位、
收益、账户凭证表单、移动导航和删除确认。

## 安全说明

- 主加密密钥只通过 `.env` 注入 backend，不进入数据库或镜像
- AES-GCM 使用每字段随机 96 位 Nonce 和 128 位认证标签
- 会话令牌和 CSRF 令牌在 PostgreSQL 中只保存 SHA-256 摘要
- Nginx 限制请求体、隐藏版本并添加浏览器安全响应头
- API 错误、同步错误与健康检查不包含凭证或数据库 URL
- 删除连接会删除所有凭证密文并立即停止启用中的统计周期
- Docker 网络固定为 `172.30.42.0/24`，便于 PostgreSQL 最小授权

更多资料：

- [部署文档](docs/deployment.md)
- [交易所只读 API 依据](docs/exchange-api-reference.md)
