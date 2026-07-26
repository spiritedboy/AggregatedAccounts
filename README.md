# Atlas Ledger：多交易所账户资产聚合平台

Atlas Ledger 是面向个人使用的只读数字资产看板，将 Binance、OKX、Bitget、
Hyperliquid 与 Polymarket 的账户权益、余额、仓位和统计周期收益聚合到一个响应式
Web 界面。
项目不包含下单、撤单、平仓、划转、提币、修改杠杆或其他交易能力。

## 已实现

- 无访问密码的公开只读页面与 API；账户增删和批量写操作统一禁用
- 仓库内五平台账户配置模板，敏感凭证只通过环境变量注入
- API Key、Secret 和 Passphrase 使用 AES-256-GCM 分字段认证加密
- Hyperliquid 与 Polymarket 只接收公开钱包/Profile 地址，不接收私钥、助记词或密码
- 凭证响应严格脱敏；密文、Nonce、认证标签和主密钥不会返回前端
- 每个连接独立的 `tracking_started_at`、初始权益快照和初始仓位收益基线
- 15 张以上 PostgreSQL 业务、安全和同步表，包含索引、唯一约束和幂等来源 ID
- Binance、OKX、Bitget、Hyperliquid 和 Polymarket 独立只读 Adapter
- 账户摘要、余额、当前仓位、历史仓位、日/周/月收益和交易所收益贡献 API
- 历史仓位 CSV 导出及公式注入防护
- APScheduler 定时同步、账户级互斥、隔离失败、耗时/记录数/安全错误日志
- Server-Sent Events 同步心跳
- 四交易所 Demo 账户、真实 Polymarket 账户接入、当前仓位、历史仓位和 30 天净值数据
- 深浅主题、金额隐藏、桌面侧栏和移动端底部导航
- 数据页面每 60 秒自动刷新；超过 120 秒未获得新数据时显示过期提示并持续重试
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

网站不需要登录或访问密码。`.env` 仍被 Git 忽略，用于数据库连接、主加密密钥和
交易所凭证环境变量；不要将任何密钥复制到文档、提交或日志中。

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

## 配置交易所账户

账户模板位于 `backend/config/exchange_accounts.json`，仓库中已经包含 Binance、
OKX、Bitget、Hyperliquid 和 Polymarket 五个平台的默认值，默认均为
`"enabled": false`。启用账户时：

1. 将对应配置项改为 `"enabled": true`。
2. 在服务器 `.env` 中填写配置项引用的环境变量。
3. 重启 backend。

示例：

```json
{
  "exchange": "BINANCE",
  "connection_name": "Binance 默认账户",
  "enabled": true,
  "api_key_env": "BINANCE_API_KEY",
  "api_secret_env": "BINANCE_API_SECRET"
}
```

真实 API Key、Secret 和 Passphrase 不写入 JSON，也不提交 Git。启动时平台先调用
只读接口测试连接并检查权限；检测到交易、划转或提币权限时拒绝创建。配置加载是
幂等的：同交易所、同连接名称的启用账户会保留，不会删除现有账户或历史数据。

Polymarket 使用公开 Data API 和 Accounting Snapshot，不需要 API Key。请填写
Polymarket 的登录钱包或 Profile / Proxy Wallet 地址，系统会自动解析实际的
Profile 地址；平台不会请求或保存钱包私钥、助记词或登录密码。总权益来自
Accounting Snapshot 的 `equity`，可用余额来自
`cashBalance`，预测市场持仓价值来自 `positionsValue`。

“交易所账户”页面不提供添加或删除按钮，保留连接测试和立即同步。

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

Polymarket 当前持仓显示官方 `cashPnl`，因此添加账户之前已经产生的完整浮盈亏也会
保留；“统计期变化”仍只计算添加账户后的变化。已平仓接口不提供可靠的原始开仓时间，
因此这类记录使用统计起点并标记为 `PARTIAL`。若统计期发生外部充值或提现，在资金
流水无法从公开接口完整确认时，收益完整性同样保持为 `PARTIAL`，不会把入金猜成盈利。

## 页面刷新与数据时效

资产总览（含 30 天净值曲线）、当前仓位、收益分析、历史仓位和交易所账户页面会每
60 秒重新请求当前筛选条件下的数据，并显示下一次刷新倒计时。总览、持仓和账户页面
优先使用服务端同步时间判断数据新鲜度；其余页面使用最近一次成功请求时间。超过
120 秒没有新数据时，页面显示“数据已过期”并继续自动重试。切回长时间处于后台的
浏览器标签页时，如果已经错过刷新时间，会立即补发一次请求。

## 测试与质量

所有后端集成测试使用 `exchange_aggregator_test` PostgreSQL 数据库，不使用
SQLite。

```bash
make lint
make test
make security-check
```

后端覆盖配置加载、凭证加密、篡改检测、脱敏、Symbol 标准化、收益公式、字段校验、
公开只读限制、Demo 查询、仓位筛选和 CSV。前端覆盖总览、当前仓位、历史仓位、
收益、只读账户页、移动导航和主题持久化。

## 安全说明

- 主加密密钥只通过 `.env` 注入 backend，不进入数据库或镜像
- AES-GCM 使用每字段随机 96 位 Nonce 和 128 位认证标签
- 网站不创建登录会话；账户增删与批量写接口在公开模式下统一拒绝
- Nginx 限制请求体、隐藏版本并添加浏览器安全响应头
- API 错误、同步错误与健康检查不包含凭证或数据库 URL
- 账户配置加载不会删除已有连接、凭证或历史统计数据
- Docker 网络固定为 `172.30.42.0/24`，便于 PostgreSQL 最小授权

更多资料：

- [部署文档](docs/deployment.md)
- [交易所只读 API 依据](docs/exchange-api-reference.md)
