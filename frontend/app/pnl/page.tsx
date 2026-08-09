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

import { useCurrency } from "@/components/app-shell";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import { Chart } from "@/components/chart";
import { ProtectedPage } from "@/components/protected-page";
import { Badge, ErrorState, LoadingState, MetricCard, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { compactDate, exchangeDisplayName } from "@/lib/format";
import type { PnlPoint } from "@/lib/types";

type PnlSummary = {
  period_initial_equity: number;
  period_investment_return: number;
  period_realized_pnl: number;
  period_net_realized_pnl: number;
  current_position_pnl: number;
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

type PnlBootstrapData = {
  summary: PnlSummary;
  daily: PnlPoint[];
  weekly: PnlPoint[];
  monthly: PnlPoint[];
  by_exchange: ExchangePnl[];
  by_side: SidePnl;
  trade_quality: TradeQuality;
};

type SideMetrics = {
  count: number;
  net_pnl: number;
  average_net_pnl: number;
  win_rate: number;
  average_win: number;
  average_loss: number;
};
type SidePnl = {
  long: SideMetrics;
  short: SideMetrics;
  count_ratio: number | null;
};
type ExtremeTrade = { exchange: string; symbol: string; side: "LONG" | "SHORT"; net_pnl: number; close_time: string };
type TradeQuality = SideMetrics & {
  payoff_ratio: number | null;
  profit_factor: number | null;
  best_trade: ExtremeTrade | null;
  worst_trade: ExtremeTrade | null;
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
  const [bySide, setBySide] = useState<SidePnl | null>(null);
  const [tradeQuality, setTradeQuality] = useState<TradeQuality | null>(null);
  const [period, setPeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [error, setError] = useState("");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const { currency, formatMoney, usdCnyRate } = useCurrency();
  const displayValue = useCallback(
    (value: number) => (currency === "CNY" ? value * usdCnyRate : value),
    [currency, usdCnyRate],
  );

  const load = useCallback(() => {
    setError("");
    return apiFetch<PnlBootstrapData>("/api/pnl/bootstrap")
      .then((nextData) => {
        setSummary(nextData.summary);
        setDaily(nextData.daily);
        setWeekly(nextData.weekly);
        setMonthly(nextData.monthly);
        setByExchange(nextData.by_exchange);
        setBySide(nextData.by_side);
        setTradeQuality(nextData.trade_quality);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  const autoRefresh = useAutoRefresh(load);

  const selected = period === "daily" ? daily : period === "weekly" ? weekly : monthly;
  const curveOption = useMemo<EChartsOption>(
    () => ({
      grid: { left: 10, right: 16, top: 22, bottom: 24, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: daily.map((point) => compactDate(point.period)),
        axisLabel: { color: "#687086", interval: 5 },
        axisLine: { lineStyle: { color: "#cdd3e1" } },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "rgba(104,112,134,.12)" } },
        axisLabel: {
          color: "#687086",
          formatter: (value: number) => `${currency === "CNY" ? "¥" : "$"}${value}`,
        },
      },
      series: [
        {
          type: "line",
          data: daily.map((point) => displayValue(point.cumulative_return)),
          smooth: 0.35,
          symbol: "none",
          lineStyle: { color: "#7c5cfc", width: 2.5 },
          areaStyle: { color: "rgba(124,92,252,.14)" },
        },
      ],
    }),
    [currency, daily, displayValue],
  );

  const barOption = useMemo<EChartsOption>(
    () => ({
      grid: { left: 8, right: 8, top: 18, bottom: 24, containLabel: true },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: selected.map((point) => compactDate(point.period)),
        axisLabel: { color: "#687086", interval: period === "daily" ? 5 : 0 },
        axisLine: { lineStyle: { color: "#cdd3e1" } },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "rgba(104,112,134,.12)" } },
        axisLabel: {
          color: "#687086",
          formatter: (value: number) => `${currency === "CNY" ? "¥" : "$"}${value}`,
        },
      },
      series: [
        {
          type: "bar",
          barMaxWidth: 18,
          data: selected.map((point) => ({
            value: displayValue(point.investment_return),
            itemStyle: {
              color: point.investment_return >= 0 ? "#08966d" : "#df5268",
              borderRadius: point.investment_return >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4],
            },
          })),
        },
      ],
    }),
    [currency, displayValue, period, selected],
  );

  if (error) return <ErrorState message={error} retry={load} />;
  if (!summary) return <LoadingState rows={7} />;

  const metrics = [
    {
      label: "已实现毛收益",
      value: summary.period_realized_pnl,
      detail: "历史仓位“已实现收益”求和（不含费用）",
      icon: Landmark,
    },
    {
      label: "资金费",
      value: summary.period_funding_fee,
      detail: "资金费流水求和（正数收入，负数支出）",
      icon: CalendarDays,
    },
    {
      label: "手续费",
      value: -summary.period_trading_fee,
      detail: "手续费流水求和，在公式中作为扣减项",
      icon: ReceiptText,
    },
    {
      label: "当前持仓收益",
      value: summary.current_position_pnl,
      detail: "当前仓位“当前未实现盈亏”求和",
      icon: TrendingUp,
    },
  ];
  const maxContribution = Math.max(...byExchange.map((item) => Math.abs(item.investment_return)), 1);
  const activeDays = summary.profitable_days + summary.losing_days;
  const profitableDayRate = activeDays ? (summary.profitable_days / activeDays) * 100 : 0;
  const dayRatio = summary.losing_days ? `${(summary.profitable_days / summary.losing_days).toFixed(1)} : 1` : "--";

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
      <section className="grid gap-3 xl:grid-cols-[1.1fr_.9fr]">
        <MetricCard
          label="累计净收益"
          value={formatMoney(summary.period_net_realized_pnl)}
          detail="已实现毛收益 + 资金费 - 手续费"
          icon={CircleDollarSign}
          tone={summary.period_net_realized_pnl >= 0 ? "positive" : "negative"}
          featured
        />
        <div className="grid grid-cols-2 gap-3">
          {metrics.map((metric) => (
            <MetricCard
              key={metric.label}
              label={metric.label}
              value={formatMoney(metric.value)}
              detail={metric.detail}
              icon={metric.icon}
              tone={metric.value > 0 ? "positive" : metric.value < 0 ? "negative" : "neutral"}
            />
          ))}
        </div>
      </section>

      <section className="mt-4 grid gap-4">
        <article className="panel p-5 md:p-6">
          <p className="section-label">累计权益收益曲线</p>
          <p className="muted mt-1 text-xs">当前权益 - 统计期初权益 - 净充值提现</p>
          <Chart option={curveOption} height={330} />
        </article>
        <article className="panel p-5 md:p-6">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
            <p className="section-label">周期表现</p>
            <p className="muted mt-1 text-xs">统计期内的高低点与胜负天数</p>
            </div>
            <p className="muted text-[11px]">{summary.notice}</p>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <Stat icon={TrendingUp} label="最佳单日" value={formatMoney(summary.best_day)} tone="positive" />
            <Stat icon={TrendingDown} label="最大单日亏损" value={formatMoney(summary.worst_day)} tone="negative" />
            <Stat icon={CalendarDays} label="盈利天数" value={`${summary.profitable_days} 天`} />
            <Stat icon={CalendarDays} label="亏损天数" value={`${summary.losing_days} 天`} />
            <div className="soft-block flex min-h-24 flex-col justify-center p-4">
              <p className="metric-label">盈利日占比</p>
              <p className="mono-number mt-4 text-2xl font-bold text-positive">{profitableDayRate.toFixed(1)}%</p>
            </div>
            <div className="soft-block flex min-h-24 flex-col justify-center p-4">
              <p className="metric-label">盈亏日比</p>
              <p className="mono-number mt-4 text-2xl font-bold">{dayRatio}</p>
            </div>
          </div>
        </article>
      </section>

      {tradeQuality ? <TradeQualityPanel data={tradeQuality} formatMoney={formatMoney} /> : null}
      {bySide ? <SidePerformance data={bySide} quality={tradeQuality} formatMoney={formatMoney} /> : null}

      <section className="panel mt-4 p-5 md:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="section-label">周期收益</p>
            <p className="muted mt-1 text-xs">在日、周和月三个时间尺度之间切换</p>
          </div>
          <div className="flex rounded-[10px] border bg-[var(--surface-soft)] p-1" style={{ borderColor: "var(--line)" }}>
            {(["daily", "weekly", "monthly"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setPeriod(value)}
                className={`min-h-8 rounded-lg px-3 text-xs font-medium transition ${period === value ? "bg-[var(--surface)] text-[var(--accent-strong)] shadow-sm" : "muted"}`}
              >
                {{ daily: "每日", weekly: "每周", monthly: "每月" }[value]}
              </button>
            ))}
          </div>
        </div>
        <Chart option={barOption} height={300} />
      </section>

      <section className="mt-4">
        <article className="panel overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="border-b px-5 py-4" style={{ borderColor: "var(--line)" }}>
              <p className="section-label">交易所收益贡献</p>
              <p className="muted mt-1 text-xs">条形长度代表各平台对统计期收益的相对贡献</p>
            </div>
          </div>
          <div className="divide-y" style={{ borderColor: "var(--line)" }}>
            {byExchange.map((row) => (
              <div key={row.exchange} className="grid gap-4 px-5 py-4 lg:grid-cols-[140px_1fr_100px_100px_100px] lg:items-center">
                <p className="text-sm font-semibold">{exchangeDisplayName(row.exchange)}</p>
                <div>
                  <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                    <span className="muted">投资收益</span>
                    <span className={`mono-number font-semibold ${row.investment_return >= 0 ? "text-positive" : "text-negative"}`}>
                      {formatMoney(row.investment_return)}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-[var(--surface-soft)]">
                    <div
                      className={`h-full rounded-full ${row.investment_return >= 0 ? "bg-[var(--positive)]" : "bg-[var(--negative)]"}`}
                      style={{ width: `${Math.max(5, (Math.abs(row.investment_return) / maxContribution) * 100)}%` }}
                    />
                  </div>
                </div>
                <Metric label="已实现毛收益" value={row.realized_pnl} formatMoney={formatMoney} />
                <Metric label="资金费" value={row.funding_fee} formatMoney={formatMoney} />
                <Metric label="手续费" value={-row.trading_fee} formatMoney={formatMoney} />
              </div>
            ))}
          </div>
        </article>
      </section>
    </>
  );
}

function TradeQualityPanel({ data, formatMoney }: { data: TradeQuality; formatMoney: (value: number) => string }) {
  const ratio = (value: number | null) => (value === null ? "--" : value.toFixed(2));
  const metrics = [
    ["交易胜率", `${data.win_rate.toFixed(1)}%`],
    ["平均盈利", formatMoney(data.average_win)],
    ["平均亏损", formatMoney(data.average_loss)],
    ["盈亏比", ratio(data.payoff_ratio)],
    ["盈利因子", ratio(data.profit_factor)],
  ];

  return (
    <section className="panel mt-4 overflow-hidden">
      <div className="border-b px-5 py-4 md:px-6" style={{ borderColor: "var(--line)" }}>
        <p className="section-label">交易质量</p>
        <p className="muted mt-1 text-xs">按历史仓位净收益衡量胜率、平均盈亏与收益质量</p>
      </div>
      <div className="grid xl:grid-cols-[1.2fr_.8fr]">
        <div className="grid gap-3 border-b p-5 sm:grid-cols-2 lg:grid-cols-5 xl:border-b-0 xl:border-r md:p-6" style={{ borderColor: "var(--line)" }}>
          {metrics.map(([label, value]) => (
            <div key={label} className="soft-block p-4">
              <p className="metric-label">{label}</p>
              <p className="mono-number mt-3 text-lg font-bold">{value}</p>
            </div>
          ))}
        </div>
        <div className="grid gap-3 p-5 sm:grid-cols-2 md:p-6">
          <ExtremeTradeCard label="最大单笔盈利" trade={data.best_trade} formatMoney={formatMoney} tone="positive" />
          <ExtremeTradeCard label="最大单笔亏损" trade={data.worst_trade} formatMoney={formatMoney} tone="negative" />
        </div>
      </div>
    </section>
  );
}

function ExtremeTradeCard({ label, trade, formatMoney, tone }: { label: string; trade: ExtremeTrade | null; formatMoney: (value: number) => string; tone: "positive" | "negative" }) {
  return (
    <div className="soft-block p-4">
      <p className="metric-label">{label}</p>
      {trade ? (
        <>
          <p className={`mono-number mt-2 text-lg font-bold ${tone === "positive" ? "text-positive" : "text-negative"}`}>{formatMoney(trade.net_pnl)}</p>
          <p className="mt-2 truncate text-xs font-semibold">{trade.symbol}</p>
          <p className="muted mt-1 text-[11px]">{exchangeDisplayName(trade.exchange)} · {trade.side === "LONG" ? "做多" : "做空"}</p>
        </>
      ) : <p className="muted mt-3 text-sm">暂无数据</p>}
    </div>
  );
}

function SidePerformance({ data, quality, formatMoney }: { data: SidePnl; quality: TradeQuality | null; formatMoney: (value: number) => string }) {
  const sides = [
    { label: "做多", tone: "positive", data: data.long },
    { label: "做空", tone: "negative", data: data.short },
  ] as const;
  const ratio = (value: number | null) => (value === null ? "--" : `${value.toFixed(2)} : 1`);

  return (
    <section className="panel mt-4 overflow-hidden">
      <div className="border-b px-5 py-4 md:px-6" style={{ borderColor: "var(--line)" }}>
        <p className="section-label">多空表现</p>
        <p className="muted mt-1 text-xs">按当前统计周期的历史仓位净收益计算，已计入手续费与资金费</p>
      </div>
      <div className="grid lg:grid-cols-[1fr_1fr_.72fr]">
        {sides.map((side) => (
          <div key={side.label} className="border-b p-5 last:border-b-0 lg:border-b-0 lg:border-r md:p-6" style={{ borderColor: "var(--line)" }}>
            <p className={`text-sm font-bold ${side.tone === "positive" ? "text-positive" : "text-negative"}`}>{side.label}</p>
            <div className="mt-5 grid grid-cols-2 gap-4">
              <div>
                <p className="mono-number text-2xl font-bold">{side.data.count} 笔</p>
                <p className="muted mt-1 text-xs">平仓笔数</p>
              </div>
              <div>
                <p className={`mono-number text-2xl font-bold ${side.data.net_pnl >= 0 ? "text-positive" : "text-negative"}`}>
                  {formatMoney(side.data.net_pnl)}
                </p>
                <p className="muted mt-1 text-xs">总净收益</p>
              </div>
            </div>
            <div className="soft-block mt-4 flex items-center justify-between gap-3 p-3">
              <span className="metric-label">单笔平均</span>
              <span className={`mono-number text-sm font-semibold ${side.data.average_net_pnl >= 0 ? "text-positive" : "text-negative"}`}>
                {formatMoney(side.data.average_net_pnl)}
              </span>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2">
              <SideDetail label="胜率" value={`${side.data.win_rate.toFixed(1)}%`} />
              <SideDetail label="平均盈利" value={formatMoney(side.data.average_win)} tone="positive" />
              <SideDetail label="平均亏损" value={formatMoney(side.data.average_loss)} tone="negative" />
            </div>
          </div>
        ))}
        <div className="grid grid-cols-2 gap-3 p-5 lg:grid-cols-1 md:p-6">
          <div className="soft-block p-4">
            <p className="metric-label">盈利因子</p>
            <p className="mono-number mt-2 text-lg font-bold">{quality?.profit_factor == null ? "--" : quality.profit_factor.toFixed(2)}</p>
            <p className="muted mt-1 text-[11px]">总盈利 ÷ 总亏损绝对值</p>
          </div>
          <div className="soft-block p-4">
            <p className="metric-label">多空次数比</p>
            <p className="mono-number mt-2 text-lg font-bold">{ratio(data.count_ratio)}</p>
            <p className="muted mt-1 text-[11px]">做多笔数 ÷ 做空笔数</p>
          </div>
        </div>
      </div>
    </section>
  );
}

function SideDetail({ label, value, tone }: { label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className="rounded-lg bg-[var(--surface-soft)] p-2.5">
      <p className="muted text-[11px]">{label}</p>
      <p className={`mono-number mt-1 truncate text-xs font-semibold ${tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : ""}`}>{value}</p>
    </div>
  );
}

function Metric({ label, value, formatMoney }: { label: string; value: number; formatMoney: (value: number) => string }) {
  return (
    <div>
      <p className="metric-label">{label}</p>
      <p className={`mono-number mt-1 text-sm ${value >= 0 ? "text-positive" : "text-negative"}`}>{formatMoney(value)}</p>
    </div>
  );
}

function Stat({ icon: Icon, label, value, tone }: { icon: typeof TrendingUp; label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className="soft-block flex min-h-24 flex-col justify-center p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="metric-label">{label}</p>
        <Icon className={`h-4 w-4 ${tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : "text-[var(--aqua)]"}`} />
      </div>
      <p className="mono-number mt-4 text-2xl font-bold">{value}</p>
    </div>
  );
}
