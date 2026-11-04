# 交易所只读 API 依据

适配器仅包含读取与签名，不包含任何交易、资金划转或提币请求。所有历史读取均将
`tracking_started_at` 作为最早时间边界。

## Binance

官方资料：

- <https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints>
- <https://developers.binance.com/docs/wallet/account/api-key-permission>
- <https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api-v3>

使用：

- `GET /api/v3/account`：现货余额
- `GET /sapi/v1/account/apiRestrictions`：API Key 权限
- `GET /fapi/v3/account`：USD-M 账户权益
- `GET /fapi/v3/positionRisk`：当前仓位
- `GET /fapi/v1/userTrades`：统计起点后的成交，用于重建已平仓周期
- `GET /fapi/v1/income`：统计起点后的已实现收益、资金费、手续费和合约账户资金流

签名为查询字符串的 HMAC-SHA256，使用 `X-MBX-APIKEY` 请求头。

`userTrades` 的一张订单可能返回多个成交分片。平台先按合约、持仓方向、买卖方向和
`orderId` 合并分片，成交价按数量加权，已实现收益与手续费求和，再重建仓位周期。
历史仓位来源 ID 使用合并后最后一个成交 ID，因此同步保持幂等。

## OKX

官方资料：

- <https://www.okx.com/docs-v5/en/>

使用：

- `GET /api/v5/account/config`：账户配置与权限
- `GET /api/v5/account/balance`：交易账户权益和余额
- `GET /api/v5/account/positions`：当前仓位
- `GET /api/v5/account/positions-history`：永续和交割合约已平仓仓位
- `GET /api/v5/account/bills-archive`：统计起点后的已实现收益、资金费、交易手续费和
  Funding/Trading 账户划转；接口最多覆盖近 3 个月

签名原文为 `timestamp + method + requestPath + body`，使用 HMAC-SHA256 后
Base64 编码，并发送 OKX 的四个认证请求头。

`positions-history` 在同一仓位分批减仓时会保留相同 `posId` 和 `cTime`，并更新
`uTime`、累计平仓数量、均价和盈亏；仓位归零后再次开仓时，OKX 可能复用 `posId`，
但会产生新的 `cTime`。平台使用 `instType + posId + cTime` 作为稳定周期 ID；
`uTime` 仅作为最终关闭时间，不参与幂等键。这样既不会重复计算同一周期的中间减仓，
也不会让后一次独立开平仓覆盖前一次。

## Bitget

官方资料：

- <https://www.bitget.com/legacy-docs/uta/account/Get-Account>
- <https://www.bitget.com/legacy-docs/uta/account/Get-Account-Info>
- <https://www.bitget.com/legacy-docs/uta/trade/Get-Position>
- <https://www.bitget.com/legacy-docs/uta/trade/Get-Position-History>
- <https://www.bitget.com/legacy-docs/uta/account/Get-Financial-Records>
- <https://www.bitget.com/legacy-docs/uta/account/Get-Funding-Financial-Records>

使用：

- `GET /api/v3/account/info`：通过 `permType=readonly` 核对只读权限
- `GET /api/v3/account/assets`：统一账户总权益、保证金与逐币种余额；不得再加现货或合约权益
- `GET /api/v3/position/current-position`：按合约 category 获取当前仓位
- `GET /api/v3/position/history-position`：按 category 获取历史仓位，使用 `cursor` 分页
- `GET /api/v3/account/financial-records`：交易损益、资金费和手续费账务
- `GET /api/v3/account/funding-financial-records`：资金账户的外部充值提现；UTA 内部划转不计作收益

历史与财务接口单次不超过 30 天，在线接口仅提供近 90 天。历史仓位以
`category + positionId` 为稳定来源 ID，同一 ID 的阶段状态只保留 `updatedTime`
最新值；`cumRealisedPnl` 是毛收益，`netProfit` 是含费用的净收益。v3 历史接口
不保证提供杠杆，缺失时不推算；更新已存在的经典账户历史记录时保留原先确认的杠杆。

签名原文为 `timestamp + method + requestPath + body`，使用 HMAC-SHA256 后
Base64 编码。

统一账户升级后不删除旧事实表数据；上线前需先备份并恢复验证，部署后核对账户权益、
余额、仓位数与同步状态。若同一笔外部充值/提现已被 v2 记为合约划转，v3 首次同步
会在同币种、同方向、同金额、相差不超过五分钟且只有唯一匹配时复用旧记录，避免双计。

## Bybit

官方资料：

- <https://bybit-exchange.github.io/docs/v5/guide>
- <https://bybit-exchange.github.io/docs/v5/user/apikey-info>
- <https://bybit-exchange.github.io/docs/v5/account/wallet-balance>
- <https://bybit-exchange.github.io/docs/v5/position>
- <https://bybit-exchange.github.io/docs/v5/position/close-pnl>
- <https://bybit-exchange.github.io/docs/v5/account/transaction-log>

使用：

- `GET /v5/user/query-api`：验证 API Key 为只读
- `GET /v5/account/wallet-balance`：统一账户权益和逐币种余额
- `GET /v5/account/info` 与 `GET /v5/position/list`：保证金模式及当前仓位
- `GET /v5/position/closed-pnl`：线性与反向合约净平仓收益
- `GET /v5/account/transaction-log`：毛收益、资金费、手续费和统一账户转入转出

签名原文为 `timestamp + apiKey + recvWindow + queryString`，使用 HMAC-SHA256 后发送
Bybit V5 认证请求头。历史接口单次最多查询 7 天，适配器会按时间分段并对每段游标分页。
`closedPnl` 已包含交易费及资金费，作为历史仓位净收益；收益分析的费用拆分以 Transaction
Log 的 `cashFlow`、`funding` 和 `fee` 为权威来源。Bybit 官方限制美国及中国大陆 IP
访问 API，服务器出口必须位于可用地区。

## Hyperliquid

官方资料：

- <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint>
- <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals>
- <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits>

只读 Info API 使用公开钱包地址：

- `clearinghouseState`：永续账户权益和当前仓位
- `spotClearinghouseState`：现货余额
- `userFillsByTime`：统计起点后的成交与已实现收益
- `userFunding`：统计起点后的资金费
- `userFillsByTime.fee`：统计起点后的实际成交手续费
- `userNonFundingLedgerUpdates`：充值、提现及永续/现货/子账户资金划转

平台不会要求或保存 Hyperliquid 钱包私钥、助记词或签名密钥。

## Polymarket

官方资料：

- <https://docs.polymarket.com/api-reference/data-api/overview>
- <https://docs.polymarket.com/migrate/data-api-v1-to-v2>
- <https://docs.polymarket.com/api-reference/profiles/get-public-profile-by-wallet-address>
- <https://docs.polymarket.com/resources/contracts>

Polymarket Data API 使用公开的 User Profile / Proxy Wallet 地址，不需要 API Key。

组合单通过 Data API v2 的 `/v2/positions/combos` 接口同步。开放组合单按各子市场概率计算当前估值；已结算组合单使用官方结算金额、原始成本和买入费用重建已实现收益。组合单与普通仓位一样进入中文翻译缓存，当前仓位转为历史仓位后复用同一译文。
账户连接时先通过 Public Profile API 将登录钱包地址解析为实际 Proxy Wallet：

- `GET /public-profile`：解析并验证 Profile / Proxy Wallet 地址
- `GET /v2/value`：读取普通仓位市值与未结算组合单价值
- `GET /v2/positions?status=OPEN`：读取当前仓位、成本、现价和未实现盈亏
- `GET /v2/positions?status=CLOSED`：读取统计区间内关闭的仓位和已实现盈亏
- Polygon `eth_call`：读取官方 pUSD 合约余额；总权益为持仓价值加可用 pUSD

Data API v2 使用 `{data, pagination}` 响应和不透明游标分页，续页请求保留原筛选窗口。
平台使用官方响应里的 outcome `token_id` 作为稳定幂等键，避免同一 outcome 在后续同步
中被重复写入，并使用 `first_entry_at`、`last_event_at` 记录开仓和最后经济事件时间。
平台不会请求或保存 Polymarket 私钥、助记词、登录密码或交易凭证。公开接口仍不能在
所有账户类型下完整确认外部充值与提现，因此 Polymarket 账户默认显示为统计部分完整。
结算记录可能晚于当前仓位消失才进入官方已平仓接口，因此每轮平仓同步固定回看最近
72 小时，并按 outcome token 幂等写入；迟到记录会同时修正所属北京时间自然日的收益。

市场标题的简体中文显示使用百度“LLM 大模型翻译”服务，不使用通用机器翻译接口。
适配器会保存官方 `title`、`outcome`、`condition_id`、`outcome_index` 和 outcome token；
后端以 outcome token 作为翻译缓存键，将“市场标题 · 结果”译为简体中文。当前与已平仓
记录共用缓存，因此平仓不触发重复翻译。翻译请求只由后端后台任务发出，读 API 不会
实时调用第三方服务；第三方不可用时 API 继续返回英文原文。

## 覆盖限制

不同账户类型、区域和 API Key 权限可能导致某些只读接口不可用。适配器会安全失败
并将账户标记为统计不完整；资产与当前仓位仍继续刷新，不会用猜测值补全。非
USD/USDT/USDC 结算流水在没有可靠历史美元价格时不会冒充美元金额，并会把完整性
降为 `PARTIAL`。首次上线前应分别使用用户的
纯只读凭证或公开地址验证各平台；当前 Demo 验收不代表真实账户权限已验证。
