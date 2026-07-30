"use client";

import {
  ArrowDownToLine,
  ArrowUpFromLine,
  BadgeDollarSign,
  Download,
  Filter,
  Landmark,
  ReceiptText,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { usePrivacy } from "@/components/app-shell";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import { ProtectedPage } from "@/components/protected-page";
import { SortButton, type SortDirection } from "@/components/sort-button";
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, usd } from "@/lib/format";
import type {
  AccountingBootstrapData,
  AccountingRecordsData,
  CompletenessComponent,
  DataCompletenessData,
} from "@/lib/types";

const componentLabels = {
  equity: "账户权益",
  balances: "逐资产余额",
  positions: "当前仓位",
  closed_positions: "已平仓仓位",
  realized_pnl: "已实现收益",
  funding_fee: "资金费",
  trading_fee: "交易手续费",
  cash_flow: "资金流",
} as const;

const recordTypeLabels: Record<string, string> = {
  REALIZED_PNL: "已实现收益",
  FUNDING_FEE: "资金费",
  TRADING_FEE: "交易手续费",
  DEPOSIT: "转入 / 充值",
  WITHDRAW: "转出 / 提现",
  WITHDRAWAL: "转出 / 提现",
};

export default function LedgerPage() {
  return (
    <ProtectedPage>
      <LedgerContent />
    </ProtectedPage>
  );
}

function LedgerContent() {
  const [records, setRecords] = useState<AccountingRecordsData | null>(null);
  const [completeness, setCompleteness] =
    useState<DataCompletenessData | null>(null);
  const [error, setError] = useState("");
  const [exchange, setExchange] = useState("");
  const [recordType, setRecordType] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(1);
  const [financialImpactSort, setFinancialImpactSort] =
    useState<SortDirection>("none");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const { hidden } = usePrivacy();

  const params = useCallback(() => {
    const query = new URLSearchParams({ page: String(page), page_size: "30" });
    if (exchange) query.set("exchange", exchange);
    if (recordType) query.set("record_type", recordType);
    if (start) query.set("start_time", new Date(`${start}T00:00:00`).toISOString());
    if (end) query.set("end_time", new Date(`${end}T23:59:59`).toISOString());
    return query;
  }, [end, exchange, page, recordType, start]);

  const load = useCallback(() => {
    setError("");
    return apiFetch<AccountingBootstrapData>(
      `/api/accounting/bootstrap?${params()}`,
    )
      .then((nextData) => {
        setRecords(nextData.records);
        setCompleteness(nextData.completeness);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "账务数据加载失败"),
      );
  }, [params]);

  useEffect(() => {
    void load();
  }, [load]);
  const autoRefresh = useAutoRefresh(load);
  const sortedItems = useMemo(() => {
    const items = [...(records?.items ?? [])];
    if (financialImpactSort === "none") return items;
    return items.sort((left, right) => {
      const difference = left.signed_amount_usd - right.signed_amount_usd;
      return financialImpactSort === "asc" ? difference : -difference;
    });
  }, [financialImpactSort, records?.items]);

  function exportCsv() {
    const query = params();
    query.delete("page");
    query.delete("page_size");
    window.location.assign(`/api/accounting/records/export?${query}`);
  }

  return (
    <>
      <PageHeader
        eyebrow="每笔来往"
        title="账务流水"
        description="集中查看统计期内的已实现收益、资金费、交易手续费与资金流；所有记录均使用交易所原始 ID 幂等写入。"
        action={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <AutoRefreshStatus state={autoRefresh} lastUpdatedAt={lastLoadedAt} />
            <button type="button" className="button-secondary" onClick={exportCsv}>
              <Download className="h-4 w-4" />
              导出 CSV
            </button>
          </div>
        }
      />

      {records && (
        <section className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Metric
            icon={BadgeDollarSign}
            label="已实现收益"
            value={usd(records.summary.realized_pnl, hidden)}
            tone={records.summary.realized_pnl >= 0 ? "positive" : "negative"}
          />
          <Metric
            icon={Landmark}
            label="资金费"
            value={usd(records.summary.funding_fee, hidden)}
            tone={records.summary.funding_fee >= 0 ? "positive" : "negative"}
          />
          <Metric
            icon={ReceiptText}
            label="交易手续费"
            value={usd(records.summary.trading_fee, hidden)}
            tone="warning"
          />
          <Metric
            icon={ArrowDownToLine}
            label="净资金流"
            value={usd(records.summary.net_cash_flow, hidden)}
            tone={records.summary.net_cash_flow >= 0 ? "positive" : "negative"}
          />
        </section>
      )}

      <section className="filter-panel sm:grid-cols-2 xl:grid-cols-4">
        <Select
          label="交易所"
          value={exchange}
          onChange={(value) => {
            setPage(1);
            setExchange(value);
          }}
        >
          <option value="">全部交易所</option>
          <option value="BINANCE">Binance</option>
          <option value="OKX">OKX</option>
          <option value="BITGET">Bitget</option>
          <option value="HYPERLIQUID">Hyperliquid</option>
          <option value="POLYMARKET">Polymarket</option>
        </Select>
        <Select
          label="流水类型"
          value={recordType}
          onChange={(value) => {
            setPage(1);
            setRecordType(value);
          }}
        >
          <option value="">全部类型</option>
          <option value="REALIZED_PNL">已实现收益</option>
          <option value="FUNDING_FEE">资金费</option>
          <option value="TRADING_FEE">交易手续费</option>
          <option value="DEPOSIT">转入 / 充值</option>
          <option value="WITHDRAWAL">转出 / 提现</option>
        </Select>
        <label>
          <span className="sr-only">开始日期</span>
          <input
            className="input"
            type="date"
            value={start}
            onChange={(event) => {
              setPage(1);
              setStart(event.target.value);
            }}
          />
        </label>
        <label>
          <span className="sr-only">结束日期</span>
          <input
            className="input"
            type="date"
            value={end}
            onChange={(event) => {
              setPage(1);
              setEnd(event.target.value);
            }}
          />
        </label>
      </section>

      {records && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 px-1">
          <p className="muted text-xs">
            共 <span className="mono-number font-semibold text-[var(--text)]">{records.total}</span> 条账务记录
          </p>
          {(exchange || recordType || start || end) && (
            <button
              type="button"
              className="text-xs font-semibold text-[var(--accent)]"
              onClick={() => {
                setPage(1);
                setExchange("");
                setRecordType("");
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
      ) : !records ? (
        <LoadingState rows={7} />
      ) : records.items.length === 0 ? (
        <div className="panel">
          <EmptyState
            title="当前筛选范围没有账务流水"
            description="0 条也可能表示统计期内确实没有发生该类事件，请结合下方完整性状态判断。"
          />
        </div>
      ) : (
        <>
          <div className="table-shell hidden lg:block">
            <table className="data-table min-w-[980px]">
              <thead>
                <tr>
                  {[
                    "发生时间",
                    "账户",
                    "类型",
                    "资产 / 交易对",
                    "账务影响",
                    "来源记录",
                  ].map((title) => (
                    <th key={title} data-numeric={title === "账务影响"}>
                      {title === "账务影响" ? (
                        <span className="inline-flex items-center whitespace-nowrap">
                          {title}
                          <SortButton
                            direction={financialImpactSort}
                            label="账务影响"
                            onChange={setFinancialImpactSort}
                          />
                        </span>
                      ) : title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((record) => (
                  <tr key={`${record.record_type}-${record.id}`}>
                    <td className="whitespace-nowrap text-xs">
                      {dateTime(record.record_time)}
                    </td>
                    <td>
                      <p className="font-semibold">{record.connection_name}</p>
                      <p className="muted mt-1 text-xs">{record.exchange}</p>
                    </td>
                    <td>
                      <RecordTypeBadge recordType={record.record_type} />
                      {record.subtype !== record.record_type && (
                        <p className="muted mt-1 max-w-44 truncate text-[10px]">
                          {record.subtype}
                        </p>
                      )}
                    </td>
                    <td>
                      <p className="font-mono font-semibold">{record.asset}</p>
                      <p className="muted mt-1 text-xs">{record.symbol || "账户级"}</p>
                    </td>
                    <td
                      className={`mono-number font-semibold ${
                        record.signed_amount_usd > 0
                          ? "text-positive"
                          : record.signed_amount_usd < 0
                            ? "text-negative"
                            : ""
                      }`}
                      data-numeric="true"
                    >
                      {usd(record.signed_amount_usd, hidden)}
                    </td>
                    <td>
                      <p
                        className="muted max-w-52 truncate font-mono text-[10px]"
                        title={record.source_record_id}
                      >
                        {record.source_record_id}
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 lg:hidden">
            {sortedItems.map((record) => (
              <article key={`${record.record_type}-${record.id}`} className="panel p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <RecordTypeBadge recordType={record.record_type} />
                    <p className="muted mt-2 text-xs">{record.connection_name} · {record.exchange}</p>
                  </div>
                  <p className={`mono-number text-sm font-semibold ${record.signed_amount_usd > 0 ? "text-positive" : record.signed_amount_usd < 0 ? "text-negative" : ""}`}>
                    {usd(record.signed_amount_usd, hidden)}
                  </p>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div>
                    <p className="metric-label">资产 / 交易对</p>
                    <p className="mono-number mt-1 text-sm font-semibold">{record.asset}</p>
                    <p className="muted mt-1 text-[10px]">{record.symbol || "账户级"}</p>
                  </div>
                  <div>
                    <p className="metric-label">发生时间</p>
                    <p className="mt-1 text-xs">{dateTime(record.record_time)}</p>
                  </div>
                </div>
                <p className="muted mt-4 truncate border-t pt-3 font-mono text-[10px]" style={{ borderColor: "var(--line)" }} title={record.source_record_id}>
                  来源 {record.source_record_id}
                </p>
              </article>
            ))}
          </div>
          <div className="mt-4 flex items-center justify-between">
            <p className="muted text-xs">第 {page} 页 · 每页 30 条</p>
            <div className="flex gap-2">
              <button
                type="button"
                className="button-secondary"
                disabled={page === 1}
                onClick={() => setPage((value) => value - 1)}
              >
                上一页
              </button>
              <button
                type="button"
                className="button-secondary"
                disabled={page * 30 >= records.total}
                onClick={() => setPage((value) => value + 1)}
              >
                下一页
              </button>
            </div>
          </div>
        </>
      )}

      {completeness && <CompletenessPanel data={completeness} />}
    </>
  );
}

function CompletenessPanel({ data }: { data: DataCompletenessData }) {
  return (
    <section className="data-panel mt-6">
      <div
        className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4"
        style={{ borderColor: "var(--line)" }}
      >
        <div>
          <p className="font-semibold">数据完整性明细</p>
          <p className="muted mt-1 text-xs">
            “0 条”与“接口不支持”分开显示，避免把没有事件误判为漏数据。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone="positive">{data.summary.complete_components} 项完整</Badge>
          <Badge tone="warning">{data.summary.partial_components} 项部分完整</Badge>
          <Badge tone="neutral">{data.summary.unsupported_components} 项不支持</Badge>
        </div>
      </div>
      <div className="grid gap-4 p-4 xl:grid-cols-2">
        {data.accounts.map((account) => (
          <article
            key={account.account_id}
            className="rounded-2xl border p-4"
            style={{ borderColor: "var(--line)" }}
          >
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <p className="font-semibold">{account.connection_name}</p>
                <p className="muted mt-1 text-xs">{account.exchange}</p>
              </div>
              <Badge
                tone={account.overall_status === "COMPLETE" ? "positive" : "warning"}
              >
                {account.overall_status === "COMPLETE" ? "整体完整" : "整体部分完整"}
              </Badge>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {Object.entries(componentLabels).map(([key, label]) => (
                <ComponentStatus
                  key={key}
                  label={label}
                  component={
                    account.components[key as keyof typeof account.components]
                  }
                />
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ComponentStatus({
  label,
  component,
}: {
  label: string;
  component: CompletenessComponent;
}) {
  const tone =
    component.status === "COMPLETE"
      ? "positive"
      : component.status === "PARTIAL"
        ? "warning"
        : "neutral";
  return (
    <div className="rounded-xl bg-black/[0.025] p-3 dark:bg-white/[0.035]">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold">{label}</p>
        <Badge tone={tone}>
          {component.status === "COMPLETE"
            ? "完整"
            : component.status === "PARTIAL"
              ? "部分"
              : "不支持"}
        </Badge>
      </div>
      <p className="muted mt-2 text-[11px] leading-5">{component.reason}</p>
      <div className="muted mt-2 flex flex-wrap gap-x-3 text-[10px]">
        <span>{component.record_count} 条记录</span>
        <span>同步：{dateTime(component.last_synced_at)}</span>
      </div>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof ShieldCheck;
  label: string;
  value: string;
  tone: "positive" | "negative" | "warning";
}) {
  const colors = {
    positive: "text-positive bg-[var(--positive-soft)]",
    negative: "text-negative bg-[var(--negative-soft)]",
    warning: "text-warning bg-[var(--warning-soft)]",
  };
  return (
    <article className="panel p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="muted text-xs">{label}</p>
        <span className={`rounded-xl p-2 ${colors[tone]}`}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <p className="mono-number mt-3 text-xl font-semibold">{value}</p>
    </article>
  );
}

function RecordTypeBadge({ recordType }: { recordType: string }) {
  const Icon =
    recordType === "DEPOSIT"
      ? ArrowDownToLine
      : recordType === "WITHDRAWAL" || recordType === "WITHDRAW"
        ? ArrowUpFromLine
        : recordType === "TRADING_FEE"
          ? ReceiptText
          : BadgeDollarSign;
  const tone =
    recordType === "DEPOSIT" || recordType === "REALIZED_PNL"
      ? "positive"
      : recordType === "FUNDING_FEE"
        ? "mint"
        : recordType === "TRADING_FEE"
          ? "warning"
          : "negative";
  return (
    <Badge tone={tone}>
      <Icon className="mr-1 h-3 w-3" />
      {recordTypeLabels[recordType] || recordType}
    </Badge>
  );
}

function Select({
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
      <select
        className="input appearance-none pr-9"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
      <Filter className="muted pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2" />
    </label>
  );
}
