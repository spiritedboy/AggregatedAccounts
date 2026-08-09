"use client";

import {
  ArrowRightLeft,
  CircleAlert,
  Gauge,
  Layers3,
  Scale,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import { useCurrency } from "@/components/app-shell";
import { ProtectedPage } from "@/components/protected-page";
import { Badge, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { connectionDisplayName, dateTime, exchangeDisplayName, number, usd } from "@/lib/format";
import type {
  AnalyticsBootstrapData,
  ReconciliationData,
  RiskData,
} from "@/lib/types";

export default function ReconciliationPage() {
  return (
    <ProtectedPage>
      <ReconciliationContent />
    </ProtectedPage>
  );
}

function ReconciliationContent() {
  const [reconciliation, setReconciliation] = useState<ReconciliationData | null>(null);
  const [risk, setRisk] = useState<RiskData | null>(null);
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const [error, setError] = useState("");
  const { formatMoney } = useCurrency();

  const load = useCallback(() => {
    setError("");
    return apiFetch<AnalyticsBootstrapData>("/api/analytics/bootstrap")
      .then((nextData) => {
        setReconciliation(nextData.reconciliation);
        setRisk(nextData.risk);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  const autoRefresh = useAutoRefresh(load);

  if (error) return <ErrorState message={error} retry={load} />;
  if (!reconciliation || !risk) return <LoadingState rows={7} />;

  const totals = reconciliation.totals;
  const riskTone =
    risk.summary.risk_level === "HIGH"
      ? "negative"
      : risk.summary.risk_level === "MEDIUM"
        ? "warning"
        : "positive";

  return (
    <>
      <PageHeader
        eyebrow="资产体检"
        title="风险与收益对账"
        description="按统一收益公式核对权益变化，并集中查看账户敞口。"
        action={<AutoRefreshStatus state={autoRefresh} lastUpdatedAt={lastLoadedAt} />}
      />

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          icon={ArrowRightLeft}
          label="权益口径收益"
          value={formatMoney(totals.equity_return)}
          detail="当前权益 − 初始权益 − 净资金流"
        />
        <SummaryCard
          icon={Layers3}
          label="累计净收益"
          value={formatMoney(totals.net_realized_pnl)}
          detail="已实现毛收益 + 资金费 − 手续费"
        />
        <SummaryCard
          icon={totals.status === "MATCHED" ? ShieldCheck : CircleAlert}
          label="待解释差额"
          value={formatMoney(totals.variance)}
          detail={totals.status === "MATCHED" ? "处于允许误差内" : "建议检查接口覆盖和数据源"}
          tone={totals.status === "MATCHED" ? "positive" : "warning"}
          explanation="权益口径收益与对账组成收益超过容差时会产生待解释差额。常见原因包括接口覆盖不完整、同步时间不一致、接入前仓位或交易所数据延迟；可继续查看下方账户明细定位来源。"
        />
        <SummaryCard
          icon={Gauge}
          label="综合风险"
          value={{ LOW: "低", MEDIUM: "中", HIGH: "高" }[risk.summary.risk_level]}
          detail={`最大回撤 ${number(risk.summary.max_drawdown_percent, 1)}%`}
          tone={riskTone}
        />
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.1fr_.9fr]">
        <article className="panel p-5 md:p-6">
          <p className="section-label">收益组成</p>
          <p className="muted mt-1 text-xs">{reconciliation.notice}</p>
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Breakdown label="充值" value={totals.deposits} formatMoney={formatMoney} />
            <Breakdown label="提现" value={-totals.withdrawals} formatMoney={formatMoney} />
            <Breakdown label="已实现毛收益" value={totals.realized_pnl} formatMoney={formatMoney} />
            <Breakdown label="当前持仓收益" value={totals.current_position_pnl} formatMoney={formatMoney} />
            <Breakdown label="资金费" value={totals.funding_fee} formatMoney={formatMoney} />
            <Breakdown label="手续费" value={-totals.trading_fee} formatMoney={formatMoney} />
            <Breakdown label="接入时持仓收益" value={totals.initial_position_pnl} formatMoney={formatMoney} />
            <Breakdown label="对账组成收益" value={totals.component_return} formatMoney={formatMoney} />
            <Breakdown label="初始权益" value={totals.initial_equity} formatMoney={formatMoney} />
            <Breakdown label="当前权益" value={totals.current_equity} formatMoney={formatMoney} />
          </div>
        </article>

        <article className="panel p-5 md:p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="section-label">风险指标</p>
              <p className="muted mt-1 text-xs">按当前权益与持仓计算</p>
            </div>
            <Badge tone={riskTone}>
              {{ LOW: "低风险", MEDIUM: "中风险", HIGH: "高风险" }[risk.summary.risk_level]}
            </Badge>
          </div>
          <div className="mt-5 grid grid-cols-2 gap-3">
            <RiskMetric label="最大回撤" value={risk.summary.max_drawdown_percent} />
            <RiskMetric
              label="交易所集中度"
              value={risk.summary.largest_exchange_concentration_percent}
            />
            <RiskMetric label="单仓最大敞口" value={risk.summary.largest_position_exposure_percent} />
            <RiskMetric label="保证金使用率" value={risk.summary.margin_utilization_percent} />
            <RiskMetric
              label="最近强平距离"
              value={risk.summary.nearest_liquidation_distance_percent}
              empty="无可用强平价"
            />
          </div>
        </article>
      </section>

      <section className="data-panel mt-4">
        <div className="border-b px-5 py-4" style={{ borderColor: "var(--line)" }}>
          <p className="section-label">账户对账明细</p>
          <p className="muted mt-1 text-xs">差额超过 1 USD 或当前权益的 0.1% 时标记复核。</p>
        </div>
        <div className="overflow-x-auto">
          <table className="data-table min-w-[1040px]">
            <thead>
              <tr>
                {["账户", "初始 / 当前权益", "净资金流", "权益收益", "累计净收益", "当前持仓收益", "对账组成收益", "差额", "完整性", "状态"].map((title) => (
                  <th key={title} data-numeric={["初始 / 当前权益", "净资金流", "权益收益", "累计净收益", "当前持仓收益", "对账组成收益", "差额"].includes(title)}>{title}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {reconciliation.accounts.map((item) => (
                <tr key={item.account_id}>
                  <td>
                    <p className="font-semibold">{connectionDisplayName(item.connection_name, item.exchange)}</p>
                    <p className="muted mt-1 text-xs">{exchangeDisplayName(item.exchange)} · {dateTime(item.last_synced_at)}</p>
                  </td>
                  <td className="mono-number" data-numeric="true">
                    <p>{formatMoney(item.initial_equity)}</p>
                    <p className="muted mt-1 text-xs">{formatMoney(item.current_equity)}</p>
                  </td>
                  <td className="mono-number" data-numeric="true">{formatMoney(item.net_cash_flow)}</td>
                  <td className="mono-number" data-numeric="true">{formatMoney(item.equity_return)}</td>
                  <td className="mono-number" data-numeric="true">{formatMoney(item.net_realized_pnl)}</td>
                  <td className="mono-number" data-numeric="true">{formatMoney(item.current_position_pnl)}</td>
                  <td className="mono-number" data-numeric="true">{formatMoney(item.component_return)}</td>
                  <td className={`mono-number ${Math.abs(item.variance) > item.tolerance ? "text-warning" : "text-positive"}`} data-numeric="true">
                    {formatMoney(item.variance)}
                  </td>
                  <td>
                    <StatusExplanation
                      label={item.data_completeness === "COMPLETE" ? "完整" : "部分"}
                      healthy={item.data_completeness === "COMPLETE"}
                      explanation="部分完整表示至少一类交易所接口覆盖不足。平台仍会展示已取得的数据，但相关收益或费用需要结合缺失项判断。"
                    />
                  </td>
                  <td>
                    <StatusExplanation
                      label={item.status === "MATCHED" ? "已对平" : "需复核"}
                      healthy={item.status === "MATCHED"}
                      explanation="需复核表示差额超过 1 USD 或当前权益的 0.1%。建议对照该账户的净资金流、费用和当前持仓收益。"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="data-panel mt-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4" style={{ borderColor: "var(--line)" }}>
          <div>
            <p className="section-label">数据异常检查</p>
            <p className="muted mt-1 text-xs">每次账户同步后检查本金、杠杆、收益率、仓位消失和平仓重复记录。</p>
          </div>
          <Badge tone={reconciliation.quality.status === "HEALTHY" ? "positive" : "warning"}>
            {reconciliation.quality.status === "HEALTHY"
              ? "未发现异常"
              : `${reconciliation.quality.issue_count} 项待复核`}
          </Badge>
        </div>
        {reconciliation.quality.issues.length === 0 ? (
          <div className="px-5 py-6 text-sm text-positive">最近一次同步检查通过。</div>
        ) : (
          <div className="divide-y" style={{ borderColor: "var(--line)" }}>
            {reconciliation.quality.issues.map((issue, index) => (
              <details key={`${issue.account_id}-${issue.code}-${issue.entity}-${index}`} className="group px-5 py-4">
                <summary className="flex cursor-pointer list-none flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold">{issue.entity}</p>
                    <p className="muted mt-1 text-xs">{exchangeDisplayName(issue.exchange)} · {connectionDisplayName(issue.connection_name, issue.exchange)}</p>
                    <p className="mt-2 text-sm">{issue.message}</p>
                  </div>
                  <Badge tone={issue.severity === "ERROR" ? "negative" : "warning"}>
                    {issue.severity === "ERROR" ? "异常 · 查看建议" : "提示 · 查看建议"}
                  </Badge>
                </summary>
                <div className="soft-block mt-3 p-3 text-xs leading-5">
                  <span className="font-semibold">处理建议：</span>{qualityIssueSuggestion(issue.code)}
                </div>
              </details>
            ))}
          </div>
        )}
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-2">
        <article className="panel p-5 md:p-6">
          <p className="section-label">交易所集中度</p>
          <div className="mt-5 space-y-4">
            {risk.exchange_concentration.map((item) => (
              <ProgressRow
                key={item.exchange}
                label={exchangeDisplayName(item.exchange)}
                value={`${formatMoney(item.equity)} · ${number(item.percent, 1)}%`}
                percent={item.percent}
              />
            ))}
          </div>
        </article>
        <article className="panel p-5 md:p-6">
          <p className="section-label">最大持仓敞口</p>
          <div className="mt-5 space-y-4">
            {risk.top_exposures.slice(0, 6).map((item) => (
              <ProgressRow
                key={item.normalized_symbol}
                label={item.symbol}
                value={`${usd(item.position_value)} · ${number(item.equity_percent, 1)}%`}
                percent={item.equity_percent}
              />
            ))}
          </div>
        </article>
      </section>
    </>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  detail,
  tone = "neutral",
  explanation,
}: {
  icon: typeof Scale;
  label: string;
  value: string;
  detail: string;
  tone?: "neutral" | "positive" | "warning" | "negative";
  explanation?: string;
}) {
  const colors = {
    neutral: "text-[var(--accent)]",
    positive: "text-positive",
    warning: "text-warning",
    negative: "text-negative",
  };
  return (
    <article className="panel p-5">
      <div className="flex items-center justify-between">
        <p className="muted text-xs">{label}</p>
        <Icon className={`h-4 w-4 ${colors[tone]}`} />
      </div>
      <p className={`mono-number mt-3 text-xl font-semibold ${colors[tone]}`}>{value}</p>
      <p className="muted mt-2 text-xs">{detail}</p>
      {explanation && (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer font-semibold text-[var(--accent)]">为什么会出现？</summary>
          <p className="soft-block mt-2 p-3 leading-5">{explanation}</p>
        </details>
      )}
    </article>
  );
}

function StatusExplanation({
  label,
  healthy,
  explanation,
}: {
  label: string;
  healthy: boolean;
  explanation: string;
}) {
  if (healthy) return <Badge tone="positive">{label}</Badge>;
  return (
    <details className="group relative">
      <summary className="cursor-pointer list-none">
        <Badge tone="warning">{label} · 说明</Badge>
      </summary>
      <p className="mt-2 min-w-52 whitespace-normal text-xs leading-5 text-[var(--text)]">{explanation}</p>
    </details>
  );
}

function qualityIssueSuggestion(code: string) {
  const normalized = code.toUpperCase();
  if (normalized.includes("DUPLICATE")) return "核对交易所成交记录，确认同一次平仓是否被不同接口重复返回；系统下一次同步会继续执行去重检查。";
  if (normalized.includes("MISSING") || normalized.includes("INCOMPLETE") || normalized.includes("COVERAGE")) return "检查只读 API 权限和对应数据接口的时间覆盖范围，并等待下一轮同步后再次确认。";
  if (normalized.includes("LEVERAGE") || normalized.includes("MARGIN")) return "对照交易所仓位详情中的杠杆与保证金；部分历史接口不返回完整杠杆信息。";
  if (normalized.includes("POSITION") || normalized.includes("CLOSED")) return "先确认仓位是否刚刚关闭或接口暂时延迟，再在下一轮同步后对照当前仓位与历史仓位。";
  return "等待下一轮同步后再次确认；若仍存在，请对照交易所原始记录检查金额、时间与数据来源。";
}

function Breakdown({ label, value, formatMoney }: { label: string; value: number; formatMoney: (value: number) => string }) {
  return (
    <div className="soft-block p-3">
      <p className="metric-label">{label}</p>
      <p className={`mono-number mt-2 text-sm font-semibold ${value > 0 ? "text-positive" : value < 0 ? "text-negative" : ""}`}>
        {formatMoney(value)}
      </p>
    </div>
  );
}

function RiskMetric({
  label,
  value,
  empty,
}: {
  label: string;
  value: number | null;
  empty?: string;
}) {
  return (
    <div className="soft-block p-3">
      <p className="metric-label">{label}</p>
      <p className="mono-number mt-2 text-sm font-semibold">
        {value === null ? empty : `${number(value, 1)}%`}
      </p>
    </div>
  );
}

function ProgressRow({
  label,
  value,
  percent,
}: {
  label: string;
  value: string;
  percent: number;
}) {
  return (
    <div>
      <div className="flex items-center justify-between gap-4 text-xs">
        <p className="truncate font-medium">{label}</p>
        <p className="mono-number shrink-0">{value}</p>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-[var(--surface-soft)]">
        <div
          className="h-full rounded-full bg-[var(--accent)]"
          style={{ width: `${Math.min(Math.max(percent, 0), 100)}%` }}
        />
      </div>
    </div>
  );
}
