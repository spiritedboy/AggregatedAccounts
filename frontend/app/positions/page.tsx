"use client";

import { AlertTriangle, Filter, Search, SlidersHorizontal } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useCurrency } from "@/components/app-shell";
import { AutoRefreshStatus, RefreshErrorNotice, useAutoRefresh } from "@/components/auto-refresh-status";
import { CalculationHint } from "@/components/calculation-hint";
import { LiquidationRiskDisplay } from "@/components/liquidation-risk";
import { ProtectedPage } from "@/components/protected-page";
import { PositionLabel } from "@/components/position-label";
import { SortButton, type SortDirection } from "@/components/sort-button";
import { readPageFilters, useUrlFilterSync } from "@/components/use-url-filter-sync";
import { Badge, EmptyState, ErrorState, FilterPanel, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, exchangeDisplayName, number, positionSideLabel, usd } from "@/lib/format";
import type { ExchangeAccount, LiquidationRiskLevel, Position } from "@/lib/types";

type PositionResult = { items: Position[]; total: number };
type PositionSortField = "value" | "pnl" | "liquidation";
type LiquidationRiskFilter = "" | LiquidationRiskLevel | "NO_DATA";

export default function PositionsPage() {
  return (
    <ProtectedPage>
      <PositionsContent />
    </ProtectedPage>
  );
}

function PositionsContent() {
  const [fetchedResult, setResult] = useState<PositionResult | null>(null);
  const [loadedFilterKey, setLoadedFilterKey] = useState("");
  const latestRequest = useRef(0);
  const [error, setError] = useState("");
  const [exchange, setExchange] = useState("");
  const [accountId, setAccountId] = useState("");
  const [side, setSide] = useState("");
  const [symbol, setSymbol] = useState("");
  const [liquidationRisk, setLiquidationRisk] = useState<LiquidationRiskFilter>("");
  const [focusPositionId, setFocusPositionId] = useState("");
  const [sortField, setSortField] = useState<PositionSortField | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("none");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<ExchangeAccount[]>([]);
  const [urlReady, setUrlReady] = useState(false);
  const { formatMoney, formatSignedMoney } = useCurrency();

  const filterParams = new URLSearchParams();
  if (exchange) filterParams.set("exchange", exchange);
  if (accountId) filterParams.set("account_id", accountId);
  if (side) filterParams.set("side", side);
  if (symbol) filterParams.set("symbol", symbol);
  const filterKey = filterParams.toString();
  const result = loadedFilterKey === filterKey ? fetchedResult : null;

  const load = useCallback(() => {
    const requestId = ++latestRequest.current;
    setError("");
    const base = new URLSearchParams(filterKey);
    base.set("page_size", "200");
    base.set("page", "1");
    return apiFetch<PositionResult>(`/api/positions/current?${base}`)
      .then(async (firstPage) => {
        const pageCount = Math.ceil(firstPage.total / 200);
        const remaining: PositionResult[] = [];
        for (let start = 2; start <= pageCount; start += 4) {
          const batch = await Promise.all(Array.from({ length: Math.min(4, pageCount - start + 1) }, (_, index) => {
            const params = new URLSearchParams(base);
            params.set("page", String(start + index));
            return apiFetch<PositionResult>(`/api/positions/current?${params}`);
          }));
          remaining.push(...batch);
          if (requestId !== latestRequest.current) return;
        }
        if (requestId !== latestRequest.current) return;
        const items = [firstPage, ...remaining].flatMap((pageResult) => pageResult.items);
        if (items.length !== firstPage.total || new Set(items.map((item) => item.id)).size !== firstPage.total) {
          throw new Error("仓位在分页读取期间发生变化，请重试以获取完整结果");
        }
        setResult({ items, total: firstPage.total });
        setLoadedFilterKey(filterKey);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason) => {
        if (requestId === latestRequest.current) setError(reason instanceof Error ? reason.message : "仓位加载失败");
      });
  }, [filterKey]);

  useEffect(() => {
    const query = readPageFilters("/positions");
    if (query) {
      setExchange(query.get("exchange") ?? "");
      setAccountId(query.get("account") ?? "");
      setSide(query.get("side") ?? "");
      setSymbol(query.get("symbol") ?? "");
      const risk = query.get("risk") ?? "";
      if (["SAFE", "WATCH", "DANGER", "NO_DATA"].includes(risk)) {
        setLiquidationRisk(risk as LiquidationRiskFilter);
      }
      setFocusPositionId(query.get("focus") ?? "");
      const [field, direction] = (query.get("sort") ?? "").split("-");
      if ((field === "value" || field === "pnl" || field === "liquidation") && (direction === "asc" || direction === "desc")) {
        setSortField(field);
        setSortDirection(direction);
      }
      const savedPage = Number(query.get("page"));
      if (Number.isInteger(savedPage) && savedPage > 0) setPage(savedPage);
      const savedPageSize = Number(query.get("page_size"));
      if ([20, 50, 100].includes(savedPageSize)) setPageSize(savedPageSize);
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
  useUrlFilterSync("/positions", urlReady, {
    exchange,
    account: accountId,
    side,
    symbol,
    risk: liquidationRisk,
    focus: focusPositionId,
    sort: sortField && sortDirection !== "none" ? `${sortField}-${sortDirection}` : "",
    page,
    page_size: pageSize === 20 ? "" : pageSize,
  });

  const positions = useMemo(() => {
    const rows = (result?.items ?? []).filter((position) => {
      if (!liquidationRisk) return true;
      if (liquidationRisk === "NO_DATA") return position.liquidation_risk_level === null;
      return position.liquidation_risk_level === liquidationRisk;
    });
    if (!sortField || sortDirection === "none") return rows;
    return rows.sort((left, right) => {
      if (sortField === "liquidation") {
        const leftDistance = left.liquidation_distance_percent;
        const rightDistance = right.liquidation_distance_percent;
        if (leftDistance === null) return 1;
        if (rightDistance === null) return -1;
        return sortDirection === "asc" ? leftDistance - rightDistance : rightDistance - leftDistance;
      }
      const difference = sortField === "value"
        ? left.position_value_usd - right.position_value_usd
        : left.unrealized_pnl - right.unrealized_pnl;
      return sortDirection === "asc" ? difference : -difference;
    });
  }, [liquidationRisk, result?.items, sortDirection, sortField]);

  const pageCount = Math.max(1, Math.ceil(positions.length / pageSize));
  const displayedPage = Math.min(page, pageCount);
  const pagePositions = positions.slice((displayedPage - 1) * pageSize, displayedPage * pageSize);
  useEffect(() => {
    if (result && page > pageCount) setPage(pageCount);
  }, [page, pageCount, result]);

  useEffect(() => {
    if (!focusPositionId || !result) return;
    const index = positions.findIndex((position) => position.id === focusPositionId);
    if (index >= 0) setPage(Math.floor(index / pageSize) + 1);
  }, [focusPositionId, pageSize, positions, result]);

  useEffect(() => {
    if (!focusPositionId || positions.length === 0) return;
    const desktop = window.matchMedia?.("(min-width: 1024px)").matches ?? false;
    const element = document.getElementById(
      `position-${focusPositionId}-${desktop ? "desktop" : "mobile"}`,
    );
    element?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [displayedPage, focusPositionId, positions]);
  useEffect(() => {
    if (result && focusPositionId && !positions.some((position) => position.id === focusPositionId)) {
      setFocusPositionId("");
    }
  }, [focusPositionId, positions, result]);

  function changeSort(field: PositionSortField, direction: SortDirection) {
    setPage(1);
    setSortField(direction === "none" ? null : field);
    setSortDirection(direction);
  }

  function changeMobileSort(value: string) {
    setPage(1);
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
  const liquidationSortDirection = sortField === "liquidation" ? sortDirection : "none";
  const mobileSortValue =
    sortField && sortDirection !== "none"
      ? `${sortField}-${sortDirection}`
      : "none";
  const activeFilterCount = [
    exchange,
    accountId,
    side,
    symbol,
    liquidationRisk,
    mobileSortValue !== "none" ? mobileSortValue : "",
  ].filter(Boolean).length;
  const resetFilters = () => {
    setExchange("");
    setAccountId("");
    setSide("");
    setSymbol("");
    setLiquidationRisk("");
    setSortField(null);
    setSortDirection("none");
    setFocusPositionId("");
    setPage(1);
  };
  const lastUpdatedAt =
    positions.reduce<string | null>(
      (latest, position) =>
        !latest || Date.parse(position.update_time) < Date.parse(latest)
          ? position.update_time
          : latest,
      null,
    );
  const grossExposure = positions.reduce(
    (total, position) => total + Math.abs(position.position_value_usd),
    0,
  );
  const currentPnl = positions.reduce(
    (total, position) => total + position.unrealized_pnl,
    0,
  );

  return (
    <>
      <PageHeader
        eyebrow="仓位雷达"
        title="当前仓位"
        description={result ? `${positions.length} 个仓位 · Gross ${usd(grossExposure)} · PnL ${formatSignedMoney(currentPnl)}` : "正在读取各交易所当前敞口…"}
        action={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Badge tone="mint">
              <SlidersHorizontal className="mr-1 h-3 w-3" />
              只读
            </Badge>
            <AutoRefreshStatus state={autoRefresh} lastUpdatedAt={lastUpdatedAt} lastFetchedAt={lastLoadedAt} />
          </div>
        }
      />

      <FilterPanel
        activeCount={activeFilterCount}
        onReset={resetFilters}
        desktopClassName="md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5"
        primary={<>
        <label className="relative">
          <Search className="muted absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2" />
          <input
            className="input pl-10"
            value={symbol}
            onChange={(event) => { setSymbol(event.target.value); setPage(1); }}
            placeholder="搜索交易对 / 市场"
            aria-label="搜索交易对或市场"
          />
        </label>
        <FilterSelect value={exchange} onChange={(value) => { setExchange(value); setPage(1); }} label="交易所">
          <option value="">全部交易所</option>
          <option value="BINANCE">Binance</option>
          <option value="OKX">OKX</option>
          <option value="BITGET">Bitget</option>
          <option value="BYBIT">Bybit</option>
          <option value="HYPERLIQUID">Hyperliquid</option>
          <option value="POLYMARKET">Polymarket</option>
        </FilterSelect>
        </>}
        secondary={<>
        <FilterSelect value={accountId} onChange={(value) => { setAccountId(value); setPage(1); }} label="账户">
          <option value="">全部账户</option>
          {accounts
            .filter((account) => !exchange || account.exchange === exchange)
            .map((account) => (
              <option key={account.id} value={account.id}>{account.connection_name}</option>
            ))}
        </FilterSelect>
        <FilterSelect value={side} onChange={(value) => { setSide(value); setPage(1); }} label="方向">
          <option value="">全部方向</option>
          <option value="LONG">做多</option>
          <option value="SHORT">做空</option>
        </FilterSelect>
        <FilterSelect value={liquidationRisk} onChange={(value) => { setLiquidationRisk(value as LiquidationRiskFilter); setPage(1); }} label="强平风险">
          <option value="">全部强平风险</option>
          <option value="SAFE">正常</option>
          <option value="WATCH">关注</option>
          <option value="DANGER">危险</option>
          <option value="NO_DATA">无强平数据</option>
        </FilterSelect>
        <div className="md:hidden">
          <FilterSelect value={mobileSortValue} onChange={changeMobileSort} label="排序">
            <option value="none">默认排序</option>
            <option value="value-asc">仓位价值升序</option>
            <option value="value-desc">仓位价值降序</option>
            <option value="pnl-asc">未实现盈亏升序</option>
            <option value="pnl-desc">未实现盈亏降序</option>
            <option value="liquidation-asc">强平距离从近到远</option>
            <option value="liquidation-desc">强平距离从远到近</option>
          </FilterSelect>
        </div>
        </>}
      />

      {fetchedResult && <div className="mb-3 flex flex-wrap items-center justify-between gap-3 px-1">
        <p className="muted text-xs">{result ? `共 ${positions.length} 个匹配仓位 · 当前第 ${displayedPage}/${pageCount} 页` : "正在加载当前筛选结果…"}</p>
        <label className="flex items-center gap-2 text-xs"><span className="muted">每页</span><select className="input min-h-9 w-auto py-1" value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }} aria-label="每页仓位数"><option value={20}>20 条</option><option value={50}>50 条</option><option value={100}>100 条</option></select></label>
      </div>}

      {result && (
        <div className="mb-3 flex flex-wrap items-center gap-2 px-1">
          <p className="muted text-xs">
            当前显示 <span className="mono-number font-semibold text-[var(--text)]">{pagePositions.length}</span> / {positions.length} 个仓位
          </p>
          {activeFilterCount > 0 ? <span className="mono-number text-[10px] text-[var(--accent)]">{activeFilterCount} FILTERS</span> : null}
        </div>
      )}

      {error && result && <RefreshErrorNotice message={error} lastFetchedAt={lastLoadedAt} retry={() => void load()} />}
      {error && !result ? (
        <ErrorState message={error} retry={load} />
      ) : !result ? (
        <LoadingState rows={6} />
      ) : positions.length === 0 ? (
        <div className="panel">
          <EmptyState title="没有匹配仓位" description="调整筛选条件，或等待下一次账户同步。" />
        </div>
      ) : (
        <>
          <div className="table-shell table-shell-sticky hidden lg:block">
            <table className="data-table min-w-[1080px]">
              <thead>
                <tr>
                  {["交易对 / 账户", "方向", "数量", "仓位价值", "入场 / 标记", "杠杆 / 保证金", "强平风险", "当前未实现盈亏"].map((title) => (
                    <th
                      key={title}
                      data-numeric={["数量", "仓位价值", "入场 / 标记", "杠杆 / 保证金", "强平风险", "当前未实现盈亏"].includes(title)}
                    >
                      {title === "仓位价值" ? (
                        <span className="inline-flex items-center whitespace-nowrap">
                          {title}
                          <CalculationHint
                            label="仓位价值"
                            text="仓位价值 = 当前标记价格 × 仓位数量，用于衡量当前持仓敞口；该字段固定使用美元显示。"
                          />
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
                      ) : title === "强平风险" ? (
                        <span className="inline-flex items-center whitespace-nowrap">
                          {title}
                          <SortButton
                            direction={liquidationSortDirection}
                            label="强平距离"
                            onChange={(direction) => changeSort("liquidation", direction)}
                          />
                        </span>
                      ) : title === "杠杆 / 保证金" ? (
                        <span className="inline-flex items-center whitespace-nowrap">
                          {title}
                          <CalculationHint
                            label="仓位本金"
                            text="仓位本金 = 入场价 × 仓位数量 ÷ 杠杆倍数。这里展示的是建立该仓位所需的本金，不是当前仓位价值。"
                          />
                        </span>
                      ) : title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pagePositions.map((position) => (
                  <tr key={position.id} id={`position-${position.id}-desktop`} className={focusPositionId === position.id ? "bg-[var(--accent-soft)]" : undefined}>
                    <td>
                      <div className="max-w-md">
                        <PositionLabel position={position} />
                      </div>
                      <p className="muted mt-1 text-xs">{exchangeDisplayName(position.exchange)} · {position.market_type} · {dateTime(position.update_time)}</p>
                    </td>
                    <td>
                      <Badge tone={position.side === "LONG" ? "positive" : "negative"}>
                        {positionSideLabel(position.side, position.exchange)}
                      </Badge>
                    </td>
                    <td className="mono-number" data-numeric="true">{number(position.position_size)}</td>
                    <td className="mono-number" data-numeric="true">{usd(position.position_value_usd)}</td>
                    <td data-numeric="true">
                      <p className="mono-number">{usd(position.entry_price)}</p>
                      <p className="muted mono-number mt-1 text-xs">{usd(position.mark_price)}</p>
                    </td>
                    <td data-numeric="true">
                      <p className="mono-number">{number(position.leverage, 1)}×</p>
                      <p className="muted mt-1 text-xs">本金 {formatMoney(position.margin_used)}</p>
                    </td>
                    <td data-numeric="true">
                      <LiquidationRiskDisplay
                        liquidationPrice={position.liquidation_price}
                        distancePercent={position.liquidation_distance_percent}
                        riskLevel={position.liquidation_risk_level}
                        marginMode={position.margin_mode}
                      />
                    </td>
                    <td data-numeric="true">
                      <p className={`mono-number font-semibold ${position.unrealized_pnl >= 0 ? "text-positive" : "text-negative"}`}>
                        {formatSignedMoney(position.unrealized_pnl)}
                      </p>
                      <p className={`mono-number mt-1 text-xs font-semibold ${position.unrealized_pnl_percent >= 0 ? "text-positive" : "text-negative"}`}>
                        {position.unrealized_pnl_percent > 0 ? "+" : ""}{number(position.unrealized_pnl_percent, 2)}%
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 lg:hidden">
            {pagePositions.map((position) => (
              <article
                key={position.id}
                id={`position-${position.id}-mobile`}
                className={`panel min-w-0 overflow-hidden p-4 ${position.liquidation_risk_level === "DANGER" ? "border-l-4 !border-l-[var(--negative)] bg-[var(--negative-soft)]" : ""} ${focusPositionId === position.id ? "ring-2 ring-[var(--accent)]" : ""}`}
              >
                {position.liquidation_risk_level === "DANGER" ? (
                  <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-negative">
                    <AlertTriangle className="h-4 w-4" />高风险仓位 · 已进入强平危险区间
                  </div>
                ) : null}
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <PositionLabel position={position} />
                    <p className="muted mt-1 truncate text-xs">{exchangeDisplayName(position.exchange)}</p>
                  </div>
                  <span className="shrink-0">
                    <Badge tone={position.side === "LONG" ? "positive" : "negative"}>
                      {positionSideLabel(position.side, position.exchange)}
                    </Badge>
                  </span>
                </div>
                <div className="mt-4 grid min-w-0 grid-cols-2 gap-4">
                  <Metric label="仓位价值" value={usd(position.position_value_usd)} />
                  <div className="min-w-0">
                    <p className="metric-label mb-2">强平风险</p>
                    <LiquidationRiskDisplay
                      liquidationPrice={position.liquidation_price}
                      distancePercent={position.liquidation_distance_percent}
                      riskLevel={position.liquidation_risk_level}
                      marginMode={position.margin_mode}
                      compact
                    />
                  </div>
                  <Metric label="入场 / 标记" value={`${usd(position.entry_price)} / ${usd(position.mark_price)}`} />
                  <Metric label="杠杆 / 本金" hint="本金 = 入场价 × 仓位数量 ÷ 杠杆倍数。" value={`${number(position.leverage, 1)}× / ${formatMoney(position.margin_used)}`} />
                  <div className="col-span-2 rounded-[10px] border p-3" style={{ borderColor: "var(--line-strong)", background: "var(--surface-soft)" }}>
                    <Metric label="当前未实现盈亏" hint="收益率 = 当前未实现盈亏 ÷ 仓位本金 × 100%，已包含杠杆影响。" value={`${formatSignedMoney(position.unrealized_pnl)} · ${position.unrealized_pnl_percent > 0 ? "+" : ""}${number(position.unrealized_pnl_percent, 2)}%`} tone={position.unrealized_pnl >= 0 ? "positive" : "negative"} />
                  </div>
                </div>
              </article>
            ))}
          </div>
          <nav className="mt-4 flex flex-wrap items-center justify-between gap-3" aria-label="当前仓位分页">
            <p className="muted text-xs">第 {displayedPage} / {pageCount} 页 · 共 {positions.length} 个仓位</p>
            <div className="flex gap-2"><button type="button" className="button-secondary" disabled={displayedPage <= 1} onClick={() => setPage(displayedPage - 1)}>上一页</button><button type="button" className="button-secondary" disabled={displayedPage >= pageCount} onClick={() => setPage(displayedPage + 1)}>下一页</button></div>
          </nav>
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

function Metric({ label, value, tone, hint }: { label: string; value: string; tone?: "positive" | "negative"; hint?: string }) {
  return (
    <div className="min-w-0">
      <p className="metric-label">
        {label}
        {hint ? <CalculationHint label={label} text={hint} /> : null}
      </p>
      <p className={`financial-value mono-number mt-1 text-sm ${tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : ""}`}>{value}</p>
    </div>
  );
}
