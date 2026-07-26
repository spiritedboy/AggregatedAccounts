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
- `GET /fapi/v1/income`：统计起点后的收益流水

签名为查询字符串的 HMAC-SHA256，使用 `X-MBX-APIKEY` 请求头。

## OKX

官方资料：

- <https://www.okx.com/docs-v5/en/>

使用：

- `GET /api/v5/account/config`：账户配置与权限
- `GET /api/v5/account/balance`：交易账户权益和余额
- `GET /api/v5/account/positions`：当前仓位
- `GET /api/v5/account/bills-archive`：统计起点后的账户流水

签名原文为 `timestamp + method + requestPath + body`，使用 HMAC-SHA256 后
Base64 编码，并发送 OKX 的四个认证请求头。

## Bitget

官方资料：

- <https://www.bitget.com/api-doc/common/intro>
- <https://www.bitget.com/api-doc/spot/account/Get-Account-Assets>
- <https://www.bitget.com/api-doc/contract/account/Get-Account-List>
- <https://www.bitget.com/api-doc/classic/contract/position/get-all-position>
- <https://www.bitget.com/api-doc/classic/contract/position/Get-History-Position>

使用：

- `GET /api/v2/spot/account/info`：账户权限信息
- `GET /api/v2/spot/account/assets`：现货资产
- `GET /api/v2/mix/account/accounts`：合约账户权益
- `GET /api/v2/mix/position/all-position`：当前合约仓位
- `GET /api/v2/spot/account/bills`：统计起点后的账户流水

签名原文为 `timestamp + method + requestPath + body`，使用 HMAC-SHA256 后
Base64 编码。

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

平台不会要求或保存 Hyperliquid 钱包私钥、助记词或签名密钥。

## Polymarket

官方资料：

- <https://docs.polymarket.com/api-reference/introduction>
- <https://docs.polymarket.com/api-reference/profiles/get-public-profile-by-wallet-address>
- <https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user>
- <https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user>
- <https://docs.polymarket.com/api-reference/misc/download-an-accounting-snapshot-zip-of-csvs>

Polymarket Data API 使用公开的 User Profile / Proxy Wallet 地址，不需要 API Key。
账户连接时先通过 Public Profile API 将登录钱包地址解析为实际 Proxy Wallet：

- `GET /public-profile`：解析并验证 Profile / Proxy Wallet 地址
- `GET /v1/accounting/snapshot`：读取 `cashBalance`、`positionsValue` 和 `equity`
- `GET /positions`：读取当前预测市场持仓、成本、现价和完整 `cashPnl`
- `GET /closed-positions`：读取统计起点后关闭的仓位和已实现盈亏

平台不会请求或保存 Polymarket 私钥、助记词、登录密码或交易凭证。官方已平仓接口
没有可靠的原始开仓时间，相关历史记录会标记为 `PARTIAL`。公开接口也不能在所有账户
类型下完整确认外部充值与提现，因此 Polymarket 账户默认显示为统计部分完整。
已平仓响应中的 `timestamp` 可能变化，平台使用官方响应里的 outcome token `asset`
作为稳定幂等键，避免同一 outcome 在后续同步中被重复写入。

## 覆盖限制

不同账户类型、区域和 API Key 权限可能导致某些只读接口不可用。适配器会安全失败
并将账户标记为异常或统计不完整，不会用猜测值补全。首次上线前应分别使用用户的
纯只读凭证或公开地址验证各平台；当前 Demo 验收不代表真实账户权限已验证。
