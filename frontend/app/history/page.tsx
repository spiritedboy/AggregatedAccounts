"use client";

import { ChevronDown, Download, Filter, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useCurrency } from "@/components/app-shell";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import { CalculationHint } from "@/components/calculation-hint";
import { ProtectedPage } from "@/components/protected-page";
import { PositionLabel } from "@/components/position-label";
import { SortButton, type SortDirection } from "@/components/sort-button";
import { readPageFilters, useUrlFilterSync } from "@/components/use-url-filter-sync";
import { Badge, EmptyState, ErrorState, FilterPanel, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, exchangeDisplayName, number, positionSideLabel, usd } from "@/lib/format";
import type { ClosedPosition, ExchangeAccount } from "@/lib/types";

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
  const [accountId, setAccountId] = useState("");
  const [side, setSide] = useState("");
  const [pnlResult, setPnlResult] = useState("");
  const [completeness, setCompleteness] = useState("");
  const [symbol, setSymbol] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(1);
  const [netPnlSort, setNetPnlSort] = useState<SortDirection>("none");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<ExchangeAccount[]>([]);
  const [urlReady, setUrlReady] = useState(false);
  const { formatMoney } = useCurrency();

  const params = useCallback(() => {
    const query = new URLSearchParams({ page: String(page), page_size: "20" });
    if (exchange) query.set("exchange", exchange);
    if (accountId) query.set("account_id", accountId);
    if (side) query.set("side", side);
    if (pnlResult) query.set("pnl_result", pnlResult);
    if (completeness) query.set("completeness", completeness);
    if (symbol) query.set("symbol", symbol);
    if (start) query.set("start_time", new Date(`${start}T00:00:00`).toISOString());
    if (end) query.set("end_time", new Date(`${end}T23:59:59`).toISOString());
    return query;
  }, [accountId, completeness, end, exchange, page, pnlResult, side, start, symbol]);

  const load = useCallback(() => {
    setError("");
    return apiFetch<HistoryResult>(`/api/positions/history?${params()}`)
      .then((nextResult) => {
        setResult(nextResult);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason) => setError(reason.message));
  }, [params]);

  useEffect(() => {
    const query = readPageFilters("/history");
    if (query) {
      setExchange(query.get("exchange") ?? "");
      setAccountId(query.get("account") ?? "");
      setSide(query.get("side") ?? "");
      setPnlResult(query.get("result") ?? "");
      setCompleteness(query.get("completeness") ?? "");
      setSymbol(query.get("symbol") ?? "");
      setStart(query.get("start") ?? "");
      setEnd(query.get("end") ?? "");
      const nextPage = Number(query.get("page"));
      if (Number.isInteger(nextPage) && nextPage > 0) setPage(nextPage);
      const sort = query.get("sort");
      if (sort === "asc" || sort === "desc") setNetPnlSort(sort);
    }
    setUrlReady(true);
  }, []);
  useEffect(() => {
    if (urlReady) void load();
  }, [load, urlReady]);
  useEffect(() => {
    void apiFetch<ExchangeAccount[]>("/api/exchange-accounts").then(setAccounts);
  }, []);
  const autoRefresh = useAutoRefresh(load);
  useUrlFilterSync("/history", urlReady, {
    exchange,
    account: accountId,
    side,
    result: pnlResult,
    completeness,
    symbol,
    start,
    end,
    page,
    sort: netPnlSort === "none" ? "" : netPnlSort,
  });
  const sortedItems = useMemo(() => {
    const items = [...(result?.items ?? [])];
    if (netPnlSort === "none") return items;
    return items.sort((left, right) => {
      const difference = left.net_pnl - right.net_pnl;
      return netPnlSort === "asc" ? difference : -difference;
    });
  }, [netPnlSort, result?.items]);

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
          <div className="flex w-full min-w-0 flex-wrap items-center gap-2 md:w-auto md:justify-end">
            <AutoRefreshStatus state={autoRefresh} lastUpdatedAt={lastLoadedAt} />
            <button type="button" className="button-secondary" onClick={exportCsv}>
              <Download className="h-4 w-4" />
              导出 CSV
            </button>
          </div>
        }
      />

      <FilterPanel
        activeCount={[accountId, side, pnlResult, completeness, start, end].filter(Boolean).length}
        desktopClassName="md:grid-cols-2 xl:grid-cols-4"
        primary={<>
        <label className="relative">
          <Search className="muted absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2" />
          <input className="input pl-10" value={symbol} onChange={(event) => { setPage(1); setSymbol(event.target.value); }} placeholder="交易对" aria-label="搜索交易对" />
        </label>
        <Select value={exchange} onChange={(value) => { setPage(1); setExchange(value); }} label="交易所">
          <option value="">全部交易所</option>
          <option value="BINANCE">Binance</option>
          <option value="OKX">OKX</option>
          <option value="BITGET">Bitget</option>
          <option value="BYBIT">Bybit</option>
          <option value="HYPERLIQUID">Hyperliquid</option>
          <option value="POLYMARKET">Polymarket</option>
        </Select>
        </>}
        secondary={<>
        <Select value={accountId} onChange={(value) => { setPage(1); setAccountId(value); }} label="账户">
          <option value="">全部账户</option>
          {accounts
            .filter((account) => !exchange || account.exchange === exchange)
            .map((account) => (
              <option key={account.id} value={account.id}>{account.connection_name}</option>
            ))}
        </Select>
        <Select value={side} onChange={(value) => { setPage(1); setSide(value); }} label="方向">
          <option value="">全部方向</option>
          <option value="LONG">做多</option>
          <option value="SHORT">做空</option>
        </Select>
        <Select value={pnlResult} onChange={(value) => { setPage(1); setPnlResult(value); }} label="盈亏">
          <option value="">全部盈亏</option>
          <option value="PROFIT">盈利</option>
          <option value="LOSS">亏损</option>
          <option value="BREAKEVEN">持平</option>
        </Select>
        <Select value={completeness} onChange={(value) => { setPage(1); setCompleteness(value); }} label="完整性">
          <option value="">全部完整性</option>
          <option value="COMPLETE">完整</option>
          <option value="PARTIAL">部分完整</option>
        </Select>
        <label>
          <span className="sr-only">开始日期</span>
          <input className="input" type="date" value={start} onChange={(event) => { setPage(1); setStart(event.target.value); }} />
        </label>
        <label>
          <span className="sr-only">结束日期</span>
          <input className="input" type="date" value={end} onChange={(event) => { setPage(1); setEnd(event.target.value); }} />
        </label>
        </>}
      />

      {result && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 px-1">
          <p className="muted text-xs">
            共 <span className="mono-number font-semibold text-[var(--text)]">{result.total}</span> 条历史记录
          </p>
          {(exchange || accountId || side || pnlResult || completeness || symbol || start || end) && (
            <button
              type="button"
              className="text-xs font-semibold text-[var(--accent)]"
              onClick={() => {
                setPage(1);
                setExchange("");
                setAccountId("");
                setSide("");
                setPnlResult("");
                setCompleteness("");
                setSymbol("");
                setStart("");
                setEnd("");
              }}
            >
              清除筛选
            </button>
          )}
        </div>
      )}

      {error ? (
        <ErrorState message={error} retry={load} />
      ) : !result ? (
        <LoadingState rows={7} />
      ) : result.items.length === 0 ? (
        <div className="panel"><EmptyState title="没有历史仓位" description="当前筛选范围内没有已关闭仓位。" /></div>
      ) : (
        <>
          <div className="table-shell table-shell-sticky hidden lg:block">
            <table className="data-table min-w-[1040px]">
              <thead>
                <tr>
                  {["交易对", "方向", "开仓 / 平仓时间", "均价", "最大数量", "已实现收益", "费用", "净收益", "数据来源"].map((title) => (
                    <th
                      key={title}
                      data-numeric={["均价", "最大数量", "已实现收益", "费用", "净收益"].includes(title)}
                    >
                      {title === "净收益" ? (
                        <span className="inline-flex items-center whitespace-nowrap">
                          {title}
                          <CalculationHint
                            label="历史仓位收益率"
                            text="有可靠本金时显示杠杆收益率：净收益 ÷ 仓位本金 × 100%。缺少历史杠杆时改为显示开仓价到平仓价的价格变动，做空仓位按反方向计算。"
                          />
                          <SortButton
                            direction={netPnlSort}
                            label="净收益"
                            onChange={setNetPnlSort}
                          />
                        </span>
                      ) : title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((position) => (
                  <tr key={position.id}>
                    <td>
                      <div className="max-w-md">
                        <PositionLabel position={position} />
                      </div>
                      <p className="muted mt-1 text-xs">{exchangeDisplayName(position.exchange)}</p>
                    </td>
                    <td><Badge tone={position.side === "LONG" ? "positive" : "negative"}>{positionSideLabel(position.side, position.exchange)}</Badge></td>
                    <td>
                      <p className="text-xs">{dateTime(position.open_time)}</p>
                      <p className="muted mt-1 text-xs">{dateTime(position.close_time)}</p>
                    </td>
                    <td className="mono-number" data-numeric="true">
                      <p>{usd(position.average_entry_price)}</p>
                      <p className="muted mt-1 text-xs">{usd(position.average_exit_price)}</p>
                    </td>
                    <td className="mono-number" data-numeric="true">{number(position.max_position_size)}</td>
                    <td className={`mono-number ${position.realized_pnl >= 0 ? "text-positive" : "text-negative"}`} data-numeric="true">{formatMoney(position.realized_pnl)}</td>
                    <td className="mono-number muted text-xs" data-numeric="true">{formatMoney(position.funding_fee - position.trading_fee)}</td>
                    <td className={`mono-number font-semibold ${position.net_pnl >= 0 ? "text-positive" : "text-negative"}`} data-numeric="true">
                      {formatMoney(position.net_pnl)}
                      <p className="mt-1 text-xs">
                        {historicalReturnLabel(position)}
                      </p>
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-1.5">
                        <Badge
                          tone={position.data_source === "EXCHANGE_API" ? "mint" : "warning"}
                        >
                          {position.data_source === "EXCHANGE_API"
                            ? "交易所 API"
                            : position.data_source === "EXCHANGE_FILLS"
                              ? "交易所成交 API"
                              : "本地重建"}
                        </Badge>
                        <Badge tone={position.data_completeness === "COMPLETE" ? "positive" : "warning"}>
                          {position.data_completeness === "COMPLETE" ? "完整" : "部分完整"}
                        </Badge>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 lg:hidden">
            {sortedItems.map((position) => (
              <article key={position.id} className="panel min-w-0 overflow-hidden p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <PositionLabel position={position} />
                    <p className="muted mt-1 truncate text-xs">{exchangeDisplayName(position.exchange)} · 平仓于 {dateTime(position.close_time)}</p>
                  </div>
                  <span className="shrink-0">
                    <Badge tone={position.side === "LONG" ? "positive" : "negative"}>
                      {positionSideLabel(position.side, position.exchange)}
                    </Badge>
                  </span>
                </div>
                <div className="mt-4 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3">
                  <div className="soft-block min-w-0 overflow-hidden p-3">
                    <p className="metric-label">
                      净收益
                      <CalculationHint
                        label="历史仓位收益率"
                        text="有可靠本金时显示杠杆收益率；缺少历史杠杆时显示开仓价到平仓价的价格变动，做空仓位按反方向计算。"
                      />
                    </p>
                    <p className={`mono-number mt-1 break-words text-sm font-semibold ${position.net_pnl >= 0 ? "text-positive" : "text-negative"}`}>
                      {formatMoney(position.net_pnl)}
                    </p>
                    <p className="muted mono-number mt-1 text-[11px]">
                      {historicalReturnLabel(position)}
                    </p>
                  </div>
                  <div className="soft-block min-w-0 overflow-hidden p-3">
                    <p className="metric-label">开仓 / 平仓均价</p>
                    <p className="mono-number mt-1 truncate text-xs" title={usd(position.average_entry_price)}>{usd(position.average_entry_price)}</p>
                    <p className="muted mono-number mt-1 truncate text-[11px]" title={usd(position.average_exit_price)}>{usd(position.average_exit_price)}</p>
                  </div>
                </div>
                <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border px-3 py-2 text-[11px]" style={{ borderColor: "var(--line)", background: "var(--surface-soft)" }}>
                  <span className="muted">费用（资金费 − 手续费）</span>
                  <span className="mono-number shrink-0 font-semibold">
                    {formatMoney(position.funding_fee - position.trading_fee)}
                  </span>
                </div>
                <details className="group mt-3 rounded-xl border" style={{ borderColor: "var(--line)" }}>
                  <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between px-3 text-xs font-semibold [&::-webkit-details-marker]:hidden">
                    查看完整明细
                    <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                  </summary>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-3 border-t p-3 text-xs" style={{ borderColor: "var(--line)" }}>
                    <HistoryDetail label="开仓时间" value={dateTime(position.open_time)} />
                    <HistoryDetail label="平仓时间" value={dateTime(position.close_time)} />
                    <HistoryDetail label="最大数量" value={number(position.max_position_size)} mono />
                    <HistoryDetail label="已实现毛收益" value={formatMoney(position.realized_pnl)} mono />
                    <HistoryDetail label="资金费" value={formatMoney(position.funding_fee)} mono />
                    <HistoryDetail label="手续费" value={formatMoney(position.trading_fee)} mono />
                    <div className="col-span-2 flex flex-wrap gap-1.5 pt-1">
                      <Badge tone={position.data_source === "EXCHANGE_API" ? "mint" : "warning"}>
                        {position.data_source === "EXCHANGE_API"
                          ? "交易所 API"
                          : position.data_source === "EXCHANGE_FILLS"
                            ? "交易所成交 API"
                            : "本地重建"}
                      </Badge>
                      <Badge tone={position.data_completeness === "COMPLETE" ? "positive" : "warning"}>
                        {position.data_completeness === "COMPLETE" ? "数据完整" : "部分完整"}
                      </Badge>
                    </div>
                  </div>
                </details>
              </article>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="muted text-xs">第 {page} 页 · 每页 20 条</p>
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

function historicalReturnLabel(position: ClosedPosition) {
  if (position.margin_used > 0) return `${number(position.return_percent, 2)}%`;
  if (position.average_entry_price <= 0) return "价格变动 --";
  const direction = position.side === "SHORT" ? -1 : 1;
  const priceChange =
    ((position.average_exit_price - position.average_entry_price) /
      position.average_entry_price) *
    100 *
    direction;
  return `价格变动 ${priceChange >= 0 ? "+" : ""}${number(priceChange, 2)}%`;
}

function HistoryDetail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <p className="metric-label">{label}</p>
      <p className={`mt-1 break-words ${mono ? "mono-number" : ""}`}>{value}</p>
    </div>
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
