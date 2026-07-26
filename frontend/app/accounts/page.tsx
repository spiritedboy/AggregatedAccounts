"use client";

import { CheckCircle2, Eye, RefreshCw, Settings2, ShieldCheck } from "lucide-react";
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
import type { ExchangeAccount } from "@/lib/types";

export default function AccountsPage() {
  return (
    <ProtectedPage>
      <AccountsContent />
    </ProtectedPage>
  );
}

function AccountsContent() {
  const [accounts, setAccounts] = useState<ExchangeAccount[] | null>(null);
  const [error, setError] = useState("");
  const [actionId, setActionId] = useState("");
  const [lastLoadedAt, setLastLoadedAt] = useState<string | null>(null);

  const load = useCallback(() => {
    setError("");
    return apiFetch<ExchangeAccount[]>("/api/exchange-accounts")
      .then((nextAccounts) => {
        setAccounts(nextAccounts);
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

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="muted text-[10px] uppercase">{label}</p>
      <p className="mt-1 leading-5">{value}</p>
    </div>
  );
}
