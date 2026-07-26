"use client";

import type { EChartsOption } from "echarts";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  CircleDollarSign,
  Clock3,
  Coins,
  Gauge,
  ShieldAlert,
  Wallet,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Chart } from "@/components/chart";
import { ProtectedPage } from "@/components/protected-page";
import { Badge, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { usePrivacy } from "@/components/app-shell";
import { apiFetch } from "@/lib/api";
import { compactDate, dateTime, usd } from "@/lib/format";
import type { DashboardData } from "@/lib/types";

export default function DashboardPage() {
  return (
    <ProtectedPage>
      <DashboardContent />
    </ProtectedPage>
  );
}

function DashboardContent() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const { hidden } = usePrivacy();

  const load = useCallback(() => {
    setError("");
    apiFetch<DashboardData>("/api/dashboard/summary")
      .then(setData)
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(load, [load]);

  const equityOption = useMemo<EChartsOption>(
    () => ({
      animationDuration: 500,
      grid: { left: 8, right: 12, top: 18, bottom: 24, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#10201e",
        borderColor: "rgba(97,232,197,.2)",
        textStyle: { color: "#ebf7f3" },
        formatter: (params: unknown) => {
          const point = (params as Array<{ axisValue: string; value: number }>)[0];
          return `${point.axisValue}<br/><b>${usd(point.value, hidden)}</b>`;
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: data?.equity_curve.map((point) => compactDate(point.date)) ?? [],
        axisLine: { lineStyle: { color: "rgba(130,160,152,.18)" } },
        axisLabel: { color: "#7f968f", interval: 5 },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: { lineStyle: { color: "rgba(130,160,152,.09)" } },
        axisLabel: {
          color: "#7f968f",
          formatter: (value: number) => `${Math.round(value / 1000)}k`,
        },
      },
      series: [
        {
          type: "line",
          smooth: 0.35,
          symbol: "none",
          data: data?.equity_curve.map((point) => point.equity) ?? [],
          lineStyle: { color: "#33d6ad", width: 2.5 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(51,214,173,.30)" },
                { offset: 1, color: "rgba(51,214,173,0)" },
              ],
            },
          },
        },
      ],
    }),
    [data, hidden],
  );

  const allocationOption = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: "item", formatter: "{b}<br/>{d}%" },
      legend: {
        bottom: 0,
        textStyle: { color: "#82968f" },
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
                color: ["#33d6ad", "#699bf7", "#b785f5", "#f4b75f"][index],
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
  if (!data)
    return (
      <>
        <PageHeader eyebrow="Portfolio command" title="资产总览" description="正在建立安全数据视图…" />
        <LoadingState rows={6} />
      </>
    );

  const cards = [
    {
      label: "估算总权益",
      value: data.estimated_total_equity,
      detail: `${data.by_exchange.length} 个连接账户`,
      icon: Wallet,
      tone: "neutral",
    },
    {
      label: "今日收益",
      value: data.today_pnl,
      detail: data.today_pnl >= 0 ? "当日净变化" : "注意当日回撤",
      icon: data.today_pnl >= 0 ? ArrowUpRight : ArrowDownRight,
      tone: data.today_pnl >= 0 ? "positive" : "negative",
    },
    {
      label: "累计收益",
      value: data.cumulative_pnl,
      detail: "仅当前统计周期",
      icon: CircleDollarSign,
      tone: data.cumulative_pnl >= 0 ? "positive" : "negative",
    },
    {
      label: "未实现收益变化",
      value: data.unrealized_pnl_change,
      detail: "已扣除初始仓位基线",
      icon: Activity,
      tone: data.unrealized_pnl_change >= 0 ? "positive" : "negative",
    },
  ];

  return (
    <>
      {data.demo_mode && (
        <div className="mb-5 flex items-center gap-2 rounded-xl border border-mint-400/20 bg-mint-400/10 px-4 py-3 text-sm text-mint-500 dark:text-mint-300">
          <ShieldAlert className="h-4 w-4" />
          当前为演示数据，与真实账户数据严格隔离
        </div>
      )}
      <PageHeader
        eyebrow="Portfolio command"
        title="资产总览"
        description="跨交易所权益、风险敞口与统计周期收益的一体化只读视图。"
        action={
          <div className="muted flex items-center gap-2 text-xs">
            <Clock3 className="h-4 w-4" />
            更新于 {dateTime(data.last_updated_at)}
          </div>
        }
      />

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => {
          const Icon = card.icon;
          const positive = card.tone === "positive";
          const negative = card.tone === "negative";
          return (
            <article key={card.label} className="panel p-5">
              <div className="flex items-start justify-between">
                <div>
                  <p className="muted text-xs font-medium">{card.label}</p>
                  <p
                    className={`mono-number mt-3 text-2xl font-semibold ${
                      positive ? "text-emerald-500" : negative ? "text-rose-500" : ""
                    }`}
                  >
                    {usd(card.value, hidden)}
                  </p>
                </div>
                <div className="grid h-9 w-9 place-items-center rounded-xl bg-mint-400/10 text-mint-400">
                  <Icon className="h-[18px] w-[18px]" />
                </div>
              </div>
              <p className="muted mt-4 text-xs">{card.detail}</p>
            </article>
          );
        })}
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.55fr_.75fr]">
        <article className="panel min-w-0 p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-semibold">净值曲线</p>
              <p className="muted mt-1 text-xs">过去 30 天 · USD 估值</p>
            </div>
            <Badge tone="mint">30D</Badge>
          </div>
          <div className="mt-3">
            <Chart option={equityOption} height={300} />
          </div>
        </article>
        <article className="panel min-w-0 p-5">
          <p className="font-semibold">资产分布</p>
          <p className="muted mt-1 text-xs">按交易所权益占比</p>
          <Chart option={allocationOption} height={300} />
        </article>
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_.95fr]">
        <article className="panel overflow-hidden">
          <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--line)" }}>
            <div>
              <p className="font-semibold">主要当前仓位</p>
              <p className="muted mt-1 text-xs">按仓位价值排序</p>
            </div>
            <a href="/positions" className="text-xs font-semibold text-mint-400">
              查看全部
            </a>
          </div>
          <div className="divide-y" style={{ borderColor: "var(--line)" }}>
            {data.positions.map((position) => (
              <div key={position.id} className="grid grid-cols-[1fr_auto] gap-4 px-5 py-4 sm:grid-cols-[1.1fr_.7fr_.7fr] sm:items-center">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="font-mono text-sm font-semibold">{position.normalized_symbol}</p>
                    <Badge tone={position.side === "LONG" ? "positive" : "negative"}>
                      {position.side}
                    </Badge>
                  </div>
                  <p className="muted mt-1 text-xs">{position.exchange} · {position.margin_mode}</p>
                </div>
                <div className="hidden sm:block">
                  <p className="muted text-[10px] uppercase">仓位价值</p>
                  <p className="mono-number mt-1 text-sm">{usd(position.position_value_usd, hidden)}</p>
                </div>
                <div className="text-right">
                  <p className="muted text-[10px] uppercase">收益变化</p>
                  <p className={`mono-number mt-1 text-sm ${position.tracking_unrealized_pnl_change >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
                    {usd(position.tracking_unrealized_pnl_change, hidden)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="panel p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-semibold">账户健康度</p>
              <p className="muted mt-1 text-xs">连接与数据完整性</p>
            </div>
            <Gauge className="h-5 w-5 text-mint-400" />
          </div>
          <div className="mt-5 space-y-4">
            {data.by_exchange.map((item) => (
              <div key={`${item.exchange}-${item.connection_name}`} className="flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-black/5 font-mono text-[11px] font-bold dark:bg-white/5">
                    {item.exchange.slice(0, 2)}
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{item.connection_name}</p>
                    <p className="muted mt-0.5 text-xs">{usd(item.equity, hidden)}</p>
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
              <p className="muted text-[10px] uppercase">可用余额</p>
              <p className="mono-number mt-1 text-sm">{usd(data.available_balance, hidden)}</p>
            </div>
            <div>
              <p className="muted text-[10px] uppercase">保证金占用</p>
              <p className="mono-number mt-1 text-sm">{usd(data.margin_used, hidden)}</p>
            </div>
          </div>
          {data.unvalued_asset_count > 0 && (
            <div className="mt-4 flex gap-2 rounded-xl bg-amber-500/10 p-3 text-xs text-amber-600 dark:text-amber-300">
              <Coins className="h-4 w-4 shrink-0" />
              {data.unvalued_asset_count} 项资产暂时无法估值，未按 0 计入。
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
