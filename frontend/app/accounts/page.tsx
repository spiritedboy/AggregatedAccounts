"use client";

import {
  Activity,
  CheckCircle2,
  CircleAlert,
  Eye,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Timer,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ProtectedPage } from "@/components/protected-page";
import { AutoRefreshStatus, useAutoRefresh } from "@/components/auto-refresh-status";
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { ExchangeAccount, SyncStatusData } from "@/lib/types";

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
  const [error, setError] = useState("");
  const [actionId, setActionId] = useState("");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);

  const load = useCallback(() => {
    setError("");
    return Promise.all([
      apiFetch<ExchangeAccount[]>("/api/exchange-accounts"),
      apiFetch<SyncStatusData>("/api/sync/status"),
    ])
      .then(([nextAccounts, nextStatus]) => {
        setAccounts(nextAccounts);
        setSyncStatus(nextStatus);
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

  async function action(account: ExchangeAccount, type: "test" | "sync") {
    setActionId(`${account.id}-${type}`);
    setError("");
    try {
      await apiFetch(`/api/exchange-accounts/${account.id}/${type}`, {
        method: "POST",
      });
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    } finally {
      setActionId("");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="连接中心"
        title="交易所账户"
        description="账户由服务器配置文件统一管理；此页面展示连接状态并保留测试与同步。"
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

      <div className="mb-4 flex items-start gap-3 rounded-2xl border border-violet-500/20 bg-violet-500/10 px-4 py-3 text-sm text-violet-600 dark:text-violet-200">
        <Settings2 className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          新增、修改或停用账户请调整服务器配置及对应环境变量；页面仅保留连接测试和
          立即同步，不提供添加与删除操作。
        </p>
      </div>

      {syncStatus && (
        <section className="panel mb-4 overflow-hidden">
          <div className="border-b px-5 py-4" style={{ borderColor: "var(--line)" }}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-semibold">同步状态中心</p>
                <p className="muted mt-1 text-xs">
                  每个账户的最近结果、耗时、写入量和连续失败次数。
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
                  <p className="muted text-[10px] uppercase">最近错误</p>
                  <p className="mt-1 leading-5">
                    {item.consecutive_failures && item.last_error
                      ? item.last_error.message
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
            <article key={account.id} className="panel p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-mint-400/10 font-mono text-xs font-bold text-mint-400">
                    {account.exchange.slice(0, 2)}
                  </div>
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
                {["spot_trade", "futures_trade", "transfer", "withdraw"].map(
                  (permission) => (
                    <Badge
                      key={permission}
                      tone={account.permission_status[permission] ? "negative" : "neutral"}
                    >
                      {permission.replace("_", " ")}:{" "}
                      {account.permission_status[permission] ? "开启" : "关闭"}
                    </Badge>
                  ),
                )}
              </div>

              <div className="mt-5 flex gap-2">
                <button
                  type="button"
                  className="button-secondary flex-1"
                  disabled={account.is_demo || !!actionId}
                  onClick={() => action(account, "test")}
                >
                  <CheckCircle2 className="h-4 w-4" />
                  {actionId === `${account.id}-test` ? "测试中…" : "测试连接"}
                </button>
                <button
                  type="button"
                  className="button-secondary flex-1"
                  disabled={!!actionId}
                  onClick={() => action(account, "sync")}
                >
                  <RefreshCw
                    className={`h-4 w-4 ${
                      actionId === `${account.id}-sync` ? "animate-spin" : ""
                    }`}
                  />
                  立即同步
                </button>
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
    <div className="rounded-2xl bg-black/[0.025] p-4 dark:bg-white/[0.035]">
      <div className="flex items-center justify-between">
        <p className="muted text-xs">{label}</p>
        <Icon className={`h-4 w-4 ${tone === "positive" ? "text-emerald-500" : "text-amber-500"}`} />
      </div>
      <p className="mono-number mt-2 text-2xl font-semibold">{value}</p>
      <p className="muted mt-1 text-[11px]">{detail}</p>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="muted text-[10px] uppercase">{label}</p>
      <p className="mt-1 leading-5">{value}</p>
    </div>
  );
}
