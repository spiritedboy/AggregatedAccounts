# Atlas Ledger

Atlas Ledger 是一个公开只读的多交易所资产聚合平台，将 Binance、OKX、Bitget、
Hyperliquid 和 Polymarket 的账户权益、余额、当前仓位、历史仓位、财务流水与收益分析
汇总到同一个响应式 Web 看板。

平台只读取账户数据，不提供下单、撤单、平仓、划转、提币或修改杠杆能力。中心化交易所
必须使用只读 API；Hyperliquid 和 Polymarket 仅使用公开钱包地址。

生产环境示例：[https://www.bitboy.cn](https://www.bitboy.cn)

## 核心能力

- 聚合 Binance、OKX、Bitget、Hyperliquid、Polymarket 五个平台
- 账户权益、逐资产余额、当前仓位、历史仓位和财务流水统一展示
- 已实现收益、资金费、手续费和充值提现分开核算
- 累计净收益、当前持仓收益、日/周/月收益与五分钟净值曲线
- 交易胜率、平均盈亏、盈亏比、盈利因子、最大单笔盈亏
- 做多/做空笔数、净收益、胜率、平均盈利与平均亏损对比
- 权益口径与交易口径对账，以及回撤、集中度、保证金和强平风险
- Polymarket 市场标题通过百度 LLM 翻译为简体中文并持久化复用
- USD/CNY 前端显示切换，汇率不写入数据库
- 深浅主题、响应式布局、60 秒自动刷新与数据过期提示
- 配置文件管理账户；网站不提供添加或删除账户入口
- 定时同步、幂等写入、账户级失败隔离和八维数据完整性标记
- PostgreSQL + TimescaleDB 五分钟净值时序、连续聚合与读取缓存
- 每日数据库备份、恢复验证、90 天备份保留和 7 天日志维护工具

## 页面与统计口径

页面包括资产总览、当前仓位、历史仓位、收益分析、账务流水、风险与对账、交易所账户。

```text
累计净收益 = 已实现毛收益 + 资金费 - 手续费
当前持仓收益 = 当前仓位未实现盈亏之和
权益口径收益 = 当前权益 - 统计期初权益 - 净充值提现
交易净收益 = 已实现收益 + 资金费 - 手续费
当前仓位收益率 = 当前未实现盈亏 ÷ 仓位本金 × 100%
历史仓位收益率 = 净收益 ÷ 仓位本金 × 100%
```

历史仓位缺少可靠杠杆和本金时，页面不会猜测杠杆收益率，而是按多空方向展示开仓价到
平仓价的价格变动。交易质量和多空分析均使用历史仓位净收益，已经计入资金费和手续费；
每次新平仓同步入库后自动重新计算。

## 架构

```text
浏览器
  │ HTTPS
  ▼
宿主机 Nginx / CDN
  │ 127.0.0.1:8000
  ▼
gateway (Nginx，唯一发布端口)
  ├─ /api/* ─► backend:8001 (FastAPI + APScheduler)
  └─ /*     ─► frontend:3000 (Next.js)
                       │
                       ▼
         宿主机 PostgreSQL 16 + TimescaleDB
         通过 host.docker.internal 访问
```

三个应用服务使用内部 Docker 网络。生产覆盖文件只将 gateway 发布到
`127.0.0.1:8000`，backend、frontend 和 PostgreSQL 均不直接暴露到公网。

## 技术栈

- 后端：Python 3.12、FastAPI、SQLAlchemy 2、Alembic、APScheduler
- 前端：Next.js 16、React、TypeScript、Tailwind CSS、ECharts
- 数据库：PostgreSQL 16、TimescaleDB
- 运行：Docker Engine、Docker Compose、Nginx
- 测试：pytest、Vitest、Testing Library、ESLint、Ruff

## 快速开始

全新服务器请直接阅读 [生产部署手册](docs/deployment.md)。本地开发需要 Docker、
Docker Compose、PostgreSQL 16 和 TimescaleDB：

```bash
git clone git@github.com:spiritedboy/AggregatedAccounts.git
cd AggregatedAccounts
cp .env.example .env
bash scripts/init-env.sh
# 编辑 .env 中的数据库连接和账户凭证
make dev-up
```

访问 `http://127.0.0.1:8000`，健康检查为
`http://127.0.0.1:8000/api/health`。网站为公开只读模式，不需要访问密码。

`.env` 已被 Git 忽略，不得提交数据库密码、交易所密钥或翻译服务凭证。

## 配置交易所账户

仓库模板位于 `backend/config/exchange_accounts.json`。部署时复制为 Git 忽略的本地配置，
避免后续升级与服务器修改冲突：

```bash
cp backend/config/exchange_accounts.json backend/config/exchange_accounts.local.json
```

将本地配置中需要的账户设为 `"enabled": true`，在 `.env` 填写模板引用的环境变量，
并设置 `EXCHANGE_ACCOUNTS_CONFIG=/app/config/exchange_accounts.local.json`。

```json
{
  "exchange": "BINANCE",
  "connection_name": "Binance 默认账户",
  "enabled": true,
  "api_key_env": "BINANCE_API_KEY",
  "api_secret_env": "BINANCE_API_SECRET"
}
```

JSON 只能写环境变量名称，不能写真实密钥。账户配置加载是幂等的，不会因重启删除历史
数据。修改配置后重启 backend：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps backend
```

交易所权限、钱包地址和翻译配置见
[交易所 API 参考](docs/exchange-api-reference.md)。

## 默认同步周期

| 数据 | 默认周期 |
|---|---:|
| 当前仓位 | 15 秒 |
| 账户余额 | 60 秒 |
| 账务历史 | 5 分钟 |
| 已平仓仓位 | 10 分钟 |
| 同步健康状态 | 60 秒 |
| 浏览器页面刷新 | 60 秒 |

同步周期可在 `.env` 调整。业务数据库默认永久保留；备份默认保留 90 天，日志建议保留
7 天。

## 常用命令

```bash
make prod-up          # 生产构建、迁移和启动
make dev-up           # 本地构建、迁移和启动
make test-fast        # 无需数据库的后端快速测试 + 前端测试
make test-exchanges   # 五个交易所适配器专项测试
make test             # 完整回归测试（需要测试数据库）
make lint             # Ruff 和 ESLint
make security-check   # 密钥、SQLite 和交易写操作检查

docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8000/api/health
./scripts/backup-postgres.sh
```

生产后端镜像使用独立的 `runtime` 构建阶段，不包含 `tests/`、pytest、Ruff 或覆盖率工具；
测试源码仍保留在仓库中，用于快速检查、交易所专项测试和发布前完整回归。

## 数据安全

- API 凭证由环境变量注入，保存时使用 AES-256-GCM 分字段加密
- `APP_ENCRYPTION_KEY` 必须与数据库备份分开保管；丢失后已保存凭证无法解密
- API 响应不返回 Secret、Passphrase、密文、Nonce 或认证标签
- 写接口在公开模式下禁用，项目不包含交易实现
- PostgreSQL、backend 和 frontend 不应发布公网端口
- 部署前运行 `make security-check`

## 项目结构

```text
backend/                 FastAPI、适配器、模型、迁移和后端测试
frontend/                Next.js 页面、组件和前端测试
gateway/                 容器内反向代理
backend/config/          交易所账户配置模板
docs/                    部署和交易所 API 文档
scripts/                 备份、检查、缓存与安全维护脚本
docker-compose.yml       基础服务定义
docker-compose.dev.yml   本地端口覆盖
docker-compose.prod.yml  生产端口与安全配置
```

## 文档

- [生产部署手册](docs/deployment.md)
- [交易所 API 参考](docs/exchange-api-reference.md)

## 免责声明

本项目只提供资产和统计信息展示，不构成投资建议。交易所接口覆盖、网络故障、权限配置和
上游数据延迟都可能造成短时缺失；应同时关注页面的数据完整性与来源标记。
