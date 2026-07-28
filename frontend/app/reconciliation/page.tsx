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
import { usePrivacy } from "@/components/app-shell";
import { ProtectedPage } from "@/components/protected-page";
import { Badge, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, number, usd } from "@/lib/format";
import type { ReconciliationData, RiskData } from "@/lib/types";

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
  const { hidden } = usePrivacy();

  const load = useCallback(() => {
    setError("");
    return Promise.all([
      apiFetch<ReconciliationData>("/api/analytics/reconciliation"),
      apiFetch<RiskData>("/api/analytics/risk"),
    ])
      .then(([nextReconciliation, nextRisk]) => {
        setReconciliation(nextReconciliation);
        setRisk(nextRisk);
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
        description="把权益变化拆成资金流、已实现收益、费用和未实现变化，并集中查看账户敞口。"
        action={<AutoRefreshStatus state={autoRefresh} lastUpdatedAt={lastLoadedAt} />}
      />

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          icon={ArrowRightLeft}
          label="权益口径收益"
          value={usd(totals.equity_return, hidden)}
          detail="当前权益 − 初始权益 − 净资金流"
        />
        <SummaryCard
          icon={Layers3}
          label="组成口径收益"
          value={usd(totals.component_return, hidden)}
          detail="已实现 + 资金费 − 手续费 + 未实现变化"
        />
        <SummaryCard
          icon={totals.status === "MATCHED" ? ShieldCheck : CircleAlert}
          label="待解释差额"
          value={usd(totals.variance, hidden)}
          detail={totals.status === "MATCHED" ? "处于允许误差内" : "建议检查接口覆盖和数据源"}
          tone={totals.status === "MATCHED" ? "positive" : "warning"}
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
            <Breakdown label="充值" value={totals.deposits} hidden={hidden} />
            <Breakdown label="提现" value={-totals.withdrawals} hidden={hidden} />
            <Breakdown label="已实现" value={totals.realized_pnl} hidden={hidden} />
            <Breakdown label="未实现变化" value={totals.unrealized_pnl_change} hidden={hidden} />
            <Breakdown label="资金费" value={totals.funding_fee} hidden={hidden} />
            <Breakdown label="手续费" value={-totals.trading_fee} hidden={hidden} />
            <Breakdown label="初始权益" value={totals.initial_equity} hidden={hidden} />
            <Breakdown label="当前权益" value={totals.current_equity} hidden={hidden} />
          </div>
        </article>

        <article className="panel p-5 md:p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="section-label">风险指标</p>
              <p className="muted mt-1 text-xs">按当前权益与持仓计算</p>
            </div>
            <Badge tone={riskTone}>{risk.summary.risk_level}</Badge>
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
                {["账户", "初始 / 当前权益", "净资金流", "权益收益", "组成收益", "差额", "完整性", "状态"].map((title) => (
                  <th key={title} data-numeric={["初始 / 当前权益", "净资金流", "权益收益", "组成收益", "差额"].includes(title)}>{title}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {reconciliation.accounts.map((item) => (
                <tr key={item.account_id}>
                  <td>
                    <p className="font-semibold">{item.connection_name}</p>
                    <p className="muted mt-1 text-xs">{item.exchange} · {dateTime(item.last_synced_at)}</p>
                  </td>
                  <td className="mono-number" data-numeric="true">
                    <p>{usd(item.initial_equity, hidden)}</p>
                    <p className="muted mt-1 text-xs">{usd(item.current_equity, hidden)}</p>
                  </td>
                  <td className="mono-number" data-numeric="true">{usd(item.net_cash_flow, hidden)}</td>
                  <td className="mono-number" data-numeric="true">{usd(item.equity_return, hidden)}</td>
                  <td className="mono-number" data-numeric="true">{usd(item.component_return, hidden)}</td>
                  <td className={`mono-number ${Math.abs(item.variance) > item.tolerance ? "text-warning" : "text-positive"}`} data-numeric="true">
                    {usd(item.variance, hidden)}
                  </td>
                  <td>
                    <Badge tone={item.data_completeness === "COMPLETE" ? "positive" : "warning"}>
                      {item.data_completeness === "COMPLETE" ? "完整" : "部分"}
                    </Badge>
                  </td>
                  <td>
                    <Badge tone={item.status === "MATCHED" ? "positive" : "warning"}>
                      {item.status === "MATCHED" ? "已对平" : "需复核"}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-2">
        <article className="panel p-5 md:p-6">
          <p className="section-label">交易所集中度</p>
          <div className="mt-5 space-y-4">
            {risk.exchange_concentration.map((item) => (
              <ProgressRow
                key={item.exchange}
                label={item.exchange}
                value={`${usd(item.equity, hidden)} · ${number(item.percent, 1)}%`}
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
                value={`${usd(item.position_value, hidden)} · ${number(item.equity_percent, 1)}%`}
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
}: {
  icon: typeof Scale;
  label: string;
  value: string;
  detail: string;
  tone?: "neutral" | "positive" | "warning" | "negative";
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
    </article>
  );
}

function Breakdown({ label, value, hidden }: { label: string; value: number; hidden: boolean }) {
  return (
    <div className="soft-block p-3">
      <p className="metric-label">{label}</p>
      <p className={`mono-number mt-2 text-sm font-semibold ${value > 0 ? "text-positive" : value < 0 ? "text-negative" : ""}`}>
        {usd(value, hidden)}
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
