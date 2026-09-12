"use client";

import type { EChartsOption } from "echarts";
import Link from "next/link";
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, CheckCircle2,
  CircleDollarSign, Clock3, Coins, Gauge, Landmark, Scale, ShieldAlert,
  Target, TrendingDown, TrendingUp, Wallet,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { useCurrency } from "@/components/app-shell";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import { Chart } from "@/components/chart";
import { PositionLabel } from "@/components/position-label";
import { ProtectedPage } from "@/components/protected-page";
import { Badge, EmptyState, ErrorState, ExchangeMark, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { connectionDisplayName, dateTime, exchangeDisplayName, number, positionSideLabel, usd } from "@/lib/format";
import type { DashboardBootstrapData, DashboardData, EquityCurveData, EquityCurveRange, Position, RiskData } from "@/lib/types";

const curveRanges: Array<{ value: EquityCurveRange; label: string }> = [
  { value: "1d", label: "1日" }, { value: "1w", label: "1周" },
  { value: "1m", label: "1月" }, { value: "6m", label: "半年" },
  { value: "1y", label: "1年" },
];
const riskLevelLabel = { LOW: "低风险", MEDIUM: "中风险", HIGH: "高风险" };
type Tone = "positive" | "negative" | "warning" | "neutral";
type BriefItem = { title: string; detail: string; tone: Tone; icon: typeof Activity; href?: string };

function equityAxisLabel(value: number) {
  const magnitude = Math.abs(value);
  if (magnitude >= 1_000_000) return `${number(value / 1_000_000, 2)}m`;
  if (magnitude >= 1_000) return `${number(value / 1_000, 2)}k`;
  return number(value, 2);
}
function signedPercent(value: number | null) {
  return value === null ? "—" : `${value > 0 ? "+" : ""}${number(value, 2)}%`;
}
function pnlTone(value: number): "positive" | "negative" | "neutral" {
  return value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
}
function toneClass(tone: Tone) {
  return tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : tone === "warning" ? "text-warning" : "";
}
function positionName(position: Position) {
  return position.display_symbol || position.normalized_symbol || position.symbol;
}
function portfolioUpdatedAt(data: DashboardData, fallback: string | null) {
  const values = [data.last_updated_at, data.positions_updated_at]
    .filter((value): value is string => Boolean(value));
  if (values.length === 0) return fallback;
  return values.reduce((oldest, value) => new Date(value) < new Date(oldest) ? value : oldest);
}

function liquidationPositionHref(item: RiskData["liquidation_risks"][number]) {
  const params = new URLSearchParams({
    sort: "liquidation-asc",
    focus: item.position_id,
  });
  return `/positions?${params.toString()}`;
}

function buildTodayBrief(data: DashboardData, risk: RiskData, formatMoney: (value: number) => string): BriefItem[] {
  const items: BriefItem[] = [];
  const today = data.today;
  if (today.data_available) {
    items.push({
      title: `今日账户收益 ${today.net_return > 0 ? "+" : ""}${formatMoney(today.net_return)}（${signedPercent(today.return_percent)}）`,
      detail: "已剔除充值与提现，收益率以当日期初权益为分母。",
      tone: pnlTone(today.net_return), icon: today.net_return >= 0 ? ArrowUpRight : ArrowDownRight,
    });
  }
  const nearestLiquidation = risk.liquidation_risks[0];
  const dangerLiquidation = risk.liquidation_risks.find((item) => item.risk_level === "DANGER");
  const watchCount = risk.liquidation_risks.filter((item) => item.risk_level === "WATCH").length;
  if (dangerLiquidation) {
    items.push({
      title: `${dangerLiquidation.normalized_symbol} ${positionSideLabel(dangerLiquidation.side, dangerLiquidation.exchange)}距离强平价仅 ${number(dangerLiquidation.distance_percent, 1)}%，属于高风险仓位。`,
      detail: `${exchangeDisplayName(dangerLiquidation.exchange)} · 点击查看并定位该仓位`,
      tone: "negative", icon: AlertTriangle,
      href: liquidationPositionHref(dangerLiquidation),
    });
  } else if (watchCount > 0) {
    items.push({
      title: `存在 ${watchCount} 个仓位进入强平关注区间。`,
      detail: nearestLiquidation ? `${nearestLiquidation.normalized_symbol} 最近，距离 ${number(nearestLiquidation.distance_percent, 1)}%。` : "请检查对应仓位与保证金。",
      tone: "warning", icon: AlertTriangle,
      href: nearestLiquidation ? liquidationPositionHref(nearestLiquidation) : undefined,
    });
  }
  if (risk.summary.margin_utilization_percent >= 50) {
    items.push({
      title: `保证金使用率 ${number(risk.summary.margin_utilization_percent, 1)}%`,
      detail: risk.summary.margin_utilization_percent >= 80 ? "保证金占用偏高，可用缓冲已明显收窄。" : "保证金使用率高于常规关注线。",
      tone: risk.summary.margin_utilization_percent >= 80 ? "negative" : "warning", icon: Gauge,
    });
  }
  if (risk.summary.largest_exchange_concentration_percent >= 35) {
    const largest = risk.exchange_concentration[0];
    items.push({
      title: `${largest?.exchange ? exchangeDisplayName(largest.exchange) : "单一平台"}占总权益 ${number(risk.summary.largest_exchange_concentration_percent, 1)}%`,
      detail: "平台集中度较高，需留意单一交易所的运行与风控风险。",
      tone: risk.summary.largest_exchange_concentration_percent >= 50 ? "negative" : "warning", icon: Landmark,
    });
  }
  const winner = data.position_highlights.largest_winner;
  const loser = data.position_highlights.largest_loser;
  if (winner && items.length < 5) items.push({
    title: `${positionName(winner)} 是当前最大浮盈仓位`,
    detail: `${exchangeDisplayName(winner.exchange)} · ${formatMoney(winner.unrealized_pnl)}`,
    tone: "positive", icon: TrendingUp,
  });
  if (loser && items.length < 5) items.push({
    title: `${positionName(loser)} 是当前最大浮亏仓位`,
    detail: `${exchangeDisplayName(loser.exchange)} · ${formatMoney(loser.unrealized_pnl)}`,
    tone: "negative", icon: TrendingDown,
  });
  if (today.data_available && today.realized_pnl > 0 && items.length < 5) {
    const feeRatio = (today.trading_fee / today.realized_pnl) * 100;
    if (feeRatio >= 10) items.push({
      title: `手续费占今日已实现收益 ${number(feeRatio, 1)}%`,
      detail: `今日手续费 ${formatMoney(today.trading_fee)}，交易成本值得关注。`,
      tone: "warning", icon: CircleDollarSign,
    });
  }
  if (items.length === 0) items.push({
    title: "今日收益数据尚未形成", detail: "等待本日首个完整账户快照后计算。",
    tone: "neutral", icon: Clock3,
  });
  const hasRisk = items.some((item) => item.tone === "warning" || item.tone === "negative");
  if (today.data_available && !hasRisk && items.length < 5) items.push({
    title: "当前账户运行正常，未发现显著风险项",
    detail: "保证金、平台集中度与强平距离均未触发关注规则。",
    tone: "positive", icon: CheckCircle2,
  });
  return items.slice(0, 5);
}

export default function DashboardPage() {
  return <ProtectedPage><DashboardContent /></ProtectedPage>;
}

function DashboardContent() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [risk, setRisk] = useState<RiskData | null>(null);
  const [curve, setCurve] = useState<EquityCurveData | null>(null);
  const [curveRange, setCurveRange] = useState<EquityCurveRange>("1d");
  const [isDark, setIsDark] = useState(true);
  const [error, setError] = useState("");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const { currency, formatMoney, usdCnyRate } = useCurrency();

  const load = useCallback(() => {
    setError("");
    return apiFetch<DashboardBootstrapData>(`/api/dashboard/bootstrap?range=${curveRange}`)
      .then((next) => {
        setData(next.dashboard); setRisk(next.risk); setCurve(next.equity_curve);
        setLastLoadedAt(new Date().toISOString());
      }).catch((reason) => setError(reason.message));
  }, [curveRange]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const root = document.documentElement;
    const syncTheme = () => setIsDark(root.classList.contains("dark"));
    const observer = new MutationObserver(syncTheme);
    syncTheme();
    observer.observe(root, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => observer.disconnect();
  }, []);
  const autoRefresh = useAutoRefresh(load);

  const equityOption = useMemo<EChartsOption>(() => ({
    animationDuration: 500,
    grid: { left: 8, right: 12, top: 18, bottom: 24, containLabel: true },
    tooltip: {
      trigger: "axis", backgroundColor: "#171b2e", borderColor: "#293047", textStyle: { color: "#f4f6ff" },
      formatter: (params: unknown) => {
        const point = (params as Array<{ axisValue: string; value: number }>)[0];
        const source = currency === "CNY" ? point.value / usdCnyRate : point.value;
        return `${dateTime(point.axisValue)}<br/><b>${formatMoney(source)}</b>`;
      },
    },
    xAxis: {
      type: "category", boundaryGap: false, data: curve?.points.map((point) => point.timestamp) ?? [],
      axisLine: { lineStyle: { color: isDark ? "rgba(205,190,255,.24)" : "#cdd3e1" } },
      axisLabel: {
        color: isDark ? "#c3bad9" : "#687086", hideOverlap: true,
        formatter: (value: string) => {
          const current = new Date(value);
          return new Intl.DateTimeFormat("zh-CN", curveRange === "1d" || curveRange === "1w"
            ? { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }
            : { month: "numeric", day: "numeric" }).format(current);
        },
      },
    },
    yAxis: {
      type: "value", scale: true,
      splitLine: { lineStyle: { color: isDark ? "rgba(205,190,255,.1)" : "rgba(104,112,134,.12)" } },
      axisLabel: { color: isDark ? "#c3bad9" : "#687086", formatter: (value: number) => `${currency === "CNY" ? "¥" : "$"}${equityAxisLabel(value)}` },
    },
    series: [{
      type: "line", smooth: 0.35, symbol: "none",
      data: curve?.points.map((point) => currency === "CNY" ? point.equity * usdCnyRate : point.equity) ?? [],
      lineStyle: { color: isDark ? "#62f1d6" : "#7c5cfc", width: isDark ? 3.5 : 3 },
      areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [
        { offset: 0, color: isDark ? "rgba(98,241,214,.38)" : "rgba(124,92,252,.32)" },
        { offset: 0.55, color: isDark ? "rgba(170,140,255,.13)" : "rgba(32,189,169,.12)" },
        { offset: 1, color: isDark ? "rgba(98,241,214,0)" : "rgba(124,92,252,0)" },
      ] } },
    }],
  }), [currency, curve, curveRange, formatMoney, isDark, usdCnyRate]);

  const allocationOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: "item", formatter: "{b}<br/>{d}%" },
    legend: { bottom: 0, textStyle: { color: isDark ? "#c3bad9" : "#687086" }, icon: "circle" },
    series: [{
      type: "pie", radius: ["54%", "76%"], center: ["50%", "43%"], avoidLabelOverlap: true,
      itemStyle: { borderWidth: 4, borderColor: "transparent" }, label: { show: false },
      data: data?.by_exchange.map((item, index) => ({
        name: exchangeDisplayName(item.exchange), value: item.equity,
        itemStyle: { color: ["#7c5cfc", "#20bda9", "#ee6ca8", "#e6a136", "#4b9ff4", "#8f6fba"][index % 6] },
      })) ?? [],
    }],
  }), [data, isDark]);

  if (error) return <ErrorState message={error} retry={load} />;
  if (!data || !risk || !curve) return <><PageHeader eyebrow="TODAY DESK" title="今日驾驶舱" description="正在整理账户、收益与风险数据…" /><LoadingState rows={6} /></>;

  const briefItems = buildTodayBrief(data, risk, formatMoney);
  const nearestLiquidation = risk.liquidation_risks[0] ?? null;
  const todayTone = pnlTone(data.today.net_return);
  const dataUpdatedAt = portfolioUpdatedAt(data, lastLoadedAt);
  return <>
    {data.demo_mode && <div className="mb-4 flex items-center gap-2 rounded-xl border border-[var(--accent)]/20 bg-[var(--accent-soft)] px-4 py-3 text-sm text-[var(--accent-strong)]"><ShieldAlert className="h-4 w-4" />当前为演示数据，与真实账户数据严格隔离</div>}

    <header className="mb-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
      <div>
        <p className="eyebrow"><span className="h-1.5 w-1.5 rounded-full bg-[var(--aqua)]" />TODAY DESK · {data.today.date}</p>
        <h1 className="mt-2 font-[var(--font-display)] text-[30px] font-extrabold tracking-[-0.045em] md:text-[34px]">今日驾驶舱</h1>
        <p className="muted mt-1 text-sm">先看收益与风险，再决定今天需要关注什么。</p>
      </div>
      <AutoRefreshStatus state={autoRefresh} lastUpdatedAt={dataUpdatedAt} />
    </header>

    <section className="cockpit-overview" aria-label="今日核心指标">
      <div className="grid xl:grid-cols-[1.25fr_.9fr]">
        <article className="cockpit-primary border-b p-5 md:p-7 xl:border-b-0 xl:border-r">
          <div className="flex items-center justify-between gap-3"><p className="metric-label">总权益</p><Wallet className="h-5 w-5 text-[var(--accent)]" /></div>
          <p className="mono-number mt-3 break-all text-[34px] font-bold tracking-[-0.055em] sm:text-[42px] lg:text-[48px]">{formatMoney(data.estimated_total_equity)}</p>
          <div className="mt-6 grid grid-cols-2 gap-4 border-t pt-4" style={{ borderColor: "var(--line)" }}>
            <CoreSubMetric label="可用余额" value={formatMoney(data.available_balance)} />
            <CoreSubMetric label="保证金占用" value={formatMoney(data.margin_used)} />
          </div>
        </article>
        <article className="p-5 md:p-7">
          <div className="flex items-center justify-between gap-3"><p className="metric-label">今日净收益</p>{data.today.net_return >= 0 ? <ArrowUpRight className="h-5 w-5 text-positive" /> : <ArrowDownRight className="h-5 w-5 text-negative" />}</div>
          <p className={`mono-number mt-3 break-all text-[30px] font-bold tracking-[-0.05em] sm:text-[38px] ${toneClass(todayTone)}`}>{data.today.net_return > 0 ? "+" : ""}{formatMoney(data.today.net_return)}</p>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1"><span className={`mono-number text-xl font-bold ${toneClass(todayTone)}`}>{signedPercent(data.today.return_percent)}</span><span className="muted text-xs">今日收益率</span></div>
          <p className="muted mt-5 border-t pt-4 text-xs leading-5" style={{ borderColor: "var(--line)" }}>{data.today.opening_equity === null ? "今日尚无完整日快照，收益率暂不计算。" : `当日期初权益 ${formatMoney(data.today.opening_equity)}，已剔除净资金流。`}</p>
        </article>
      </div>
      <div className="grid border-t sm:grid-cols-2 xl:grid-cols-5" style={{ borderColor: "var(--line)" }}>
        <CoreMetric label="当前未实现盈亏" value={formatMoney(data.current_position_pnl)} tone={pnlTone(data.current_position_pnl)} icon={<Activity className="h-4 w-4" />} />
        <CoreMetric label="保证金使用率" value={`${number(risk.summary.margin_utilization_percent, 1)}%`} tone={risk.summary.margin_utilization_percent >= 80 ? "negative" : risk.summary.margin_utilization_percent >= 50 ? "warning" : "neutral"} icon={<Gauge className="h-4 w-4" />} />
        {nearestLiquidation ? (
          <Link href={liquidationPositionHref(nearestLiquidation)} className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent)]">
            <CoreMetric
              label="最近强平距离"
              value={`${number(nearestLiquidation.distance_percent, 1)}%`}
              detail={`${nearestLiquidation.normalized_symbol} ${positionSideLabel(nearestLiquidation.side, nearestLiquidation.exchange)} · ${exchangeDisplayName(nearestLiquidation.exchange)}`}
              tone={nearestLiquidation.risk_level === "DANGER" ? "negative" : nearestLiquidation.risk_level === "WATCH" ? "warning" : "neutral"}
              icon={<Target className="h-4 w-4" />}
            />
          </Link>
        ) : (
          <CoreMetric label="最近强平距离" value="暂无可用强平价" detail="当前仓位均无可靠交易所强平价" icon={<Target className="h-4 w-4" />} compact />
        )}
        <CoreMetric label="总持仓敞口 / Notional" value={usd(risk.summary.total_position_value)} icon={<Scale className="h-4 w-4" />} />
        <CoreMetric label="最近数据更新时间" value={dateTime(dataUpdatedAt)} icon={<Clock3 className="h-4 w-4" />} compact />
      </div>
    </section>

    <section className="panel mt-4 overflow-hidden" aria-labelledby="today-brief-title">
      <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--line)" }}><div><p id="today-brief-title" className="section-label">今日摘要</p><p className="muted mt-1 text-xs">基于账户收益、当前仓位与风险阈值自动提炼</p></div><Activity className="h-5 w-5 text-[var(--accent)]" /></div>
      <div className="grid lg:grid-cols-2">{briefItems.map((item, index) => { const Icon = item.icon; const content = <><span className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[var(--surface-soft)] ${toneClass(item.tone)}`}><Icon className="h-4 w-4" /></span><div className="min-w-0"><p className={`text-sm font-semibold ${toneClass(item.tone)}`}>{item.title}</p><p className="muted mt-1 text-xs leading-5">{item.detail}</p></div></>; const className = "flex gap-3 border-b px-5 py-4 last:border-b-0 lg:odd:border-r"; return item.href ? <Link key={`${item.title}-${index}`} href={item.href} className={`${className} transition hover:bg-[var(--surface-soft)]`} style={{ borderColor: "var(--line)" }}>{content}</Link> : <article key={`${item.title}-${index}`} className={className} style={{ borderColor: "var(--line)" }}>{content}</article>; })}</div>
    </section>

    <section className="mt-4 grid gap-4 xl:grid-cols-[1.45fr_.72fr]">
      <article className="panel min-w-0 p-5 md:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div><p className="section-label">净值曲线</p><p className="muted mt-1 text-xs">底层每 5 分钟采样 · 当前显示精度 {curve.resolution}</p><p className={`mono-number mt-2 text-sm font-semibold ${curve.change.amount === null ? "muted" : toneClass(pnlTone(curve.change.amount))}`}>净值变化：{curve.change.amount === null ? "—" : `${curve.change.amount > 0 ? "+" : ""}${formatMoney(curve.change.amount)}`} ({signedPercent(curve.change.percent)})</p></div>
          <div className="inline-flex max-w-full self-start overflow-x-auto rounded-xl border p-1" style={{ borderColor: "var(--line)", background: "var(--surface-soft)" }}>{curveRanges.map((item) => <button key={item.value} type="button" aria-pressed={curveRange === item.value} className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${curveRange === item.value ? "bg-[var(--accent)] text-white shadow-sm" : "muted hover:bg-[var(--surface)] hover:text-[var(--text)]"}`} onClick={() => setCurveRange(item.value)}>{item.label}</button>)}</div>
        </div>
        <div className="mt-3"><Chart option={equityOption} height={300} /></div>
      </article>
      <TodayBreakdown data={data} formatMoney={formatMoney} />
    </section>

    <section className="panel mt-4 overflow-hidden">
      <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--line)" }}><div><p className="section-label">风险速览</p><p className="muted mt-1 text-xs">权益回撤、集中度与单仓暴露</p></div><a href="/reconciliation" className="text-xs font-semibold text-[var(--accent)]">查看完整对账 →</a></div>
      <div className="grid sm:grid-cols-2 xl:grid-cols-4">
        <RiskCard label="最大回撤" value={`${number(risk.summary.max_drawdown_percent, 1)}%`} detail="每日权益口径" />
        <RiskCard label="交易所集中度" value={`${number(risk.summary.largest_exchange_concentration_percent, 1)}%`} detail="最大单一平台权益占比" />
        <RiskCard label="最大单仓暴露" value={`${number(risk.summary.largest_position_exposure_percent, 1)}%`} detail="单一标的仓位价值 ÷ 总权益" />
        <RiskCard label="综合风险" value={riskLevelLabel[risk.summary.risk_level]} detail="按回撤、集中度、保证金与强平距离判定" tone={risk.summary.risk_level === "HIGH" ? "negative" : risk.summary.risk_level === "MEDIUM" ? "warning" : "positive"} />
      </div>
    </section>

    <section className="data-panel mt-4">
      <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--line)" }}><div><p className="section-label">当前主要仓位</p><p className="muted mt-1 text-xs">按绝对仓位价值排序，首页展示前 6 项</p></div><a href="/positions" className="text-xs font-semibold text-[var(--accent)]">查看全部</a></div>
      {data.positions.length === 0 ? <EmptyState title="当前没有持仓" description="账户同步正常，但目前没有可展示的衍生品或预测市场仓位。" /> : <div className="divide-y" style={{ borderColor: "var(--line)" }}>{data.positions.map((position) => <div key={position.id} className="grid grid-cols-[1fr_auto] gap-4 px-5 py-4 sm:grid-cols-[1.2fr_.72fr_.72fr] sm:items-center"><div className="min-w-0"><div className="flex min-w-0 items-center gap-2"><PositionLabel position={position} compact /><Badge tone={position.side === "LONG" ? "positive" : "negative"}>{positionSideLabel(position.side, position.exchange)}</Badge></div><p className="muted mt-1 text-xs">{exchangeDisplayName(position.exchange)} · {number(position.leverage, 0)}×</p></div><div className="hidden sm:block"><p className="metric-label">仓位价值</p><p className="mono-number mt-1 text-sm">{usd(position.position_value_usd)}</p></div><div className="text-right"><p className="metric-label">当前未实现盈亏</p><p className={`mono-number mt-1 text-sm ${toneClass(pnlTone(position.unrealized_pnl))}`}>{formatMoney(position.unrealized_pnl)}</p></div></div>)}</div>}
    </section>

    <section className="mt-4 grid gap-4 xl:grid-cols-[.8fr_1.2fr]">
      <article className="panel min-w-0 p-5 md:p-6"><p className="section-label">资产 / 交易所分布</p><p className="muted mt-1 text-xs">按账户权益占比，不作为收益判断</p><Chart option={allocationOption} height={230} /><div className="mt-3 grid gap-2 border-t pt-4" style={{ borderColor: "var(--line)" }}>{data.by_exchange.map((item) => { const percent = data.estimated_total_equity > 0 ? item.equity / data.estimated_total_equity * 100 : 0; return <div key={`${item.exchange}-${item.connection_name}`} className="flex items-center justify-between gap-3 text-xs"><span className="min-w-0 truncate font-medium">{exchangeDisplayName(item.exchange)}</span><span className="mono-number whitespace-nowrap text-[var(--muted)]">{formatMoney(item.equity)} · {number(percent, 1)}%</span></div>; })}</div></article>
      <article className="panel p-5 md:p-6">
        <div className="flex items-center justify-between"><div><p className="section-label">账户数据健康</p><p className="muted mt-1 text-xs">连接状态、数据完整性与未估值资产</p></div><Gauge className="h-5 w-5 text-[var(--aqua)]" /></div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">{data.by_exchange.map((item) => <div key={`${item.exchange}-${item.connection_name}`} className="flex items-center justify-between gap-4 rounded-xl border p-3" style={{ borderColor: "var(--line)", background: "var(--surface-soft)" }}><div className="flex min-w-0 items-center gap-3"><ExchangeMark exchange={item.exchange} /><div className="min-w-0"><p className="truncate text-sm font-medium">{connectionDisplayName(item.connection_name, item.exchange)}</p><p className="muted mt-0.5 text-xs">{formatMoney(item.equity)}</p></div></div><Badge tone={item.status === "CONNECTED" ? "positive" : "warning"}>{item.completeness === "COMPLETE" ? "完整" : "部分"}</Badge></div>)}</div>
        {data.unvalued_asset_count > 0 && <div className="mt-5 rounded-xl bg-[var(--warning-soft)] p-3 text-xs text-[var(--warning)]"><div className="flex gap-2 font-semibold"><Coins className="h-4 w-4 shrink-0" />{data.unvalued_asset_count} 项资产暂时无法估值，未按 0 计入</div><div className="mt-2 space-y-2 pl-6">{(data.unvalued_assets ?? []).map((asset) => <div key={`${asset.exchange}-${asset.connection_name}-${asset.account_type}-${asset.asset}`}><p className="font-semibold text-[var(--text)]">{asset.asset} · {asset.exchange} / {asset.connection_name}</p><p className="mt-0.5 opacity-90">{asset.account_type} · 数量 {number(asset.quantity, 8)} · 估值源 {asset.price_source || "不可用"}</p></div>)}{(data.unvalued_assets ?? []).length === 0 && <p>当前同步批次未返回可定位的逐资产明细。</p>}</div></div>}
      </article>
    </section>

    <footer className="muted mt-5 grid gap-2 border-t pt-4 text-xs sm:grid-cols-2" style={{ borderColor: "var(--line)" }}><span>{data.notice}</span><span className="sm:text-right">统计开始时间：{dateTime(data.tracking_started_at)}</span><span>今日账户收益 = 当前权益 − 当日期初权益 − 今日净资金流</span><span className="sm:text-right">仓位敞口按所有当前衍生品绝对仓位价值求和</span></footer>
  </>;
}

function CoreSubMetric({ label, value }: { label: string; value: string }) {
  return <div><p className="metric-label">{label}</p><p className="mono-number mt-1 break-all text-sm font-semibold sm:text-base">{value}</p></div>;
}
function CoreMetric({ label, value, detail, tone = "neutral", icon, compact = false }: { label: string; value: string; detail?: string; tone?: Tone; icon: ReactNode; compact?: boolean }) {
  return <article className="cockpit-core-metric h-full"><div className="flex items-center justify-between gap-2"><p className="metric-label">{label}</p><span className={tone === "neutral" ? "text-[var(--muted)]" : toneClass(tone)}>{icon}</span></div><p className={`mono-number mt-2 break-words font-semibold ${compact ? "text-sm leading-5" : "text-lg"} ${toneClass(tone)}`}>{value}</p>{detail ? <p className="muted mt-1 text-[10px] leading-4">{detail}</p> : null}</article>;
}
function BreakdownRow({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return <div className="flex items-center justify-between gap-4 py-2.5 text-sm"><span className="muted">{label}</span><span className={`mono-number font-semibold ${toneClass(tone)}`}>{value}</span></div>;
}
function TodayBreakdown({ data, formatMoney }: { data: DashboardData; formatMoney: (value: number) => string }) {
  const today = data.today;
  if (!today.data_available) return <article className="panel min-w-0 p-5 md:p-6"><p className="section-label">今日收益组成</p><EmptyState title="今日组成数据待生成" description="本日首个完整账户快照产生后，这里会自动显示收益拆解。" /></article>;
  return <article className="panel min-w-0 p-5 md:p-6">
    <div className="flex items-start justify-between gap-3"><div><p className="section-label">今日收益组成</p><p className="muted mt-1 text-xs">交易记录组成与权益法账户收益并列核对</p></div><CircleDollarSign className="h-5 w-5 text-[var(--accent)]" /></div>
    <div className="mt-4 divide-y" style={{ borderColor: "var(--line)" }}><BreakdownRow label="已实现收益" value={formatMoney(today.realized_pnl)} tone={pnlTone(today.realized_pnl)} /><BreakdownRow label="当前未实现盈亏变化" value={formatMoney(today.unrealized_pnl_change)} tone={pnlTone(today.unrealized_pnl_change)} /><BreakdownRow label="Funding" value={formatMoney(today.funding_fee)} tone={pnlTone(today.funding_fee)} /><BreakdownRow label="Trading Fee" value={formatMoney(-Math.abs(today.trading_fee))} tone={today.trading_fee > 0 ? "negative" : "neutral"} /></div>
    <div className="mt-3 rounded-xl border p-4" style={{ borderColor: "var(--line-strong)", background: "var(--surface-soft)" }}><div className="flex items-center justify-between gap-4"><span className="text-sm font-semibold">今日账户收益</span><span className={`mono-number text-lg font-bold ${toneClass(pnlTone(today.net_return))}`}>{today.net_return > 0 ? "+" : ""}{formatMoney(today.net_return)}</span></div><p className="muted mt-2 text-[11px] leading-5">当前权益 − 当日期初权益 − 今日净资金流</p></div>
    <div className={`mt-3 rounded-xl p-3 text-xs leading-5 ${today.is_reconciled ? "bg-[var(--positive-soft)] text-[var(--positive)]" : "bg-[var(--warning-soft)] text-[var(--warning)]"}`}>{today.is_reconciled ? <>组成项合计 {formatMoney(today.component_return)}，与账户收益口径已对齐。</> : <>组成项合计 {formatMoney(today.component_return)}，与权益法账户收益相差 {formatMoney(today.reconciliation_difference)}。差额保留展示，未强行合并。</>}{today.net_cash_flow !== 0 && <span className="mt-1 block">今日净资金流 {formatMoney(today.net_cash_flow)} 已从账户收益中剔除。</span>}</div>
  </article>;
}
function RiskCard({ label, value, detail, tone = "neutral" }: { label: string; value: string; detail: string; tone?: Tone }) {
  return <article className="border-t p-4 first:border-t-0 sm:border-l sm:odd:border-l-0 sm:first:border-l-0 xl:border-t-0 xl:odd:border-l xl:first:border-l-0" style={{ borderColor: "var(--line)" }}><p className="metric-label">{label}</p><p className={`mono-number mt-2 text-lg font-semibold ${toneClass(tone)}`}>{value}</p><p className="muted mt-1 text-[11px] leading-5">{detail}</p></article>;
}
