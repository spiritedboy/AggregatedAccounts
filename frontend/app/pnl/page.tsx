"use client";

import type { EChartsOption } from "echarts";
import {
  ArrowDownUp,
  CalendarDays,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Gauge,
  Landmark,
  Layers3,
  ReceiptText,
  TrendingUp,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { useCurrency } from "@/components/app-shell";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import { Chart } from "@/components/chart";
import { ProtectedPage } from "@/components/protected-page";
import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { compactDate, exchangeDisplayName } from "@/lib/format";
import type {
  BehaviorAnalysis,
  BehaviorInsight,
  BehaviorMetricRow,
  BehaviorPeriod,
  PnlPoint,
} from "@/lib/types";

type PnlSummary = {
  period_initial_equity: number;
  period_investment_return: number;
  period_realized_pnl: number;
  period_net_realized_pnl: number;
  current_position_pnl: number;
  period_unrealized_pnl_change: number;
  period_funding_fee: number;
  period_trading_fee: number;
  total_profit: number;
  total_loss: number;
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

type TradeQuality = SideMetrics & {
  payoff_ratio: number | null;
  profit_factor: number | null;
};

type PnlBootstrapData = {
  summary: PnlSummary;
  daily: PnlPoint[];
  weekly: PnlPoint[];
  monthly: PnlPoint[];
  by_exchange: ExchangePnl[];
  by_side: SidePnl;
  trade_quality: TradeQuality;
  behavior: BehaviorAnalysis;
};

type AnalysisTab = "overview" | "time" | "position" | "symbol";
type SymbolSort = "net_pnl" | "trade_count" | "win_rate" | "profit_factor";

const PERIODS: Array<{ key: BehaviorPeriod; label: string }> = [
  { key: "7d", label: "7D" },
  { key: "30d", label: "30D" },
  { key: "90d", label: "90D" },
  { key: "all", label: "全部" },
];

const TABS: Array<{ key: AnalysisTab; label: string; icon: typeof Clock3 }> = [
  { key: "overview", label: "总览", icon: CircleDollarSign },
  { key: "time", label: "时间", icon: Clock3 },
  { key: "position", label: "仓位", icon: Gauge },
  { key: "symbol", label: "标的", icon: Layers3 },
];

export default function PnlPage() {
  return (
    <ProtectedPage>
      <PnlContent />
    </ProtectedPage>
  );
}

function PnlContent() {
  const [data, setData] = useState<PnlBootstrapData | null>(null);
  const [behaviorPeriod, setBehaviorPeriod] = useState<BehaviorPeriod>("30d");
  const [activeTab, setActiveTab] = useState<AnalysisTab>("overview");
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [isDark, setIsDark] = useState(true);
  const [error, setError] = useState("");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const { currency, formatMoney, formatSignedMoney, usdCnyRate } = useCurrency();
  const displayValue = useCallback(
    (value: number) => (currency === "CNY" ? value * usdCnyRate : value),
    [currency, usdCnyRate],
  );

  const load = useCallback(() => {
    setError("");
    return apiFetch<PnlBootstrapData>(`/api/pnl/bootstrap?behavior_period=${behaviorPeriod}`)
      .then((nextData) => {
        setData(nextData);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason: Error) => setError(reason.message));
  }, [behaviorPeriod]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const root = document.documentElement;
    const syncTheme = () => setIsDark(root.classList.contains("dark"));
    const observer = new MutationObserver(syncTheme);
    syncTheme();
    observer.observe(root, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => observer.disconnect();
  }, []);
  const autoRefresh = useAutoRefresh(load);

  useEffect(() => {
    if (!focusKey) return;
    const timer = window.setTimeout(() => {
      document.querySelector(`[data-analysis-key="${focusKey}"]`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [activeTab, focusKey]);

  const openInsight = (insight: BehaviorInsight) => {
    setActiveTab(insight.target_tab);
    setFocusKey(insight.target_key);
  };

  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <LoadingState rows={7} />;

  return (
    <>
      <PageHeader
        eyebrow="交易行为"
        title="收益分析"
        description={`${data.behavior.trade_count} 笔平仓 · 累计净收益 ${formatSignedMoney(data.summary.period_net_realized_pnl)} · 按北京时间统计`}
        action={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="mono-number text-[10px] font-semibold tracking-[0.06em] text-[var(--muted)]">UTC+8 · {data.behavior.trade_count} TRADES</span>
            <AutoRefreshStatus state={autoRefresh} lastUpdatedAt={lastLoadedAt} />
          </div>
        }
      />

      <section className="panel mb-4 flex flex-col gap-4 p-3 md:flex-row md:items-center md:justify-between md:p-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
            <ArrowDownUp className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold">行为分析周期</p>
            <p className="muted mt-0.5 truncate text-xs">按平仓时间筛选 · Asia/Shanghai</p>
          </div>
        </div>
        <div className="grid grid-cols-4 rounded-xl border bg-[var(--surface-soft)] p-1" style={{ borderColor: "var(--line)" }}>
          {PERIODS.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={behaviorPeriod === item.key}
              onClick={() => setBehaviorPeriod(item.key)}
              className={`min-h-10 rounded-lg px-3 text-xs font-bold transition ${behaviorPeriod === item.key ? "bg-[var(--surface)] text-[var(--accent-strong)] shadow-sm" : "muted hover:text-[var(--text)]"}`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>

      <InsightsPanel behavior={data.behavior} formatMoney={formatSignedMoney} onOpen={openInsight} />

      <nav className="panel mt-4 grid grid-cols-4 gap-1 p-1.5" aria-label="收益分析分组">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            aria-pressed={activeTab === key}
            onClick={() => {
              setActiveTab(key);
              setFocusKey(null);
            }}
            className={`flex min-h-11 items-center justify-center gap-2 rounded-xl px-2 text-xs font-bold transition md:text-sm ${activeTab === key ? "bg-[var(--accent-soft)] text-[var(--accent-strong)]" : "muted hover:bg-[var(--surface-soft)] hover:text-[var(--text)]"}`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </nav>

      {activeTab === "overview" ? (
        <OverviewPanel data={data} currency={currency} displayValue={displayValue} formatMoney={formatMoney} formatSignedMoney={formatSignedMoney} isDark={isDark} />
      ) : null}
      {activeTab === "time" ? (
        <TimeAnalysis behavior={data.behavior} focusKey={focusKey} formatMoney={formatSignedMoney} />
      ) : null}
      {activeTab === "position" ? (
        <PositionAnalysis behavior={data.behavior} focusKey={focusKey} formatMoney={formatSignedMoney} />
      ) : null}
      {activeTab === "symbol" ? (
        <SymbolAnalysis behavior={data.behavior} focusKey={focusKey} formatMoney={formatSignedMoney} />
      ) : null}
    </>
  );
}

function InsightsPanel({
  behavior,
  formatMoney,
  onOpen,
}: {
  behavior: BehaviorAnalysis;
  formatMoney: (value: number) => string;
  onOpen: (insight: BehaviorInsight) => void;
}) {
  return (
    <section className="panel overflow-hidden">
      <div className="border-b px-5 py-4 md:px-6" style={{ borderColor: "var(--line)" }}>
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="section-label">交易洞察</p>
            <p className="muted mt-1 text-xs">只使用样本量不少于 {behavior.minimum_insight_sample_size} 笔的确定性统计</p>
          </div>
          <span className="mono-number text-[10px] text-[var(--muted)]">{periodRange(behavior)}</span>
        </div>
      </div>
      {behavior.insights.length ? (
        <div className="grid gap-px bg-[var(--line)] md:grid-cols-2">
          {behavior.insights.map((insight) => (
            <button
              key={`${insight.code}-${insight.target_key}`}
              type="button"
              onClick={() => onOpen(insight)}
              className="group flex min-h-20 items-center justify-between gap-4 bg-[var(--surface)] px-5 py-4 text-left transition hover:bg-[var(--surface-soft)] md:px-6"
            >
              <span className="flex min-w-0 items-start gap-3">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${insight.tone === "positive" ? "bg-[var(--positive)]" : insight.tone === "negative" ? "bg-[var(--negative)]" : "bg-[var(--warning)]"}`} />
                <span className="text-sm font-medium leading-6">{insightText(insight, formatMoney)}</span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-[var(--muted)] transition group-hover:translate-x-0.5 group-hover:text-[var(--accent)]" />
            </button>
          ))}
        </div>
      ) : (
        <EmptyState
          title={behavior.trade_count ? "暂未形成可靠洞察" : "当前周期暂无平仓交易"}
          description={behavior.trade_count ? `各分组尚未达到至少 ${behavior.minimum_insight_sample_size} 笔的结论门槛，先保留数据、不做武断判断。` : "切换更长周期后，可以查看历史交易行为。"}
        />
      )}
    </section>
  );
}

function OverviewPanel({
  data,
  currency,
  displayValue,
  formatMoney,
  formatSignedMoney,
  isDark,
}: {
  data: PnlBootstrapData;
  currency: "USD" | "CNY";
  displayValue: (value: number) => number;
  formatMoney: (value: number) => string;
  formatSignedMoney: (value: number) => string;
  isDark: boolean;
}) {
  const [curvePeriod, setCurvePeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const { summary, daily, weekly, monthly, by_exchange: byExchange, by_side: bySide, trade_quality: quality } = data;
  const selected = curvePeriod === "daily" ? daily : curvePeriod === "weekly" ? weekly : monthly;
  const curveOption = useMemo<EChartsOption>(
    () => ({
      textStyle: { fontFamily: "IBM Plex Mono, monospace" },
      grid: { left: 10, right: 16, top: 22, bottom: 24, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: isDark ? "#171b24" : "#ffffff",
        borderColor: isDark ? "#343b49" : "#dfe3ea",
        textStyle: { color: isDark ? "#eef1f6" : "#171a23", fontFamily: "IBM Plex Mono, monospace" },
        extraCssText: "box-shadow:0 8px 24px rgba(0,0,0,.16);border-radius:8px;",
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: daily.map((point) => compactDate(point.period)),
        axisLabel: { color: isDark ? "#959dac" : "#697184", interval: 5 },
        axisLine: { lineStyle: { color: isDark ? "#343b49" : "#dfe3ea" } },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: isDark ? "rgba(149,157,172,.12)" : "rgba(105,113,132,.12)" } },
        axisLabel: { color: isDark ? "#959dac" : "#697184", formatter: (value: number) => `${currency === "CNY" ? "¥" : "$"}${value}` },
      },
      series: [{
        type: "line",
        data: daily.map((point) => displayValue(point.cumulative_return)),
        smooth: 0.35,
        symbol: "none",
        lineStyle: { color: isDark ? "#a891ff" : "#7157e8", width: 2.5 },
        areaStyle: { color: isDark ? "rgba(168,145,255,.14)" : "rgba(113,87,232,.12)" },
      }],
    }),
    [currency, daily, displayValue, isDark],
  );
  const barOption = useMemo<EChartsOption>(
    () => ({
      textStyle: { fontFamily: "IBM Plex Mono, monospace" },
      grid: { left: 8, right: 8, top: 18, bottom: 24, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: isDark ? "#171b24" : "#ffffff",
        borderColor: isDark ? "#343b49" : "#dfe3ea",
        textStyle: { color: isDark ? "#eef1f6" : "#171a23", fontFamily: "IBM Plex Mono, monospace" },
      },
      xAxis: {
        type: "category",
        data: selected.map((point) => compactDate(point.period)),
        axisLabel: { color: isDark ? "#959dac" : "#697184", interval: curvePeriod === "daily" ? 5 : 0 },
        axisLine: { lineStyle: { color: isDark ? "#343b49" : "#dfe3ea" } },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: isDark ? "rgba(149,157,172,.12)" : "rgba(105,113,132,.12)" } },
        axisLabel: { color: isDark ? "#959dac" : "#697184", formatter: (value: number) => `${currency === "CNY" ? "¥" : "$"}${value}` },
      },
      series: [{
        type: "bar",
        barMaxWidth: 18,
        data: selected.map((point) => ({
          value: displayValue(point.investment_return),
          itemStyle: {
            color: point.investment_return >= 0 ? "#08966d" : "#df5268",
            borderRadius: point.investment_return >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4],
          },
        })),
      }],
    }),
    [currency, curvePeriod, displayValue, isDark, selected],
  );
  const metrics = [
    ["已实现毛收益", summary.period_realized_pnl, "历史仓位已实现收益，不含费用", Landmark],
    ["资金费", summary.period_funding_fee, "正数收入，负数支出", CalendarDays],
    ["手续费", -summary.period_trading_fee, "在净收益公式中作为扣减项", ReceiptText],
    ["当前持仓收益", summary.current_position_pnl, "当前仓位未实现盈亏求和", TrendingUp],
  ] as const;
  const activeDays = summary.profitable_days + summary.losing_days;
  const maxContribution = Math.max(...byExchange.map((item) => Math.abs(item.investment_return)), 1);

  return (
    <div className="mt-4 space-y-4">
      <section className="grid gap-3 xl:grid-cols-[1.1fr_.9fr]">
        <MetricCard
          label="累计净收益"
          value={formatSignedMoney(summary.period_net_realized_pnl)}
          detail="总盈利 - 总亏损（历史仓位净收益）"
          icon={CircleDollarSign}
          tone={summary.period_net_realized_pnl >= 0 ? "positive" : "negative"}
          featured
        />
        <div className="grid grid-cols-2 gap-3">
          {metrics.map(([label, value, detail, icon]) => (
            <MetricCard key={label} label={label} value={formatSignedMoney(value)} detail={detail} icon={icon} tone={value > 0 ? "positive" : value < 0 ? "negative" : "neutral"} />
          ))}
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.1fr_.9fr]">
        <article className="panel p-5 md:p-6">
          <p className="section-label">累计权益收益曲线</p>
          <p className="muted mt-1 text-xs">当前权益 - 统计期初权益 - 净充值提现</p>
          <Chart option={curveOption} height={310} />
        </article>
        <article className="panel p-5 md:p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="section-label">周期收益曲线</p>
              <p className="muted mt-1 text-xs">切换日、周、月观察收益节奏</p>
            </div>
            <div className="flex rounded-[10px] border bg-[var(--surface-soft)] p-1" style={{ borderColor: "var(--line)" }}>
              {(["daily", "weekly", "monthly"] as const).map((value) => (
                <button key={value} type="button" onClick={() => setCurvePeriod(value)} className={`min-h-10 rounded-lg px-3 text-xs font-medium ${curvePeriod === value ? "bg-[var(--surface)] text-[var(--accent-strong)] shadow-sm" : "muted"}`}>
                  {{ daily: "日", weekly: "周", monthly: "月" }[value]}
                </button>
              ))}
            </div>
          </div>
          <Chart option={barOption} height={310} />
        </article>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <article className="panel p-5 md:p-6">
          <p className="section-label">交易质量</p>
          <p className="muted mt-1 text-xs">按全部历史仓位净收益统计</p>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <CompactMetric label="平仓笔数" value={`${quality.count} 笔`} />
            <CompactMetric label="胜率" value={`${quality.win_rate.toFixed(1)}%`} />
            <CompactMetric label="盈利因子" value={ratioText(quality.profit_factor, false)} />
            <CompactMetric label="平均盈利" value={formatSignedMoney(quality.average_win)} tone="positive" />
            <CompactMetric label="平均亏损" value={formatSignedMoney(quality.average_loss)} tone="negative" />
            <CompactMetric label="盈亏比" value={ratioText(quality.payoff_ratio, false)} />
          </div>
        </article>
        <article className="panel p-5 md:p-6">
          <p className="section-label">周期表现</p>
          <p className="muted mt-1 text-xs">累计净收益 = 总盈利 - 总亏损</p>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <CompactMetric label="总盈利" value={formatSignedMoney(summary.total_profit)} tone="positive" />
            <CompactMetric label="总亏损" value={formatMoney(summary.total_loss)} tone="negative" />
            <CompactMetric label="盈利日占比" value={`${activeDays ? (summary.profitable_days / activeDays * 100).toFixed(1) : "0.0"}%`} />
            <CompactMetric label="最佳单日" value={formatSignedMoney(summary.best_day)} tone="positive" />
            <CompactMetric label="最大单日亏损" value={formatSignedMoney(summary.worst_day)} tone="negative" />
            <CompactMetric label="多空次数比" value={bySide.count_ratio == null ? "—" : `${bySide.count_ratio.toFixed(2)} : 1`} />
          </div>
        </article>
      </section>

      <article className="panel overflow-hidden">
        <div className="border-b px-5 py-4 md:px-6" style={{ borderColor: "var(--line)" }}>
          <p className="section-label">交易所收益贡献</p>
          <p className="muted mt-1 text-xs">全部统计期收益；行为周期明细请切换到“仓位”</p>
        </div>
        <div className="divide-y" style={{ borderColor: "var(--line)" }}>
          {byExchange.map((row) => (
            <div key={row.exchange} className="grid gap-4 px-5 py-4 lg:grid-cols-[140px_1fr_100px_100px_100px] lg:items-center">
              <p className="text-sm font-semibold">{exchangeDisplayName(row.exchange)}</p>
              <div>
                <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                  <span className="muted">投资收益</span>
                  <span className={`mono-number font-semibold ${row.investment_return >= 0 ? "text-positive" : "text-negative"}`}>{formatSignedMoney(row.investment_return)}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-[var(--surface-soft)]">
                  <div className={`h-full rounded-full ${row.investment_return >= 0 ? "bg-[var(--positive)]" : "bg-[var(--negative)]"}`} style={{ width: `${Math.min(100, Math.abs(row.investment_return) / maxContribution * 100)}%` }} />
                </div>
              </div>
              <SmallMoney label="已实现毛收益" value={row.realized_pnl} formatMoney={formatSignedMoney} />
              <SmallMoney label="资金费" value={row.funding_fee} formatMoney={formatSignedMoney} />
              <SmallMoney label="手续费" value={-row.trading_fee} formatMoney={formatSignedMoney} />
            </div>
          ))}
        </div>
      </article>
    </div>
  );
}

function TimeAnalysis({ behavior, focusKey, formatMoney }: AnalysisProps) {
  return (
    <div className="mt-4 space-y-4">
      <AnalysisSection title="持仓时间" description="持仓时长 = 平仓时间 - 开仓时间；异常时间记录不进入本项统计。">
        <MetricGrid rows={behavior.duration} prefix="duration" focusKey={focusKey} formatMoney={formatMoney} detailed />
      </AnalysisSection>
      <AnalysisSection title="开仓时间段" description="固定按北京时间统计，不受浏览器或设备时区影响。">
        <MetricGrid rows={behavior.open_session} prefix="session" focusKey={focusKey} formatMoney={formatMoney} />
      </AnalysisSection>
      <AnalysisSection title="星期表现" description="按开仓日归类，收益仍取每笔平仓记录的净收益。">
        <MetricGrid rows={behavior.weekday} prefix="weekday" focusKey={focusKey} formatMoney={formatMoney} />
      </AnalysisSection>
      {behavior.data_quality.invalid_duration_count ? (
        <DataNote>{behavior.data_quality.invalid_duration_count} 笔记录因开平仓时间缺失或倒置，未纳入持仓时间分析。</DataNote>
      ) : null}
    </div>
  );
}

function PositionAnalysis({ behavior, focusKey, formatMoney }: AnalysisProps) {
  return (
    <div className="mt-4 space-y-4">
      <AnalysisSection title="杠杆表现" description="只使用历史记录中交易所明确返回且大于 0 的杠杆；缺失记录单列，不做推算。">
        <MetricGrid rows={behavior.leverage} prefix="leverage" focusKey={focusKey} formatMoney={formatMoney} />
      </AnalysisSection>
      <AnalysisSection title="仓位大小" description="当前历史数据缺少可靠的开仓时账户权益，因此使用历史仓位保证金（USD）分桶，不将其伪装为权益占比。">
        <MetricGrid rows={behavior.position_size} prefix="margin" focusKey={focusKey} formatMoney={formatMoney} />
      </AnalysisSection>
      <div className="grid gap-4 xl:grid-cols-2">
        <AnalysisSection title="多空行为" description="按做多、做空对比周期内的净收益质量。">
          <MetricGrid rows={behavior.sides} prefix="side" focusKey={focusKey} formatMoney={formatMoney} detailed />
        </AnalysisSection>
        <AnalysisSection title="交易所行为" description="只看当前行为周期内已经平仓的交易。">
          <MetricGrid rows={behavior.exchanges} prefix="exchange" focusKey={focusKey} formatMoney={formatMoney} detailed />
        </AnalysisSection>
      </div>
      {behavior.data_quality.missing_leverage_count || behavior.data_quality.missing_margin_count ? (
        <DataNote>数据不足：杠杆 {behavior.data_quality.missing_leverage_count} 笔，保证金 {behavior.data_quality.missing_margin_count} 笔。它们保留在独立分组中。</DataNote>
      ) : null}
    </div>
  );
}

function SymbolAnalysis({ behavior, focusKey, formatMoney }: AnalysisProps) {
  const [sortBy, setSortBy] = useState<SymbolSort>("net_pnl");
  const [descending, setDescending] = useState(true);
  const rows = useMemo(() => [...behavior.symbols].sort((left, right) => {
    const leftValue = left[sortBy] ?? Number.NEGATIVE_INFINITY;
    const rightValue = right[sortBy] ?? Number.NEGATIVE_INFINITY;
    const order = Number(leftValue) - Number(rightValue);
    return descending ? -order : order;
  }), [behavior.symbols, descending, sortBy]);
  const chooseSort = (next: SymbolSort) => {
    if (next === sortBy) setDescending((value) => !value);
    else {
      setSortBy(next);
      setDescending(true);
    }
  };

  return (
    <section className="panel mt-4 overflow-hidden">
      <div className="border-b px-5 py-4 md:px-6" style={{ borderColor: "var(--line)" }}>
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="section-label">标的表现</p>
            <p className="muted mt-1 text-xs">衍生品按 normalized underlying 聚合；Polymarket 保留预测市场名称。</p>
          </div>
          <div className="flex max-w-full gap-1 overflow-x-auto pb-1">
            {([
              ["net_pnl", "收益"],
              ["trade_count", "笔数"],
              ["win_rate", "胜率"],
              ["profit_factor", "盈利因子"],
            ] as Array<[SymbolSort, string]>).map(([key, label]) => (
              <button key={key} type="button" onClick={() => chooseSort(key)} className={`min-h-10 whitespace-nowrap rounded-lg border border-[var(--line)] bg-[var(--surface-soft)] px-3 text-xs font-semibold transition hover:border-[var(--accent)] ${sortBy === key ? "text-[var(--accent-strong)]" : "muted"}`}>
                {label}{sortBy === key ? (descending ? " ↓" : " ↑") : ""}
              </button>
            ))}
          </div>
        </div>
      </div>
      {rows.length ? (
        <div className="divide-y" style={{ borderColor: "var(--line)" }}>
          {rows.map((row) => (
            <article
              key={row.key}
              data-analysis-key={`symbol-${row.key}`}
              className={`grid gap-4 px-5 py-4 transition md:grid-cols-[minmax(130px,1.4fr)_repeat(6,minmax(80px,1fr))] md:items-center md:px-6 ${focusKey === `symbol-${row.key}` ? "bg-[var(--accent-soft)] ring-1 ring-inset ring-[var(--accent)]" : ""}`}
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-bold" title={row.label}>{row.label}</p>
                <p className="muted mt-1 text-xs">{row.trade_count} 笔</p>
              </div>
              <RowMetric label="净收益" value={formatMoney(row.net_pnl)} tone={row.net_pnl >= 0 ? "positive" : "negative"} />
              <RowMetric label="胜率" value={`${row.win_rate.toFixed(1)}%`} />
              <RowMetric label="盈利因子" value={ratioText(row.profit_factor, row.profit_factor_unbounded)} />
              <RowMetric label="平均收益" value={formatMoney(row.average_pnl)} tone={row.average_pnl >= 0 ? "positive" : "negative"} />
              <RowMetric label="平均盈利" value={formatMoney(row.average_win)} tone="positive" />
              <RowMetric label="平均亏损" value={formatMoney(row.average_loss)} tone="negative" />
            </article>
          ))}
        </div>
      ) : <EmptyState title="当前周期暂无标的数据" description="切换更长周期后再查看。" />}
    </section>
  );
}

type AnalysisProps = {
  behavior: BehaviorAnalysis;
  focusKey: string | null;
  formatMoney: (value: number) => string;
};

function AnalysisSection({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="panel overflow-hidden">
      <div className="border-b px-5 py-4 md:px-6" style={{ borderColor: "var(--line)" }}>
        <p className="section-label">{title}</p>
        <p className="muted mt-1 text-xs leading-5">{description}</p>
      </div>
      {children}
    </section>
  );
}

function MetricGrid({
  rows,
  prefix,
  focusKey,
  formatMoney,
  detailed = false,
}: {
  rows: BehaviorMetricRow[];
  prefix: string;
  focusKey: string | null;
  formatMoney: (value: number) => string;
  detailed?: boolean;
}) {
  return rows.length ? (
    <div className="grid gap-px bg-[var(--line)] sm:grid-cols-2 xl:grid-cols-4">
      {rows.map((row) => {
        const key = `${prefix}-${row.key}`;
        return (
          <article key={row.key} data-analysis-key={key} className={`bg-[var(--surface)] p-4 transition md:p-5 ${focusKey === key ? "relative z-10 bg-[var(--accent-soft)] ring-2 ring-inset ring-[var(--accent)]" : ""}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-bold" title={row.label}>{row.label}</p>
                <p className="muted mt-1 text-xs">{row.trade_count} 笔交易</p>
              </div>
              <span className={`mono-number text-base font-bold ${row.net_pnl >= 0 ? "text-positive" : "text-negative"}`}>{formatMoney(row.net_pnl)}</span>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-x-3 gap-y-3">
              <RowMetric label="胜率" value={`${row.win_rate.toFixed(1)}%`} />
              <RowMetric label="盈利因子" value={ratioText(row.profit_factor, row.profit_factor_unbounded)} />
              <RowMetric label="平均收益" value={formatMoney(row.average_pnl)} tone={row.average_pnl >= 0 ? "positive" : "negative"} />
              <RowMetric label="盈亏比" value={ratioText(row.payoff_ratio, row.payoff_ratio_unbounded)} />
              {detailed ? <RowMetric label="平均盈利" value={formatMoney(row.average_win)} tone="positive" /> : null}
              {detailed ? <RowMetric label="平均亏损" value={formatMoney(row.average_loss)} tone="negative" /> : null}
            </div>
          </article>
        );
      })}
    </div>
  ) : <EmptyState title="暂无可分析记录" description="当前筛选周期没有满足条件的平仓交易。" />;
}

function RowMetric({ label, value, tone }: { label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className="min-w-0">
      <p className="muted text-[10px] uppercase tracking-wide">{label}</p>
      <p className={`mono-number mt-1 truncate text-xs font-semibold ${tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : ""}`} title={value}>{value}</p>
    </div>
  );
}

function CompactMetric({ label, value, tone }: { label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className="soft-block min-h-20 p-3.5">
      <p className="metric-label">{label}</p>
      <p className={`mono-number mt-3 text-lg font-bold ${tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : ""}`}>{value}</p>
    </div>
  );
}

function SmallMoney({ label, value, formatMoney }: { label: string; value: number; formatMoney: (value: number) => string }) {
  return (
    <div>
      <p className="metric-label">{label}</p>
      <p className={`mono-number mt-1 text-sm ${value >= 0 ? "text-positive" : "text-negative"}`}>{formatMoney(value)}</p>
    </div>
  );
}

function DataNote({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] px-4 py-3 text-xs leading-5 text-[var(--muted)]">{children}</p>;
}

function ratioText(value: number | null, unbounded: boolean) {
  if (unbounded) return "∞";
  return value == null ? "—" : value.toFixed(2);
}

function insightText(insight: BehaviorInsight, formatMoney: (value: number) => string) {
  if (insight.code === "DURATION_BEST") return `${insight.label}持仓累计净收益 ${formatMoney(insight.net_pnl)}，是样本充足的持仓时长中表现最好的区间（${insight.trade_count} 笔）。`;
  if (insight.code === "HIGH_LEVERAGE_WEAK") return `10×以上杠杆交易共 ${insight.trade_count} 笔，盈利因子仅 ${insight.profit_factor?.toFixed(2)}，高杠杆交易质量偏弱。`;
  if (insight.code === "SYMBOL_BEST") return `${insight.label} 是盈利最多的标的，累计净收益 ${formatMoney(insight.net_pnl)}（${insight.trade_count} 笔）。`;
  if (insight.code === "OPEN_SESSION_LOW_WIN_RATE") return `北京时间 ${insight.label} 开仓的交易胜率最低，为 ${insight.win_rate?.toFixed(1)}%（${insight.trade_count} 笔）。`;
  return `${exchangeDisplayName(insight.label ?? "")} 累计净亏损 ${formatMoney(insight.net_pnl)}，是当前周期需要关注的平台（${insight.trade_count} 笔）。`;
}

function periodRange(behavior: BehaviorAnalysis) {
  if (!behavior.effective_from) return "暂无数据";
  const format = (value: string) => new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
  }).format(new Date(value));
  return `${format(behavior.effective_from)}－${format(behavior.to)}`;
}
