"use client";

import type { EChartsOption } from "echarts";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  CircleDollarSign,
  Coins,
  Gauge,
  Scale,
  ShieldAlert,
  Wallet,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Chart } from "@/components/chart";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import { ProtectedPage } from "@/components/protected-page";
import { PositionLabel } from "@/components/position-label";
import {
  Badge,
  ErrorState,
  ExchangeMark,
  LoadingState,
  MetricCard,
  PageHeader,
} from "@/components/ui";
import { useCurrency } from "@/components/app-shell";
import { apiFetch } from "@/lib/api";
import { dateTime, number, positionSideLabel, usd } from "@/lib/format";
import type {
  DashboardBootstrapData,
  DashboardData,
  EquityCurveData,
  EquityCurveRange,
  RiskData,
} from "@/lib/types";

const curveRanges: Array<{ value: EquityCurveRange; label: string }> = [
  { value: "1d", label: "1日" },
  { value: "1w", label: "1周" },
  { value: "1m", label: "1月" },
  { value: "6m", label: "半年" },
  { value: "1y", label: "1年" },
];

function equityAxisLabel(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 1_000_000) return `${number(value / 1_000_000, 2)}m`;
  if (magnitude >= 1_000) return `${number(value / 1_000, 2)}k`;
  return number(value, 2);
}

export default function DashboardPage() {
  return (
    <ProtectedPage>
      <DashboardContent />
    </ProtectedPage>
  );
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
    return apiFetch<DashboardBootstrapData>(
      `/api/dashboard/bootstrap?range=${curveRange}`,
    )
      .then((nextData) => {
        setData(nextData.dashboard);
        setRisk(nextData.risk);
        setCurve(nextData.equity_curve);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason) => setError(reason.message));
  }, [curveRange]);

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

  const equityOption = useMemo<EChartsOption>(
    () => ({
      animationDuration: 500,
      grid: { left: 8, right: 12, top: 18, bottom: 24, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#171b2e",
        borderColor: "#293047",
        textStyle: { color: "#f4f6ff" },
        formatter: (params: unknown) => {
          const point = (params as Array<{ axisValue: string; value: number }>)[0];
          const sourceValue = currency === "CNY" ? point.value / usdCnyRate : point.value;
          return `${dateTime(point.axisValue)}<br/><b>${formatMoney(sourceValue)}</b>`;
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: curve?.points.map((point) => point.timestamp) ?? [],
        axisLine: { lineStyle: { color: isDark ? "rgba(205,190,255,.24)" : "#cdd3e1" } },
        axisLabel: {
          color: isDark ? "#c3bad9" : "#687086",
          hideOverlap: true,
          formatter: (value: string) => {
            const current = new Date(value);
            if (curveRange === "1d" || curveRange === "1w") {
              return new Intl.DateTimeFormat("zh-CN", {
                month: "numeric",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              }).format(current);
            }
            return new Intl.DateTimeFormat("zh-CN", {
              month: "numeric",
              day: "numeric",
            }).format(current);
          },
        },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: { lineStyle: { color: isDark ? "rgba(205,190,255,.1)" : "rgba(104,112,134,.12)" } },
        axisLabel: {
          color: isDark ? "#c3bad9" : "#687086",
          formatter: (value: number) => `${currency === "CNY" ? "¥" : "$"}${equityAxisLabel(value)}`,
        },
      },
      series: [
        {
          type: "line",
          smooth: 0.35,
          symbol: "none",
          data: curve?.points.map((point) =>
            currency === "CNY" ? point.equity * usdCnyRate : point.equity,
          ) ?? [],
          lineStyle: { color: isDark ? "#62f1d6" : "#7c5cfc", width: isDark ? 3.5 : 3 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: isDark ? "rgba(98,241,214,.38)" : "rgba(124,92,252,.32)" },
                { offset: 0.55, color: isDark ? "rgba(170,140,255,.13)" : "rgba(32,189,169,.12)" },
                { offset: 1, color: isDark ? "rgba(98,241,214,0)" : "rgba(124,92,252,0)" },
              ],
            },
          },
        },
      ],
    }),
    [currency, curve, curveRange, formatMoney, isDark, usdCnyRate],
  );

  const allocationOption = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: "item", formatter: "{b}<br/>{d}%" },
      legend: {
        bottom: 0,
        textStyle: { color: "#687086" },
        icon: "circle",
      },
      series: [
        {
          type: "pie",
          radius: ["54%", "76%"],
          center: ["50%", "43%"],
          avoidLabelOverlap: true,
          itemStyle: { borderWidth: 4, borderColor: "transparent" },
          label: { show: false },
          data:
            data?.by_exchange.map((item, index) => ({
              name: item.exchange,
              value: item.equity,
              itemStyle: {
                color: ["#7c5cfc", "#20bda9", "#ee6ca8", "#e6a136", "#4b9ff4"][index % 5],
              },
            })) ?? [],
        },
      ],
    }),
    [data],
  );

  if (error)
    return (
      <ErrorState
        message={error}
        retry={load}
      />
    );
  if (!data || !risk || !curve)
    return (
      <>
        <PageHeader eyebrow="今天的钱包" title="资产总览" description="正在把资产拼成一张清晰的图…" />
        <LoadingState rows={6} />
      </>
    );

  return (
    <>
      {data.demo_mode && (
        <div className="mb-4 flex items-center gap-2 rounded-xl border border-[var(--accent)]/20 bg-[var(--accent-soft)] px-4 py-3 text-sm text-[var(--accent-strong)]">
          <ShieldAlert className="h-4 w-4" />
          当前为演示数据，与真实账户数据严格隔离
        </div>
      )}
      <PageHeader
        eyebrow="今天的钱包"
        title="资产总览"
        description="五个平台，一张轻松看懂的资产地图。"
        action={
          <AutoRefreshStatus
            state={autoRefresh}
            lastUpdatedAt={data.last_updated_at ?? lastLoadedAt}
          />
        }
      />

      <section className="grid gap-3 xl:grid-cols-[1.15fr_.85fr]">
        <MetricCard
          label="估算总权益"
          value={formatMoney(data.estimated_total_equity)}
          detail={
            <div className="mt-5 grid grid-cols-2 gap-3 border-t pt-4" style={{ borderColor: "var(--line)" }}>
              <div>
                <p className="metric-label">可用余额</p>
                <p className="mono-number mt-1 text-sm font-semibold">{formatMoney(data.available_balance)}</p>
              </div>
              <div>
                <p className="metric-label">保证金占用</p>
                <p className="mono-number mt-1 text-sm font-semibold">{formatMoney(data.margin_used)}</p>
              </div>
            </div>
          }
          icon={Wallet}
          tone="accent"
          featured
        />
        <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
          <MetricCard
            label="今日收益"
            value={formatMoney(data.today_pnl)}
            detail={data.today_pnl >= 0 ? "当日净变化" : "当日处于回撤"}
            icon={data.today_pnl >= 0 ? ArrowUpRight : ArrowDownRight}
            tone={data.today_pnl >= 0 ? "positive" : "negative"}
          />
          <MetricCard
            label="累计净收益"
            value={formatMoney(data.cumulative_net_pnl)}
            detail="已实现毛收益 + 资金费 − 手续费"
            icon={CircleDollarSign}
            tone={data.cumulative_net_pnl >= 0 ? "positive" : "negative"}
          />
          <MetricCard
            label="当前持仓收益"
            value={formatMoney(data.current_position_pnl)}
            detail="当前仓位“当前未实现盈亏”求和"
            icon={Activity}
            tone={data.current_position_pnl >= 0 ? "positive" : "negative"}
          />
        </div>
      </section>

      <section className="panel mt-4 grid gap-0 overflow-hidden md:grid-cols-4">
        <RiskCard label="最大回撤" value={`${number(risk.summary.max_drawdown_percent, 1)}%`} detail="每日权益口径" />
        <RiskCard label="交易所集中度" value={`${number(risk.summary.largest_exchange_concentration_percent, 1)}%`} detail="最大单一平台占比" />
        <RiskCard label="保证金使用率" value={`${number(risk.summary.margin_utilization_percent, 1)}%`} detail="保证金 ÷ 总权益" />
        <a href="/reconciliation" className="group border-t p-4 transition hover:bg-[var(--accent-soft)] md:border-l md:border-t-0" style={{ borderColor: "var(--line)" }}>
          <div className="flex items-center justify-between">
            <p className="metric-label">综合风险</p>
            <Scale className="h-4 w-4 text-[var(--accent)]" />
          </div>
          <p className={`mt-2 text-lg font-semibold ${risk.summary.risk_level === "HIGH" ? "text-negative" : risk.summary.risk_level === "MEDIUM" ? "text-warning" : "text-positive"}`}>
            {{ LOW: "低风险", MEDIUM: "中风险", HIGH: "高风险" }[risk.summary.risk_level]}
          </p>
          <p className="muted mt-1 text-[11px]">查看风险与收益对账 →</p>
        </a>
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.55fr_.75fr]">
        <article className="panel min-w-0 p-5 md:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="section-label">净值曲线</p>
              <p className="muted mt-1 text-xs">
                底层每 5 分钟采样 · 当前显示精度 {curve.resolution}
              </p>
              <p
                className={`mono-number mt-2 text-sm font-semibold ${
                  curve.change.amount === null
                    ? "muted"
                    : curve.change.amount > 0
                      ? "text-positive"
                      : curve.change.amount < 0
                        ? "text-negative"
                        : ""
                }`}
              >
                净值变化：
                {curve.change.amount === null
                  ? "—"
                  : `${curve.change.amount > 0 ? "+" : ""}${formatMoney(curve.change.amount)}`}
                {" "}
                (
                {curve.change.percent === null
                  ? "—"
                  : `${curve.change.percent > 0 ? "+" : ""}${number(curve.change.percent, 2)}%`}
                )
              </p>
            </div>
            <div
              className="inline-flex self-start rounded-xl border p-1"
              style={{ borderColor: "var(--line)", background: "var(--surface-soft)" }}
            >
              {curveRanges.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  aria-pressed={curveRange === item.value}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                    curveRange === item.value
                      ? "bg-[var(--accent)] text-white shadow-sm"
                      : "muted hover:bg-[var(--surface)] hover:text-[var(--text)]"
                  }`}
                  onClick={() => setCurveRange(item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-3">
            <Chart option={equityOption} height={300} />
          </div>
        </article>
        <article className="panel min-w-0 p-5 md:p-6">
          <p className="section-label">资产分布</p>
          <p className="muted mt-1 text-xs">按交易所权益占比</p>
          <Chart option={allocationOption} height={300} />
        </article>
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_.95fr]">
        <article className="data-panel">
          <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--line)" }}>
            <div>
              <p className="section-label">主要当前仓位</p>
              <p className="muted mt-1 text-xs">按仓位价值排序</p>
            </div>
            <a href="/positions" className="text-xs font-semibold text-[var(--accent)]">
              查看全部
            </a>
          </div>
          <div className="divide-y" style={{ borderColor: "var(--line)" }}>
            {data.positions.map((position) => (
              <div key={position.id} className="grid grid-cols-[1fr_auto] gap-4 px-5 py-4 sm:grid-cols-[1.1fr_.7fr_.7fr] sm:items-center">
                <div>
                  <div className="flex items-center gap-2">
                    <PositionLabel position={position} compact />
                    <Badge tone={position.side === "LONG" ? "positive" : "negative"}>
                      {positionSideLabel(position.side, position.exchange)}
                    </Badge>
                  </div>
                  <p className="muted mt-1 text-xs">{position.exchange} · {position.margin_mode}</p>
                </div>
                <div className="hidden sm:block">
                  <p className="metric-label">仓位价值</p>
                  <p className="mono-number mt-1 text-sm">{usd(position.position_value_usd)}</p>
                </div>
                <div className="text-right">
                  <p className="metric-label">当前未实现盈亏</p>
                  <p className={`mono-number mt-1 text-sm ${position.unrealized_pnl >= 0 ? "text-positive" : "text-negative"}`}>
                    {formatMoney(position.unrealized_pnl)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="panel p-5 md:p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="section-label">账户健康度</p>
              <p className="muted mt-1 text-xs">连接与数据完整性</p>
            </div>
            <Gauge className="h-5 w-5 text-[var(--aqua)]" />
          </div>
          <div className="mt-5 space-y-4">
            {data.by_exchange.map((item) => (
              <div key={`${item.exchange}-${item.connection_name}`} className="flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-3">
                  <ExchangeMark exchange={item.exchange} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{item.connection_name}</p>
                    <p className="muted mt-0.5 text-xs">{formatMoney(item.equity)}</p>
                  </div>
                </div>
                <Badge tone={item.status === "CONNECTED" ? "positive" : "warning"}>
                  {item.completeness === "COMPLETE" ? "完整" : "部分"}
                </Badge>
              </div>
            ))}
          </div>
          <div className="mt-6 grid grid-cols-2 gap-3 border-t pt-5" style={{ borderColor: "var(--line)" }}>
            <div>
              <p className="metric-label">可用余额</p>
              <p className="mono-number mt-1 text-sm">{formatMoney(data.available_balance)}</p>
            </div>
            <div>
              <p className="metric-label">保证金占用</p>
              <p className="mono-number mt-1 text-sm">{formatMoney(data.margin_used)}</p>
            </div>
          </div>
          {data.unvalued_asset_count > 0 && (
            <div className="mt-4 rounded-xl bg-[var(--warning-soft)] p-3 text-xs text-[var(--warning)]">
              <div className="flex gap-2 font-semibold">
                <Coins className="h-4 w-4 shrink-0" />
                {data.unvalued_asset_count} 项资产暂时无法估值，未按 0 计入
              </div>
              <div className="mt-2 space-y-2 pl-6">
                {(data.unvalued_assets ?? []).map((asset) => (
                  <div key={`${asset.exchange}-${asset.connection_name}-${asset.account_type}-${asset.asset}`}>
                    <p className="font-semibold text-[var(--text)]">
                      {asset.asset} · {asset.exchange} / {asset.connection_name}
                    </p>
                    <p className="mt-0.5 opacity-90">
                      {asset.account_type} · 数量 {number(asset.quantity, 8)} · 估值源 {asset.price_source || "不可用"}
                    </p>
                  </div>
                ))}
                {(data.unvalued_assets ?? []).length === 0 && (
                  <p>当前同步批次未返回可定位的逐资产明细。</p>
                )}
              </div>
            </div>
          )}
        </article>
      </section>

      <footer className="muted mt-5 flex flex-col justify-between gap-2 text-xs sm:flex-row">
        <span>{data.notice}</span>
        <span>统计开始时间：{dateTime(data.tracking_started_at)}</span>
      </footer>
    </>
  );
}

function RiskCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="border-t p-4 first:border-t-0 md:border-l md:border-t-0 md:first:border-l-0" style={{ borderColor: "var(--line)" }}>
      <p className="metric-label">{label}</p>
      <p className="mono-number mt-2 text-lg font-semibold">{value}</p>
      <p className="muted mt-1 text-[11px]">{detail}</p>
    </article>
  );
}
