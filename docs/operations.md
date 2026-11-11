# 日常巡检

项目提供宿主机只读巡检脚本 `scripts/daily-health-check.sh`。它独立于 backend 运行，
即使应用容器故障也能检查并报告问题。

收益分析基础汇总使用 `pnl_analytics_summaries` 与 `pnl_exchange_summaries` 作为可重建
读取层；
资产总览、风险、对账、同步状态、数据完整性及四个周期的交易行为分析保存在
`operational_read_models`，财务总计保存在 `accounting_daily_summaries`。巡检按模型 scope
分别校验 5 个基础模型和 4 个行为分析模型，新增其他模型不会造成数量误报。每轮交易所
同步后只重算本轮变化涉及的“账户 + 北京时间日期”，服务启动时及每天北京时间 00:05
全量校准。历史仓位、财务流水、账户状态和每日收益快照仍是唯一事实来源；读取模型超过
两个健康检查周期未更新时，接口自动回退到事实表实时计算，不能反向修改明细。

财务日汇总采用 Asia/Shanghai 自然日。日期筛选与自然日对齐时直接求和日汇总；精确到
日内时间的筛选、分页明细和导出仍查询原始流水。升级后的首次启动会幂等地把旧版 UTC
日快照转换为北京时间自然日，并在 `app_settings` 记录迁移版本。

同步调度每 15 秒检查一次，但余额、当前仓位、已平仓和账务历史分别依据自己的成功游标
决定是否调用交易所接口。同步任务类型会记录实际执行的数据流；增量历史查询保留 5 分钟
重叠窗口，依靠来源 ID 幂等更新。

## 巡检范围

- backend、frontend、gateway 容器和本机健康接口
- 公网网站可用性、磁盘使用率
- PostgreSQL 可连接性、数据库大小、启用账户与最新状态完整性
- 四类同步游标延迟、24 小时失败任务与按账户/小时去重的同步错误
- Polymarket 翻译积压、当日账户/资产/持仓快照
- 净值曲线采样延迟、同步任务累计行数
- 最新整库备份的时间、大小、SHA-256 和临时库恢复验证标记

无数据流到期的调度心跳不写入 `sync_jobs`；高频的纯当前仓位成功任务每账户每分钟最多
保留一条。同一账户、错误类型和安全消息在一小时内只记录一次，持续故障仍会通过同步游标
延迟升级为巡检异常，不会因降噪被隐藏。

脚本不会删除数据、重启服务或修改配置。退出码为：`0` 正常、`1` 需要关注、`2` 严重异常。

## 配置

真实 Webhook 只能写入不受 Git 管理的生产 `.env`：

```dotenv
FEISHU_HEALTH_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/REPLACE_ME
HEALTH_CHECK_PUBLIC_URL=https://assets.example.com
HEALTH_CHECK_WARNING_DISK_PERCENT=80
HEALTH_CHECK_CRITICAL_DISK_PERCENT=90
```

手动只读检查且不推送：

```bash
sudo ./scripts/daily-health-check.sh --no-send
```

手动检查并推送飞书移动端适配卡片：

```bash
sudo ./scripts/daily-health-check.sh
```

安装每天 03:30 的 cron 和保留 7 天的日志轮转：

```bash
sudo ./scripts/install-health-check-cron.sh
sudo cat /etc/cron.d/aggregated-accounts-health-check
```

巡检安排在 03:17 数据库备份之后，以便同时检查当天备份。飞书发送失败会返回退出码 2，
并写入 `/var/log/aggregated-accounts-health-check.log`。

飞书消息采用单列卡片布局，根据正常、关注、异常显示绿色、橙色或红色标题。异常与告警
优先展示，详细信息按系统、服务、数据库和备份分区，并提供打开资产看板的整行按钮；不使用
手机端容易挤压的多列字段。

## 每日已平仓收益汇总

`scripts/daily-pnl-report.sh` 在北京时间每天 01:00 汇总**前一自然日**已平仓记录。
例如 2026-11-11 01:00 推送 2026-11-10 的数据。与历史仓位页一致，按平仓时间筛选，
每页读取 50 条并继续翻页直到全部获取；不会只统计第一页。消息包含净收益、盈亏笔数、
盈利/亏损合计与交易所分布，点击可打开当天 `/history?start=YYYY-MM-DD&end=YYYY-MM-DD&page_size=50`。
这是历史仓位 `net_pnl` 汇总，不包括未平仓收益或充值提现，也不等于账户当日权益变化。
若数据分页不一致或有缺失金额，脚本失败且不推送不完整的数字。若源数据同步延迟，
次日 01:00 之后才入库的平仓不在已发日报内，可指定日期手动重发。

在生产机不受 Git 管理的 `.env` 中设置**另一个**飞书机器人 Webhook，不得与健康巡检相同：

```dotenv
FEISHU_DAILY_PNL_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/REPLACE_ME
DAILY_PNL_API_BASE_URL=http://127.0.0.1:8000
DAILY_PNL_PUBLIC_URL=https://www.bitboy.cn
```

先只读预览，再安装定时任务：

```bash
./scripts/daily-pnl-report.sh --no-send
./scripts/daily-pnl-report.sh --date 2026-11-10 --no-send
sudo ./scripts/install-daily-pnl-cron.sh
sudo cat /etc/cron.d/aggregated-accounts-daily-pnl
```

cron 每小时整点检查一次北京时间，仅 01:00 执行报告，因此宿主机即便是 UTC 时区也能
准确运行；日志为 `/var/log/aggregated-accounts-daily-pnl.log`，只保留 7 天。手动补发用
`./scripts/daily-pnl-report.sh --date YYYY-MM-DD`，注意会向飞书再次发送消息。
