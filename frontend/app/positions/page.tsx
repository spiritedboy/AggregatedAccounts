"use client";

import { Filter, Search, SlidersHorizontal } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { usePrivacy } from "@/components/app-shell";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import { ProtectedPage } from "@/components/protected-page";
import { SortButton, type SortDirection } from "@/components/sort-button";
import { Badge, EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, number, positionSideLabel, usd } from "@/lib/format";
import type { ExchangeAccount, Position } from "@/lib/types";

type PositionResult = { items: Position[]; total: number };
type PositionSortField = "value" | "pnl";

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
  const [accountId, setAccountId] = useState("");
  const [side, setSide] = useState("");
  const [symbol, setSymbol] = useState("");
  const [sortField, setSortField] = useState<PositionSortField | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("none");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<ExchangeAccount[]>([]);
  const { hidden } = usePrivacy();

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (exchange) params.set("exchange", exchange);
    if (accountId) params.set("account_id", accountId);
    if (side) params.set("side", side);
    if (symbol) params.set("symbol", symbol);
    setError("");
    return apiFetch<PositionResult>(`/api/positions/current?${params}`)
      .then((nextResult) => {
        setResult(nextResult);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason) => setError(reason.message));
  }, [accountId, exchange, side, symbol]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    void apiFetch<ExchangeAccount[]>("/api/exchange-accounts").then(setAccounts);
  }, []);
  const autoRefresh = useAutoRefresh(load);

  const positions = useMemo(() => {
    const rows = [...(result?.items ?? [])];
    if (!sortField || sortDirection === "none") return rows;
    return rows.sort((left, right) => {
      const difference =
        sortField === "value"
          ? left.position_value_usd - right.position_value_usd
          : left.unrealized_pnl - right.unrealized_pnl;
      return sortDirection === "asc" ? difference : -difference;
    });
  }, [result?.items, sortDirection, sortField]);

  function changeSort(field: PositionSortField, direction: SortDirection) {
    setSortField(direction === "none" ? null : field);
    setSortDirection(direction);
  }

  function changeMobileSort(value: string) {
    if (value === "none") {
      setSortField(null);
      setSortDirection("none");
      return;
    }
    const [field, direction] = value.split("-") as [
      PositionSortField,
      Exclude<SortDirection, "none">,
    ];
    setSortField(field);
    setSortDirection(direction);
  }

  const valueSortDirection = sortField === "value" ? sortDirection : "none";
  const pnlSortDirection = sortField === "pnl" ? sortDirection : "none";
  const mobileSortValue =
    sortField && sortDirection !== "none"
      ? `${sortField}-${sortDirection}`
      : "none";
  const lastUpdatedAt =
    positions.reduce<string | null>(
      (latest, position) =>
        !latest || Date.parse(position.update_time) > Date.parse(latest)
          ? position.update_time
          : latest,
      null,
    ) ?? lastLoadedAt;

  return (
    <>
      <PageHeader
        eyebrow="仓位雷达"
        title="当前仓位"
        description="统一查看各交易所当前敞口。页面没有平仓、杠杆调整或任何交易操作。"
        action={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Badge tone="mint">
              <SlidersHorizontal className="mr-1 h-3 w-3" />
              只读
            </Badge>
            <AutoRefreshStatus state={autoRefresh} lastUpdatedAt={lastUpdatedAt} />
          </div>
        }
      />

      <section className="filter-panel sm:grid-cols-2 lg:grid-cols-4">
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
          <option value="POLYMARKET">Polymarket</option>
        </FilterSelect>
        <FilterSelect value={accountId} onChange={setAccountId} label="账户">
          <option value="">全部账户</option>
          {accounts
            .filter((account) => !exchange || account.exchange === exchange)
            .map((account) => (
              <option key={account.id} value={account.id}>{account.connection_name}</option>
            ))}
        </FilterSelect>
        <FilterSelect value={side} onChange={setSide} label="方向">
          <option value="">全部方向</option>
          <option value="LONG">做多</option>
          <option value="SHORT">做空</option>
        </FilterSelect>
        <div className="sm:col-span-2 lg:hidden">
          <FilterSelect value={mobileSortValue} onChange={changeMobileSort} label="排序">
            <option value="none">默认排序</option>
            <option value="value-asc">仓位价值升序</option>
            <option value="value-desc">仓位价值降序</option>
            <option value="pnl-asc">未实现盈亏升序</option>
            <option value="pnl-desc">未实现盈亏降序</option>
          </FilterSelect>
        </div>
      </section>

      {result && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 px-1">
          <p className="muted text-xs">
            当前显示 <span className="mono-number font-semibold text-[var(--text)]">{positions.length}</span> 个仓位
          </p>
          {(exchange || accountId || side || symbol) && (
            <button
              type="button"
              className="text-xs font-semibold text-[var(--accent)]"
              onClick={() => {
                setExchange("");
                setAccountId("");
                setSide("");
                setSymbol("");
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
        <LoadingState rows={6} />
      ) : positions.length === 0 ? (
        <div className="panel">
          <EmptyState title="没有匹配仓位" description="调整筛选条件，或等待下一次账户同步。" />
        </div>
      ) : (
        <>
          <div className="table-shell hidden lg:block">
            <table className="data-table min-w-[1000px]">
              <thead>
                <tr>
                  {["交易对 / 账户", "方向", "数量", "仓位价值", "入场 / 标记", "杠杆 / 保证金", "当前未实现盈亏", "更新时间"].map((title) => (
                    <th
                      key={title}
                      data-numeric={["数量", "仓位价值", "入场 / 标记", "杠杆 / 保证金", "当前未实现盈亏"].includes(title)}
                    >
                      {title === "仓位价值" ? (
                        <span className="inline-flex items-center whitespace-nowrap">
                          {title}
                          <SortButton
                            direction={valueSortDirection}
                            label="仓位价值"
                            onChange={(direction) => changeSort("value", direction)}
                          />
                        </span>
                      ) : title === "当前未实现盈亏" ? (
                        <span className="inline-flex items-center whitespace-nowrap">
                          {title}
                          <SortButton
                            direction={pnlSortDirection}
                            label="未实现盈亏"
                            onChange={(direction) => changeSort("pnl", direction)}
                          />
                        </span>
                      ) : title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map((position) => (
                  <tr key={position.id}>
                    <td>
                      <p className={position.exchange === "POLYMARKET" ? "max-w-md font-semibold" : "font-mono font-semibold"}>
                        {position.exchange === "POLYMARKET" ? position.symbol : position.normalized_symbol}
                      </p>
                      <p className="muted mt-1 text-xs">{position.exchange} · {position.market_type}</p>
                    </td>
                    <td>
                      <Badge tone={position.side === "LONG" ? "positive" : "negative"}>
                        {positionSideLabel(position.side, position.exchange)}
                      </Badge>
                    </td>
                    <td className="mono-number" data-numeric="true">{number(position.position_size)}</td>
                    <td className="mono-number" data-numeric="true">{usd(position.position_value_usd, hidden)}</td>
                    <td data-numeric="true">
                      <p className="mono-number">{usd(position.entry_price, hidden)}</p>
                      <p className="muted mono-number mt-1 text-xs">{usd(position.mark_price, hidden)}</p>
                    </td>
                    <td data-numeric="true">
                      <p className="mono-number">{number(position.leverage, 1)}×</p>
                      <p className="muted mt-1 text-xs">{position.margin_mode}</p>
                    </td>
                    <td data-numeric="true">
                      <p className={`mono-number font-semibold ${position.unrealized_pnl >= 0 ? "text-positive" : "text-negative"}`}>
                        {usd(position.unrealized_pnl, hidden)}
                      </p>
                      <p
                        className={`mono-number mt-1 inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${
                          position.unrealized_pnl_percent >= 0
                            ? "bg-[var(--positive-soft)] text-positive"
                            : "bg-[var(--negative-soft)] text-negative"
                        }`}
                      >
                        {number(position.unrealized_pnl_percent, 2)}%
                      </p>
                    </td>
                    <td className="muted whitespace-nowrap text-xs">{dateTime(position.update_time)}</td>
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
                    <p className={position.exchange === "POLYMARKET" ? "font-semibold" : "font-mono font-semibold"}>
                      {position.exchange === "POLYMARKET" ? position.symbol : position.normalized_symbol}
                    </p>
                    <p className="muted mt-1 text-xs">{position.exchange} · {position.margin_mode}</p>
                  </div>
                  <Badge tone={position.side === "LONG" ? "positive" : "negative"}>
                    {positionSideLabel(position.side, position.exchange)}
                  </Badge>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-4">
                  <Metric label="仓位价值" value={usd(position.position_value_usd, hidden)} />
                  <Metric label="当前未实现盈亏" value={usd(position.unrealized_pnl, hidden)} tone={position.unrealized_pnl >= 0 ? "positive" : "negative"} />
                  <Metric label="入场 / 标记" value={`${usd(position.entry_price, hidden)} / ${usd(position.mark_price, hidden)}`} />
                  <Metric label="数量 / 杠杆" value={`${number(position.position_size)} / ${number(position.leverage, 1)}×`} />
                </div>
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
      <p className="metric-label">{label}</p>
      <p className={`mono-number mt-1 text-sm ${tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : ""}`}>{value}</p>
    </div>
  );
}
