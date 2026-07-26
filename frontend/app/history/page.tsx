"use client";

import { Download, Filter, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { usePrivacy } from "@/components/app-shell";
import { ProtectedPage } from "@/components/protected-page";
import { Badge, EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, number, usd } from "@/lib/format";
import type { ClosedPosition } from "@/lib/types";

type HistoryResult = { items: ClosedPosition[]; total: number };

export default function HistoryPage() {
  return (
    <ProtectedPage>
      <HistoryContent />
    </ProtectedPage>
  );
}

function HistoryContent() {
  const [result, setResult] = useState<HistoryResult | null>(null);
  const [error, setError] = useState("");
  const [exchange, setExchange] = useState("");
  const [side, setSide] = useState("");
  const [symbol, setSymbol] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(1);
  const { hidden } = usePrivacy();

  const params = useCallback(() => {
    const query = new URLSearchParams({ page: String(page), page_size: "20" });
    if (exchange) query.set("exchange", exchange);
    if (side) query.set("side", side);
    if (symbol) query.set("symbol", symbol);
    if (start) query.set("start_time", new Date(`${start}T00:00:00`).toISOString());
    if (end) query.set("end_time", new Date(`${end}T23:59:59`).toISOString());
    return query;
  }, [end, exchange, page, side, start, symbol]);

  const load = useCallback(() => {
    setError("");
    apiFetch<HistoryResult>(`/api/positions/history?${params()}`)
      .then(setResult)
      .catch((reason) => setError(reason.message));
  }, [params]);

  useEffect(load, [load]);

  function exportCsv() {
    const query = params();
    query.delete("page");
    query.delete("page_size");
    window.location.assign(`/api/positions/history/export?${query}`);
  }

  return (
    <>
      <PageHeader
        eyebrow="交易足迹"
        title="历史仓位"
        description="只展示当前统计周期开始之后关闭的仓位；重建记录会明确标注来源。"
        action={
          <button type="button" className="button-secondary" onClick={exportCsv}>
            <Download className="h-4 w-4" />
            导出 CSV
          </button>
        }
      />

      <section className="panel mb-4 grid gap-3 p-3 sm:grid-cols-2 xl:grid-cols-[1.2fr_.7fr_.7fr_.8fr_.8fr]">
        <label className="relative">
          <Search className="muted absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2" />
          <input className="input pl-10" value={symbol} onChange={(event) => { setPage(1); setSymbol(event.target.value); }} placeholder="交易对" aria-label="搜索交易对" />
        </label>
        <Select value={exchange} onChange={(value) => { setPage(1); setExchange(value); }} label="交易所">
          <option value="">全部交易所</option>
          <option value="BINANCE">Binance</option>
          <option value="OKX">OKX</option>
          <option value="BITGET">Bitget</option>
          <option value="HYPERLIQUID">Hyperliquid</option>
        </Select>
        <Select value={side} onChange={(value) => { setPage(1); setSide(value); }} label="方向">
          <option value="">全部方向</option>
          <option value="LONG">多仓</option>
          <option value="SHORT">空仓</option>
        </Select>
        <label>
          <span className="sr-only">开始日期</span>
          <input className="input" type="date" value={start} onChange={(event) => { setPage(1); setStart(event.target.value); }} />
        </label>
        <label>
          <span className="sr-only">结束日期</span>
          <input className="input" type="date" value={end} onChange={(event) => { setPage(1); setEnd(event.target.value); }} />
        </label>
      </section>

      {error ? (
        <ErrorState message={error} retry={load} />
      ) : !result ? (
        <LoadingState rows={7} />
      ) : result.items.length === 0 ? (
        <div className="panel"><EmptyState title="没有历史仓位" description="当前筛选范围内没有已关闭仓位。" /></div>
      ) : (
        <>
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[1040px] text-left text-sm">
              <thead className="muted border-b text-[10px] uppercase tracking-wider" style={{ borderColor: "var(--line)" }}>
                <tr>
                  {["交易对", "方向", "开仓 / 平仓时间", "均价", "最大数量", "已实现收益", "费用", "净收益", "数据来源"].map((title) => (
                    <th key={title} className="px-5 py-3.5 font-semibold">{title}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: "var(--line)" }}>
                {result.items.map((position) => (
                  <tr key={position.id}>
                    <td className="px-5 py-4">
                      <p className="font-mono font-semibold">{position.normalized_symbol}</p>
                      <p className="muted mt-1 text-xs">{position.exchange}</p>
                    </td>
                    <td className="px-5 py-4"><Badge tone={position.side === "LONG" ? "positive" : "negative"}>{position.side}</Badge></td>
                    <td className="px-5 py-4">
                      <p className="text-xs">{dateTime(position.open_time)}</p>
                      <p className="muted mt-1 text-xs">{dateTime(position.close_time)}</p>
                    </td>
                    <td className="mono-number px-5 py-4">
                      <p>{usd(position.average_entry_price, hidden)}</p>
                      <p className="muted mt-1 text-xs">{usd(position.average_exit_price, hidden)}</p>
                    </td>
                    <td className="mono-number px-5 py-4">{number(position.max_position_size)}</td>
                    <td className={`mono-number px-5 py-4 ${position.realized_pnl >= 0 ? "text-emerald-500" : "text-rose-500"}`}>{usd(position.realized_pnl, hidden)}</td>
                    <td className="mono-number muted px-5 py-4 text-xs">{usd(position.funding_fee - position.trading_fee, hidden)}</td>
                    <td className={`mono-number px-5 py-4 font-semibold ${position.net_pnl >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
                      {usd(position.net_pnl, hidden)}
                      <p className="mt-1 text-xs">{number(position.return_percent, 2)}%</p>
                    </td>
                    <td className="px-5 py-4">
                      <Badge tone={position.data_source === "EXCHANGE_API" ? "mint" : "warning"}>
                        {position.data_source === "EXCHANGE_API" ? "交易所 API" : "本地重建"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center justify-between">
            <p className="muted text-xs">共 {result.total} 条记录</p>
            <div className="flex gap-2">
              <button type="button" className="button-secondary" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>上一页</button>
              <button type="button" className="button-secondary" disabled={page * 20 >= result.total} onClick={() => setPage((value) => value + 1)}>下一页</button>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function Select({ value, onChange, label, children }: { value: string; onChange: (value: string) => void; label: string; children: React.ReactNode }) {
  return (
    <label className="relative">
      <span className="sr-only">{label}</span>
      <select className="input appearance-none pr-9" value={value} onChange={(event) => onChange(event.target.value)}>{children}</select>
      <Filter className="muted pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2" />
    </label>
  );
}
