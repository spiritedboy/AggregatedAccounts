# 日常巡检

项目提供宿主机只读巡检脚本 `scripts/daily-health-check.sh`。它独立于 backend 运行，
即使应用容器故障也能检查并报告问题。

收益分析使用 `pnl_analytics_summaries` 与 `pnl_exchange_summaries` 作为可重建读取层；
资产总览、风险、对账、同步状态和数据完整性保存在 `operational_read_models`，财务总计
保存在 `accounting_daily_summaries`。每轮交易所同步完成后在同一事务中统一刷新，服务
启动时及每天北京时间 00:05 全量校准。历史仓位、财务流水、账户状态和每日收益快照仍是
唯一事实来源；读取模型异常时应从事实表重建，不能反向修改明细。

财务日汇总采用 Asia/Shanghai 自然日。日期筛选与自然日对齐时直接求和日汇总；精确到
日内时间的筛选、分页明细和导出仍查询原始流水。读取模型缺失时接口自动回退到事实表聚合。

## 巡检范围

- backend、frontend、gateway 容器和本机健康接口
- 公网网站可用性、磁盘使用率
- PostgreSQL 可连接性、数据库大小、启用账户与最新状态完整性
- 超过 5 分钟未更新的账户、24 小时同步失败与同步错误
- Polymarket 翻译积压、当日账户/资产/持仓快照
- 净值曲线采样延迟、同步任务累计行数
- 最新整库备份的时间、大小和 SHA-256 完整性

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
