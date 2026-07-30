"use client";

import {
  Activity,
  ChevronDown,
  CircleAlert,
  Eye,
  Settings2,
  ShieldCheck,
  Timer,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ProtectedPage } from "@/components/protected-page";
import { usePrivacy } from "@/components/app-shell";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import {
  Badge,
  EmptyState,
  ErrorState,
  ExchangeMark,
  LoadingState,
  PageHeader,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, number, usd } from "@/lib/format";
import type {
  AccountBalance,
  AccountsBootstrapData,
  ExchangeAccount,
  SyncStatusData,
} from "@/lib/types";

export default function AccountsPage() {
  return (
    <ProtectedPage>
      <AccountsContent />
    </ProtectedPage>
  );
}

function AccountsContent() {
  const [accounts, setAccounts] = useState<ExchangeAccount[] | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatusData | null>(null);
  const [balances, setBalances] = useState<AccountBalance[]>([]);
  const [error, setError] = useState("");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);
  const { hidden } = usePrivacy();

  const load = useCallback(() => {
    setError("");
    return apiFetch<AccountsBootstrapData>("/api/accounts/bootstrap")
      .then((nextData) => {
        setAccounts(nextData.accounts);
        setSyncStatus(nextData.sync_status);
        setBalances(nextData.balances);
        setLastLoadedAt(new Date().toISOString());
      })
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  const autoRefresh = useAutoRefresh(load);
  const lastUpdatedAt =
    accounts?.reduce<string | null>(
      (latest, account) =>
        account.last_synced_at &&
        (!latest || Date.parse(account.last_synced_at) > Date.parse(latest))
          ? account.last_synced_at
          : latest,
      null,
    ) ?? lastLoadedAt;

  return (
    <>
      <PageHeader
        eyebrow="伙伴连接"
        title="交易所账户"
        description="账户由服务器配置文件统一管理；此页面仅展示连接与同步状态。"
        action={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Badge tone="mint">
              <Eye className="mr-1 h-3 w-3" />
              公开只读
            </Badge>
            <AutoRefreshStatus state={autoRefresh} lastUpdatedAt={lastUpdatedAt} />
          </div>
        }
      />

      <details className="group mb-4 rounded-xl border bg-[var(--surface)]" style={{ borderColor: "var(--line)" }}>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm">
          <span className="flex items-center gap-2 font-medium">
            <Settings2 className="h-4 w-4 text-[var(--accent)]" />
            关于账户管理
          </span>
          <ChevronDown className="h-4 w-4 transition group-open:rotate-180" />
        </summary>
        <p className="muted border-t px-4 py-3 text-xs leading-5" style={{ borderColor: "var(--line)" }}>
          账户由服务器配置文件统一管理。公网页面不提供连接测试、手动同步、添加或删除操作，后台定时同步不受影响。
        </p>
      </details>

      {syncStatus && (
        <section className="data-panel mb-4">
          <div className="border-b px-5 py-4" style={{ borderColor: "var(--line)" }}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="section-label">平台同步概况</p>
                <p className="muted mt-1 text-xs">
                  汇总每个账户的数据新鲜度和最近一次同步结果。
                </p>
              </div>
              <Badge tone={syncStatus.summary.failing_accounts ? "warning" : "positive"}>
                <Activity className="mr-1 h-3 w-3" />
                {syncStatus.summary.healthy_accounts}/{syncStatus.summary.total_accounts} 正常
              </Badge>
            </div>
          </div>
          <div className="grid gap-3 border-b p-4 sm:grid-cols-3" style={{ borderColor: "var(--line)" }}>
            <SyncMetric
              label="健康账户"
              value={`${syncStatus.summary.healthy_accounts}`}
              detail={`共 ${syncStatus.summary.total_accounts} 个`}
              tone="positive"
            />
            <SyncMetric
              label="数据过期"
              value={`${syncStatus.summary.stale_accounts}`}
              detail="超过两个同步周期"
              tone={syncStatus.summary.stale_accounts ? "warning" : "positive"}
            />
            <SyncMetric
              label="连续失败"
              value={`${syncStatus.summary.failing_accounts}`}
              detail="不包含通知推送"
              tone={syncStatus.summary.failing_accounts ? "warning" : "positive"}
            />
          </div>
          <div className="divide-y" style={{ borderColor: "var(--line)" }}>
            {syncStatus.accounts.map((item) => (
              <div
                key={item.account_id}
                className="grid gap-3 px-5 py-4 md:grid-cols-[1.2fr_.8fr_.8fr_1.4fr] md:items-center"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold">{item.connection_name}</p>
                    <Badge
                      tone={
                        item.consecutive_failures
                          ? "negative"
                          : item.is_stale
                            ? "warning"
                            : "positive"
                      }
                    >
                      {item.consecutive_failures
                        ? `连续失败 ${item.consecutive_failures} 次`
                        : item.is_stale
                          ? "数据过期"
                          : "同步正常"}
                    </Badge>
                  </div>
                  <p className="muted mt-1 text-xs">{item.exchange}</p>
                </div>
                <Info
                  label="最后成功"
                  value={dateTime(item.last_success_at ?? item.last_synced_at)}
                />
                <Info
                  label="最近任务"
                  value={
                    item.latest_job
                      ? `${item.latest_job.duration_ms ?? 0} ms · ${item.latest_job.records_written} 条`
                      : "暂无任务"
                  }
                />
                <div className="text-xs">
                  <p className="metric-label">同步说明</p>
                  <p className="mt-1 leading-5">
                    {item.consecutive_failures
                      ? "同步暂时异常，系统将在下一周期继续重试"
                      : "无未恢复错误"}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {error ? (
        <ErrorState message={error} retry={load} />
      ) : !accounts ? (
        <LoadingState rows={5} />
      ) : accounts.length === 0 ? (
        <div className="panel">
          <EmptyState
            title="还没有启用的交易所账户"
            description="请在账户配置文件中启用至少一个平台，并在服务器环境变量中提供对应凭证。"
          />
        </div>
      ) : (
        <section className="grid gap-4 xl:grid-cols-2">
          {accounts.map((account) => (
            <article key={account.id} className="panel p-5 md:p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 items-center gap-3">
                  <ExchangeMark exchange={account.exchange} size="lg" />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="truncate font-semibold">{account.connection_name}</h2>
                      {account.is_demo && <Badge tone="mint">演示</Badge>}
                    </div>
                    <p className="muted mt-1 font-mono text-xs">
                      {account.masked_identifier}
                    </p>
                  </div>
                </div>
                <Badge
                  tone={account.connection_status === "CONNECTED" ? "positive" : "warning"}
                >
                  {account.connection_status === "CONNECTED"
                    ? "已连接"
                    : account.connection_status}
                </Badge>
              </div>

              <div
                className="mt-5 grid grid-cols-2 gap-4 border-y py-4 text-xs sm:grid-cols-3"
                style={{ borderColor: "var(--line)" }}
              >
                <Info label="统计开始" value={dateTime(account.tracking_started_at)} />
                <Info label="最后同步" value={dateTime(account.last_synced_at)} />
                <Info
                  label="数据完整性"
                  value={account.data_completeness === "COMPLETE" ? "完整" : "统计不完整"}
                />
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <Badge tone={account.permission_status.read ? "positive" : "warning"}>
                  <ShieldCheck className="mr-1 h-3 w-3" />
                  只读
                </Badge>
                {[
                  ["spot_trade", "现货交易"],
                  ["futures_trade", "合约交易"],
                  ["transfer", "资金划转"],
                  ["withdraw", "资产提取"],
                ].map(([permission, label]) => (
                    <Badge
                      key={permission}
                      tone={account.permission_status[permission] ? "negative" : "neutral"}
                    >
                      {label}:{" "}
                      {account.permission_status[permission] ? "开启" : "关闭"}
                    </Badge>
                  ),
                )}
              </div>

              <div className="mt-5 border-t pt-4" style={{ borderColor: "var(--line)" }}>
                <p className="metric-label">逐资产余额</p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {(balances.find((item) => item.account_id === account.id)?.assets ?? []).map((asset) => (
                    <div key={`${asset.account_type}:${asset.asset}`} className="soft-block px-3 py-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-mono text-xs font-semibold">{asset.asset}</p>
                        <Badge tone={asset.value_usd === null ? "warning" : "neutral"}>{asset.account_type}</Badge>
                      </div>
                      <p className="mono-number mt-2 text-sm">
                        {asset.value_usd === null ? "无法估值" : usd(asset.value_usd, hidden)}
                      </p>
                      <p className="muted mono-number mt-1 text-[10px]">
                        可用 {number(asset.available)} · 锁定 {number(asset.locked)}
                      </p>
                    </div>
                  ))}
                  {(balances.find((item) => item.account_id === account.id)?.assets.length ?? 0) === 0 && (
                    <p className="muted text-xs">等待下一次同步写入资产明细。</p>
                  )}
                </div>
              </div>
            </article>
          ))}
        </section>
      )}
    </>
  );
}

function SyncMetric({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "positive" | "warning";
}) {
  const Icon = tone === "positive" ? Timer : CircleAlert;
  return (
    <div className="soft-block p-4">
      <div className="flex items-center justify-between">
        <p className="muted text-xs">{label}</p>
        <Icon className={`h-4 w-4 ${tone === "positive" ? "text-positive" : "text-warning"}`} />
      </div>
      <p className="mono-number mt-2 text-2xl font-semibold">{value}</p>
      <p className="muted mt-1 text-[11px]">{detail}</p>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="metric-label">{label}</p>
      <p className="mt-1 leading-5">{value}</p>
    </div>
  );
}
