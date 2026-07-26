"use client";

import { Filter, Search, SlidersHorizontal } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { usePrivacy } from "@/components/app-shell";
import { ProtectedPage } from "@/components/protected-page";
import { Badge, EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, number, usd } from "@/lib/format";
import type { Position } from "@/lib/types";

type PositionResult = { items: Position[]; total: number };

export default function PositionsPage() {
  return (
    <ProtectedPage>
      <PositionsContent />
    </ProtectedPage>
  );
}

function PositionsContent() {
  const [result, setResult] = useState<PositionResult | null>(null);
  const [error, setError] = useState("");
  const [exchange, setExchange] = useState("");
  const [side, setSide] = useState("");
  const [symbol, setSymbol] = useState("");
  const [sort, setSort] = useState<"value" | "pnl">("value");
  const { hidden } = usePrivacy();

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (exchange) params.set("exchange", exchange);
    if (side) params.set("side", side);
    if (symbol) params.set("symbol", symbol);
    setError("");
    apiFetch<PositionResult>(`/api/positions/current?${params}`)
      .then(setResult)
      .catch((reason) => setError(reason.message));
  }, [exchange, side, symbol]);

  useEffect(load, [load]);

  const positions = useMemo(() => {
    const rows = [...(result?.items ?? [])];
    return rows.sort((a, b) =>
      sort === "value"
        ? b.position_value_usd - a.position_value_usd
        : b.tracking_unrealized_pnl_change - a.tracking_unrealized_pnl_change,
    );
  }, [result, sort]);

  return (
    <>
      <PageHeader
        eyebrow="Open exposure"
        title="当前仓位"
        description="统一查看各交易所当前敞口。页面没有平仓、杠杆调整或任何交易操作。"
        action={
          <Badge tone="mint">
            <SlidersHorizontal className="mr-1 h-3 w-3" />
            只读
          </Badge>
        }
      />

      <section className="panel mb-4 grid gap-3 p-3 sm:grid-cols-2 lg:grid-cols-[1.4fr_.8fr_.8fr_.8fr]">
        <label className="relative">
          <Search className="muted absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2" />
          <input
            className="input pl-10"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            placeholder="搜索交易对"
            aria-label="搜索交易对"
          />
        </label>
        <FilterSelect value={exchange} onChange={setExchange} label="交易所">
          <option value="">全部交易所</option>
          <option value="BINANCE">Binance</option>
          <option value="OKX">OKX</option>
          <option value="BITGET">Bitget</option>
          <option value="HYPERLIQUID">Hyperliquid</option>
        </FilterSelect>
        <FilterSelect value={side} onChange={setSide} label="方向">
          <option value="">全部方向</option>
          <option value="LONG">多仓</option>
          <option value="SHORT">空仓</option>
        </FilterSelect>
        <FilterSelect value={sort} onChange={(value) => setSort(value as "value" | "pnl")} label="排序">
          <option value="value">仓位价值</option>
          <option value="pnl">收益变化</option>
        </FilterSelect>
      </section>

      {error ? (
        <ErrorState message={error} retry={load} />
      ) : !result ? (
        <LoadingState rows={6} />
      ) : positions.length === 0 ? (
        <div className="panel">
          <EmptyState title="没有匹配仓位" description="调整筛选条件，或等待下一次账户同步。" />
        </div>
      ) : (
        <>
          <div className="panel hidden overflow-x-auto lg:block">
            <table className="w-full min-w-[1000px] text-left text-sm">
              <thead className="muted border-b text-[10px] uppercase tracking-wider" style={{ borderColor: "var(--line)" }}>
                <tr>
                  {["交易对 / 账户", "方向", "数量", "仓位价值", "入场 / 标记", "杠杆 / 保证金", "未实现收益变化", "更新时间"].map((title) => (
                    <th key={title} className="px-5 py-3.5 font-semibold">{title}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: "var(--line)" }}>
                {positions.map((position) => (
                  <tr key={position.id} className="transition hover:bg-black/[0.025] dark:hover:bg-white/[0.025]">
                    <td className="px-5 py-4">
                      <p className="font-mono font-semibold">{position.normalized_symbol}</p>
                      <p className="muted mt-1 text-xs">{position.exchange} · {position.market_type}</p>
                    </td>
                    <td className="px-5 py-4">
                      <Badge tone={position.side === "LONG" ? "positive" : "negative"}>
                        {position.side}
                      </Badge>
                    </td>
                    <td className="mono-number px-5 py-4">{number(position.position_size)}</td>
                    <td className="mono-number px-5 py-4">{usd(position.position_value_usd, hidden)}</td>
                    <td className="px-5 py-4">
                      <p className="mono-number">{usd(position.entry_price, hidden)}</p>
                      <p className="muted mono-number mt-1 text-xs">{usd(position.mark_price, hidden)}</p>
                    </td>
                    <td className="px-5 py-4">
                      <p className="mono-number">{number(position.leverage, 1)}×</p>
                      <p className="muted mt-1 text-xs">{position.margin_mode}</p>
                    </td>
                    <td className="px-5 py-4">
                      <p className={`mono-number font-semibold ${position.tracking_unrealized_pnl_change >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
                        {usd(position.tracking_unrealized_pnl_change, hidden)}
                      </p>
                      <p className="muted mono-number mt-1 text-xs">{number(position.unrealized_pnl_percent, 2)}%</p>
                    </td>
                    <td className="muted px-5 py-4 text-xs">{dateTime(position.update_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 lg:hidden">
            {positions.map((position) => (
              <article key={position.id} className="panel p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-mono font-semibold">{position.normalized_symbol}</p>
                    <p className="muted mt-1 text-xs">{position.exchange} · {position.margin_mode}</p>
                  </div>
                  <Badge tone={position.side === "LONG" ? "positive" : "negative"}>{position.side}</Badge>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-4">
                  <Metric label="仓位价值" value={usd(position.position_value_usd, hidden)} />
                  <Metric label="收益变化" value={usd(position.tracking_unrealized_pnl_change, hidden)} tone={position.tracking_unrealized_pnl_change >= 0 ? "positive" : "negative"} />
                  <Metric label="入场 / 标记" value={`${usd(position.entry_price, hidden)} / ${usd(position.mark_price, hidden)}`} />
                  <Metric label="数量 / 杠杆" value={`${number(position.position_size)} / ${number(position.leverage, 1)}×`} />
                </div>
                {position.is_initial_position && (
                  <p className="muted mt-4 border-t pt-3 text-[11px]" style={{ borderColor: "var(--line)" }}>
                    初始仓位：收益只计算添加 API Key 后的变化
                  </p>
                )}
              </article>
            ))}
          </div>
        </>
      )}
    </>
  );
}

function FilterSelect({
  value,
  onChange,
  label,
  children,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="relative">
      <span className="sr-only">{label}</span>
      <select className="input appearance-none pr-9" value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
      <Filter className="muted pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2" />
    </label>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div>
      <p className="muted text-[10px] uppercase tracking-wide">{label}</p>
      <p className={`mono-number mt-1 text-sm ${tone === "positive" ? "text-emerald-500" : tone === "negative" ? "text-rose-500" : ""}`}>{value}</p>
    </div>
  );
}
