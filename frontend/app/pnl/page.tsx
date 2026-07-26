"use client";

import type { EChartsOption } from "echarts";
import {
  CalendarDays,
  CircleDollarSign,
  Landmark,
  ReceiptText,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { usePrivacy } from "@/components/app-shell";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import { Chart } from "@/components/chart";
import { ProtectedPage } from "@/components/protected-page";
import { Badge, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { compactDate, usd } from "@/lib/format";
import type { PnlPoint } from "@/lib/types";

type PnlSummary = {
  period_initial_equity: number;
  period_investment_return: number;
  period_realized_pnl: number;
  period_unrealized_pnl_change: number;
  period_funding_fee: number;
  period_trading_fee: number;
  best_day: number;
  worst_day: number;
  profitable_days: number;
  losing_days: number;
  notice: string;
};

type ExchangePnl = {
  exchange: string;
  realized_pnl: number;
  funding_fee: number;
  trading_fee: number;
  investment_return: number;
};

export default function PnlPage() {
  return (
    <ProtectedPage>
      <PnlContent />
    </ProtectedPage>
  );
}

function PnlContent() {
  const [summary, setSummary] = useState<PnlSummary | null>(null);
  const [daily, setDaily] = useState<PnlPoint[]>([]);
  const [weekly, setWeekly] = useState<PnlPoint[]>([]);
  const [monthly, setMonthly] = useState<PnlPoint[]>([]);
  const [byExchange, setByExchange] = useState<ExchangePnl[]>([]);
  const [period, setPeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [error, setError] = useState("");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const { hidden } = usePrivacy();

  const load = useCallback(() => {
    setError("");
    return Promise.all([
      apiFetch<PnlSummary>("/api/pnl/summary"),
      apiFetch<PnlPoint[]>("/api/pnl/daily"),
      apiFetch<PnlPoint[]>("/api/pnl/weekly"),
      apiFetch<PnlPoint[]>("/api/pnl/monthly"),
      apiFetch<ExchangePnl[]>("/api/pnl/by-exchange"),
    ])
      .then(([summaryData, dayData, weekData, monthData, exchangeData]) => {
        setSummary(summaryData);
        setDaily(dayData);
        setWeekly(weekData);
        setMonthly(monthData);
        setByExchange(exchangeData);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  const autoRefresh = useAutoRefresh(load);

  const selected = period === "daily" ? daily : period === "weekly" ? weekly : monthly;
  const cumulative = daily.map((_, index) =>
    daily.slice(0, index + 1).reduce((total, point) => total + point.realized_pnl + point.funding_fee - point.trading_fee, 0),
  );
  const curveOption = useMemo<EChartsOption>(
    () => ({
      grid: { left: 10, right: 16, top: 22, bottom: 24, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: daily.map((point) => compactDate(point.period)),
        axisLabel: { color: "#7f968f", interval: 5 },
        axisLine: { lineStyle: { color: "rgba(130,160,152,.18)" } },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "rgba(130,160,152,.09)" } },
        axisLabel: { color: "#7f968f" },
      },
      series: [
        {
          type: "line",
          data: cumulative,
          smooth: 0.35,
          symbol: "none",
          lineStyle: { color: "#33d6ad", width: 2.5 },
          areaStyle: { color: "rgba(51,214,173,.12)" },
        },
      ],
    }),
    [cumulative, daily],
  );

  const barOption = useMemo<EChartsOption>(
    () => ({
      grid: { left: 8, right: 8, top: 18, bottom: 24, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: selected.map((point) => compactDate(point.period)),
        axisLabel: { color: "#7f968f", interval: period === "daily" ? 5 : 0 },
        axisLine: { lineStyle: { color: "rgba(130,160,152,.18)" } },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "rgba(130,160,152,.09)" } },
        axisLabel: { color: "#7f968f" },
      },
      series: [
        {
          type: "bar",
          barMaxWidth: 18,
          data: selected.map((point) => ({
            value: point.realized_pnl,
            itemStyle: {
              color: point.realized_pnl >= 0 ? "#33d6ad" : "#f06f86",
              borderRadius: point.realized_pnl >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4],
            },
          })),
        },
      ],
    }),
    [period, selected],
  );

  if (error) return <ErrorState message={error} retry={load} />;
  if (!summary) return <LoadingState rows={7} />;

  const metrics = [
    { label: "累计收益", value: summary.period_investment_return, icon: CircleDollarSign },
    { label: "已实现收益", value: summary.period_realized_pnl, icon: Landmark },
    { label: "未实现变化", value: summary.period_unrealized_pnl_change, icon: TrendingUp },
    { label: "手续费", value: -summary.period_trading_fee, icon: ReceiptText },
    { label: "资金费", value: summary.period_funding_fee, icon: CalendarDays },
  ];

  return (
    <>
      <PageHeader
        eyebrow="收益节奏"
        title="收益分析"
        description="看清每天的起伏：充值不算收益，提现也不算亏损。"
        action={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Badge tone="mint">当前统计周期</Badge>
            <AutoRefreshStatus state={autoRefresh} lastUpdatedAt={lastLoadedAt} />
          </div>
        }
      />
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {metrics.map((metric) => {
          const Icon = metric.icon;
          return (
            <article key={metric.label} className="panel p-5">
              <div className="flex items-center justify-between">
                <p className="muted text-xs">{metric.label}</p>
                <Icon className="h-4 w-4 text-mint-400" />
              </div>
              <p className={`mono-number mt-3 text-xl font-semibold ${metric.value > 0 ? "text-emerald-500" : metric.value < 0 ? "text-rose-500" : ""}`}>{usd(metric.value, hidden)}</p>
            </article>
          );
        })}
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-2">
        <article className="panel p-5">
          <p className="font-semibold">累计交易净收益</p>
          <p className="muted mt-1 text-xs">已实现收益 + 资金费 − 手续费</p>
          <Chart option={curveOption} height={300} />
        </article>
        <article className="panel p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-semibold">周期收益</p>
              <p className="muted mt-1 text-xs">按日、周或月聚合</p>
            </div>
            <div className="flex rounded-xl bg-black/5 p-1 dark:bg-white/5">
              {(["daily", "weekly", "monthly"] as const).map((value) => (
                <button key={value} type="button" onClick={() => setPeriod(value)} className={`min-h-9 rounded-lg px-3 text-xs font-medium ${period === value ? "bg-mint-400 text-ink-950" : "muted"}`}>
                  {{ daily: "每日", weekly: "每周", monthly: "每月" }[value]}
                </button>
              ))}
            </div>
          </div>
          <Chart option={barOption} height={300} />
        </article>
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_.8fr]">
        <article className="panel overflow-hidden">
          <div className="border-b px-5 py-4" style={{ borderColor: "var(--line)" }}>
            <p className="font-semibold">交易所收益贡献</p>
            <p className="muted mt-1 text-xs">已实现收益、资金费与手续费拆分</p>
          </div>
          <div className="divide-y" style={{ borderColor: "var(--line)" }}>
            {byExchange.map((row) => (
              <div key={row.exchange} className="grid grid-cols-2 gap-4 px-5 py-4 sm:grid-cols-5 sm:items-center">
                <p className="font-mono text-sm font-semibold">{row.exchange}</p>
                <Metric label="投资收益" value={row.investment_return} hidden={hidden} />
                <Metric label="已实现" value={row.realized_pnl} hidden={hidden} />
                <Metric label="资金费" value={row.funding_fee} hidden={hidden} />
                <Metric label="手续费" value={-row.trading_fee} hidden={hidden} />
              </div>
            ))}
          </div>
        </article>
        <article className="panel p-5">
          <p className="font-semibold">周期表现</p>
          <div className="mt-5 grid grid-cols-2 gap-3">
            <Stat icon={TrendingUp} label="最佳单日" value={usd(summary.best_day, hidden)} tone="positive" />
            <Stat icon={TrendingDown} label="最大单日亏损" value={usd(summary.worst_day, hidden)} tone="negative" />
            <Stat icon={CalendarDays} label="盈利天数" value={`${summary.profitable_days} 天`} />
            <Stat icon={CalendarDays} label="亏损天数" value={`${summary.losing_days} 天`} />
          </div>
          <div className="muted mt-5 rounded-xl bg-black/5 p-4 text-xs leading-5 dark:bg-white/5">
            {summary.notice}。若交易所历史接口覆盖不足，页面会标记数据不完整，不会猜测填补。
          </div>
        </article>
      </section>
    </>
  );
}

function Metric({ label, value, hidden }: { label: string; value: number; hidden: boolean }) {
  return (
    <div>
      <p className="muted text-[10px] uppercase">{label}</p>
      <p className={`mono-number mt-1 text-sm ${value >= 0 ? "text-emerald-500" : "text-rose-500"}`}>{usd(value, hidden)}</p>
    </div>
  );
}

function Stat({ icon: Icon, label, value, tone }: { icon: typeof TrendingUp; label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className="rounded-xl border p-3" style={{ borderColor: "var(--line)" }}>
      <Icon className={`h-4 w-4 ${tone === "positive" ? "text-emerald-500" : tone === "negative" ? "text-rose-500" : "text-mint-400"}`} />
      <p className="muted mt-3 text-[10px] uppercase">{label}</p>
      <p className="mono-number mt-1 text-sm font-semibold">{value}</p>
    </div>
  );
}
