# Atlas Ledger：多交易所账户资产聚合平台

Atlas Ledger 是面向个人使用的只读数字资产看板，将 Binance、OKX、Bitget、
Hyperliquid 与 Polymarket 的账户权益、余额、仓位和统计周期收益聚合到一个响应式
Web 界面。
项目不包含下单、撤单、平仓、划转、提币、修改杠杆或其他交易能力。

## 已实现

- 无访问密码的公开只读页面与 API；账户增删、连接测试和手动同步入口统一禁用
- 仓库内五平台账户配置模板，敏感凭证只通过环境变量注入
- API Key、Secret 和 Passphrase 使用 AES-256-GCM 分字段认证加密
- Hyperliquid 与 Polymarket 只接收公开钱包/Profile 地址，不接收私钥、助记词或密码
- 凭证响应严格脱敏；密文、Nonce、认证标签和主密钥不会返回前端
- 每个连接独立的 `tracking_started_at`、初始权益快照和初始仓位收益基线
- PostgreSQL 业务、安全和同步表，包含索引、唯一约束和幂等来源 ID；净值时序使用
  TimescaleDB hypertable 与连续聚合
- Binance、OKX、Bitget、Hyperliquid 和 Polymarket 独立只读 Adapter
- Adapter 契约测试强制五个平台实现已平仓能力；不支持的数据流必须显式声明，禁止静默空实现
- Binance 总权益覆盖现货与 USDⓈ-M，Bitget 覆盖现货、USDT 合约与 USDC 合约
- Binance 当前仓位使用保留杠杆和保证金模式字段的 Position Information V2，
  包括 GOOGL 等 TradFi 永续合约
- Hyperliquid 自动发现默认永续与全部 HIP-3 DEX（如 `xyz:CXMT`）；统一账户以
  Spot clearinghouse 为唯一余额口径，非 USDC 现货按官方 Spot 市场价格折算
- 账户摘要、逐资产余额、当前仓位、持仓快照、历史仓位、日/周/月收益和交易所收益贡献 API
- 历史仓位 CSV 导出及公式注入防护
- 五个平台的已平仓仓位均按原始记录或可审计成交重建结果幂等同步
- APScheduler 定时同步、账户级互斥、隔离失败、耗时/记录数/安全错误日志
- Binance、OKX、Bitget、Hyperliquid 的已实现收益、资金费、手续费和资金流幂等同步
- 账务流水页面：交易所/类型/日期筛选、分页、汇总卡片和 CSV 导出
- 当前仓位的仓位价值、未实现盈亏，以及历史仓位净收益、账务流水账务影响，
  支持在当前筛选结果内前端升序、降序排序
- 仓位方向统一显示为“做多 / 做空”，Polymarket 市场仓位保持显示“持有”
- 八维数据完整性：权益、逐资产余额、当前仓位、已平仓仓位、已实现收益、资金费、手续费、
  资金流分别展示状态；发现过的不完整流水不会被后续空窗口覆盖
- 账户级同步状态中心：最近成功时间、耗时、写入量、连续失败与安全错误摘要
- Server-Sent Events 同步心跳
- 四交易所 Demo 账户、真实 Polymarket 账户接入、当前仓位、历史仓位和净值数据
- Polymarket 已平仓记录使用稳定 outcome token 幂等，并提供可预览的重复数据清理
- 权益变化/资金流/交易收益对账，以及最大回撤、集中度、保证金和强平距离指标
- PostgreSQL 每日最小权限备份、SHA-256 校验、临时库恢复验证和 90 天保留
- 生产数据库业务数据永久保留；`0` 保留值显式禁用同步任务及高频快照自动删除
- 项目容器日志进入 journald，宿主机项目、Nginx 与 PostgreSQL 文件日志保留 7 天
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
              WSL 宿主机 PostgreSQL 16 + TimescaleDB
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

Polymarket 市场标题可通过百度“LLM 大模型翻译”转换为简体中文。翻译仅在后端同步后
异步执行，结果按官方 outcome token 持久化缓存；当前仓位和平仓后的历史仓位复用
同一译文，不会因翻页、筛选或平仓重复请求翻译服务。页面同时保留英文原文和“AI译”
标识，翻译失败时安全回退英文，不影响账户同步。启用时只在未提交的 `.env` 中填写：

```dotenv
BAIDU_TRANSLATION_ENABLED=true
BAIDU_TRANSLATION_APPID=
BAIDU_TRANSLATION_API_KEY=
```

应用代码、数据库与 API 响应均不会返回翻译凭证。

“交易所账户”页面只展示配置、权限和同步状态，不提供添加、删除、连接测试或手动
同步。对应 POST API 在公开模式下同样返回 `403`；后台定时同步不受影响。

“同步状态中心”位于交易所账户页面，按账户展示最近一次任务结果、耗时、写入量、
最后成功时间、数据是否过期和连续失败次数。本项目按要求不发送邮件、Telegram 或
Webhook 通知。

## 统计规则

统计起点是连接测试成功且凭证加密保存完成后的服务器时间。平台不会把统计起点前已经
结束的仓位或账务流水计入本期收益；为准确展示统计期内才平掉的初始仓位，交易所返回的
开仓时间、入场均价和全周期成本仍会作为该平仓记录的一部分保存。

```text
净资金流 = 充值 - 提现
统计周期投资收益 = 当前权益 - 初始权益 - 净资金流
交易净收益 = 已实现收益 + 资金费 - 手续费
初始仓位未实现收益变化 = 当前未实现收益 - 添加时未实现收益
单日投资收益 = 当日累计投资收益 - 前一日累计投资收益
周/月投资收益 = 对应周期内单日投资收益之和
```

资产总览净值曲线使用独立的组合级时序数据。账户同步完成后，同一 5 分钟时间桶只保留
一个最新组合净值点；重复同步使用幂等更新，不会重复累计。时间范围均为滚动窗口：

- `1日`：最近 24 小时，读取 5 分钟原始点；
- `1周`：最近 7 天，读取 30 分钟连续聚合；
- `1月`：从当前时刻向前 1 个自然月，读取 2 小时连续聚合；
- `半年`：从当前时刻向前 6 个自然月，读取 6 小时连续聚合；
- `1年`：从当前时刻向前 12 个自然月，读取 12 小时连续聚合。

底层原始采样始终为 5 分钟。页面“净值变化”取当前范围内最后一个返回点减第一个返回点，
百分比以第一个点为基准；正数显示绿色，负数显示红色。曲线接口使用 30 秒进程内缓存，
不依赖 Redis。

交易所覆盖不足时显示“统计不完整”，本地重建历史仓位标记为
`RECONSTRUCTED`，不会伪装成交易所原始数据。

逐资产余额会随每分钟同步写入 `asset_balance_snapshots`；当前持仓同时写入
`position_snapshots`，用于审计数量、标记价格和未实现收益的历史变化。首次升级到完整
资产覆盖时，系统会把以前未纳入的 Binance/Bitget 资产加入初始基线，避免部署升级本身
制造一笔虚假收益。

OKX 已平仓仓位来自官方 `account/positions-history`，同时拉取永续与交割合约；Bitget
来自 `mix/position/history-position`，覆盖 USDT 与 USDC 合约。两者均只保存当前统计
周期开始后关闭的仓位，并使用仓位 ID、产品类型和关闭时间组成幂等来源 ID。

Hyperliquid 自动读取 `perpDexs` 并逐个查询默认永续和 HIP-3 DEX 的持仓；`xyz:CXMT`
会保留 DEX 来源，同时展示为 `CXMT-USDT-PERP`。已平仓数据根据官方
`userFillsByTime` 的 `startPosition` 重建从开仓到仓位归零的周期，并将同周期资金费和
USDC 手续费纳入净收益；页面明确标为“交易所成交重建”，不再误写成“本地重建”。
统计开始时已经存在的仓位会使用平仓成交的 `closedPnl` 反推入场均价并标记 `PARTIAL`。
Binance 根据 USDⓈ-M `userTrades` 的成交
方向、`positionSide` 和逐笔 `realizedPnl` 重建单向或双向持仓周期。由于 Binance
成交记录没有原生仓位周期 ID，且资金费不能可靠分配给同时存在的多空两侧，重建结果
统一标记 `RECONSTRUCTED / PARTIAL`；资金费仍在账务流水和收益汇总中独立准确统计。

Polymarket 使用官方 closed positions 数据，并按 outcome token 生成稳定幂等 ID。

中心化交易所和 Hyperliquid 每 5 分钟补拉一次账务流水，并与每分钟资产/持仓刷新
分开处理。账务流水按交易所原始 ID 幂等写入：已实现收益进入 `income_records`，
资金费、交易手续费和出入金分别进入对应记录表。任一账务接口失败时，本轮资产与仓位
仍可成功更新，但账户完整性会降为 `PARTIAL`，避免把缺失流水误报为完整数据。

Hyperliquid 会先读取 `userAbstraction`。统一账户和组合保证金账户按官方规则以
`spotClearinghouseState` 为唯一余额来源，避免把各 HIP-3 DEX 的虚拟账户权益重复
相加；标准账户才汇总各 DEX `accountValue` 与 Spot 余额。所有模式都会汇总各 DEX 的
保证金和未实现收益。Spot USDC 按 1 美元计价，其他代币通过官方
`spotMetaAndAssetCtxs` 市场价格换算。HyperCore 的 `send`、充值、提现和账户间划转
均会按钱包方向归一化为转入或转出，外部入金不会被误算为交易收益。

“账务流水”页面联合展示四类记录，并统一转换为对权益的正负影响：收益、收到的资金费
和转入显示为正数，手续费和转出显示为负数。页面支持交易所、流水类型和日期筛选，
最多导出当前筛选条件下的 10,000 条 CSV 记录。

如需对适配器新增的账务类型补拉既有统计周期，可先预览、再幂等应用：

```bash
docker compose exec backend python scripts/backfill_accounting_history.py \
  --exchange HYPERLIQUID --connection-name hype
docker compose exec backend python scripts/backfill_accounting_history.py \
  --exchange HYPERLIQUID --connection-name hype --apply
```

页面同时按账户展示八类数据覆盖情况。每一类会区分 `COMPLETE`、`PARTIAL` 和
`UNSUPPORTED`，展示最后同步时间、实际记录数、最新业务记录时间及原因说明。
“0 条但最近拉取成功”表示统计期内没有发生该类事件，不等同于接口漏数。

Polymarket 当前持仓显示官方 `cashPnl`，因此添加账户之前已经产生的完整浮盈亏也会
保留；“统计期变化”仍只计算添加账户后的变化。已平仓接口不提供可靠的原始开仓时间，
因此这类记录使用统计起点并标记为 `PARTIAL`。若统计期发生外部充值或提现，在资金
流水无法从公开接口完整确认时，收益完整性同样保持为 `PARTIAL`，不会把入金猜成盈利。

Polymarket 已平仓接口的 `timestamp` 可能在后续查询中变化，因此不能作为幂等 ID。
平台使用稳定的 outcome token `asset` 作为已平仓记录来源 ID，同步时也会自动合并
旧格式的同一 outcome 重复记录。手工清理命令默认只预览：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  run --rm backend python scripts/cleanup_polymarket_duplicates.py
```

确认预览数量并完成数据库备份后，添加 `--apply` 执行清理。清理会保留最新记录、
规范化来源 ID、重新计算受影响日期的已实现收益，并写入安全审计日志。

## 收益对账与风险

“风险对账”页面同时展示两套收益口径：

```text
权益口径收益 = 当前权益 - 初始权益 - 净资金流
组成口径收益 = 已实现收益 + 资金费 - 手续费
               +（当前账户未实现收益 - 接入时账户未实现收益）
待解释差额 = 权益口径收益 - 组成口径收益
```

差额超过 `1 USD` 或当前权益的 `0.1%` 时标记为“需复核”。差额并不自动代表计算
错误，也可能来自交易所历史接口覆盖不足；页面会同时保留数据完整性标记。

风险指标包括每日权益最大回撤、单一交易所集中度、单仓权益敞口、保证金使用率和
最近强平距离。风险等级是看板提示，不构成交易或投资建议。
保证金使用率使用各交易所账户级保证金汇总计算，兼容无法把保证金准确分摊到单仓的
全仓模式。

## 页面刷新与数据时效

资产总览（含五档净值曲线）、当前仓位、收益分析、历史仓位、账务流水和交易所账户
页面会每 60 秒重新请求当前筛选条件下的数据，并显示下一次刷新倒计时。总览、持仓和
账户页面优先使用服务端同步时间判断数据新鲜度；其余页面使用最近一次成功请求时间。超过
120 秒没有新数据时，页面显示“数据已过期”并继续自动重试。切回长时间处于后台的
浏览器标签页时，如果已经错过刷新时间，会立即补发一次请求。

## 运行数据保留

backend 每天 `04:20 UTC` 检查一次数据库保留策略。生产环境要求业务数据永久保留，
因此部署时设置：

```dotenv
SYNC_JOB_RETENTION_DAYS=0
BALANCE_SNAPSHOT_RETENTION_DAYS=0
```

`0` 表示禁用该类别的删除，账户余额、逐资产余额、持仓快照、净值时序、审计日志、
交易历史、资金流水、初始快照、统计周期和日汇总均不会被自动清理。开发环境仍可使用
正整数启用安全清理；高频快照只有在对应日汇总存在时才允许删除。每次检查都会写入
`DATA_RETENTION_APPLIED` 安全审计记录。

## PostgreSQL 自动备份

备份脚本默认将文件保存到仓库同级的 `backups` 目录，权限为 `700`；每个备份使用
PostgreSQL custom format，并生成 SHA-256 文件。备份完成后会恢复到随机命名的临时
数据库，按 TimescaleDB 要求执行 `timescaledb_pre_restore()` 和
`timescaledb_post_restore()`，检查表数量与 Alembic 版本，然后自动删除临时库。
恢复验证失败的备份会立即标记为无效并删除，不进入90天保留集合。

```bash
# 立即执行一次完整备份和恢复验证
./scripts/backup-postgres.sh

# 单独验证指定备份
./scripts/verify-postgres-backup.sh /absolute/path/to/atlas-ledger-*.dump

# 以 root 安装每日 03:17 定时任务、90 天备份保留和 7 天日志轮换
sudo ./scripts/install-backup-cron.sh
```

可通过 `.env` 或执行环境设置 `BACKUP_DATABASE_URL`、`BACKUP_DIR`、
`BACKUP_RETENTION_DAYS` 和 `BACKUP_VERIFY_RESTORE`。默认只删除超过 90 天的备份文件；
不会删除正式数据库记录。备份目录必须与仓库和主加密密钥分开保护；恢复验证只操作
`atlas_restore_check_*` 临时数据库，不覆盖正式库。

## 测试与质量

所有后端集成测试使用 `exchange_aggregator_test` PostgreSQL 数据库，不使用
SQLite。

```bash
make lint
make test
make security-check
```

后端覆盖配置加载、凭证加密、篡改检测、脱敏、Symbol 标准化、收益公式、字段校验、
公开只读限制、账务流水归一化与联合查询、八维完整性、Adapter 能力契约、多日收益差分、
Demo 查询、仓位筛选、CSV、Polymarket 幂等清理、安全数据保留、对账与风险公式。
前端覆盖总览、当前仓位、
历史仓位、账务流水、收益、风险对账、同步状态、只读账户页、移动导航和主题持久化。

## 安全说明

- 主加密密钥只通过 `.env` 注入 backend，不进入数据库或镜像
- AES-GCM 使用每字段随机 96 位 Nonce 和 128 位认证标签
- 网站不创建登录会话；账户增删、连接测试、手动同步与批量写接口在公开模式下统一拒绝
- Nginx 限制请求体、隐藏版本并添加浏览器安全响应头
- API 错误、同步错误与健康检查不包含凭证或数据库 URL
- 账户配置加载不会删除已有连接、凭证或历史统计数据
- Docker 网络固定为 `172.30.42.0/24`，便于 PostgreSQL 最小授权

更多资料：

- [部署文档](docs/deployment.md)
- [交易所只读 API 依据](docs/exchange-api-reference.md)
