"use client";

import {
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  WalletCards,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { ProtectedPage } from "@/components/protected-page";
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SubmitLabel,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { ExchangeAccount } from "@/lib/types";

type Exchange = "BINANCE" | "OKX" | "BITGET" | "HYPERLIQUID" | "POLYMARKET";

const initialForm = {
  exchange: "BINANCE" as Exchange,
  connection_name: "",
  api_key: "",
  api_secret: "",
  passphrase: "",
  wallet_address: "",
};

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
  const [modal, setModal] = useState(false);
  const [form, setForm] = useState(initialForm);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [pending, setPending] = useState(false);
  const [actionId, setActionId] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<ExchangeAccount | null>(null);

  const load = useCallback(() => {
    setError("");
    apiFetch<ExchangeAccount[]>("/api/exchange-accounts")
      .then(setAccounts)
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(load, [load]);

  function closeModal() {
    setModal(false);
    setForm(initialForm);
    setVisible({});
    setError("");
  }

  async function addAccount(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    const payload =
      form.exchange === "HYPERLIQUID" || form.exchange === "POLYMARKET"
        ? {
            exchange: form.exchange,
            connection_name: form.connection_name,
            wallet_address: form.wallet_address,
          }
        : {
            exchange: form.exchange,
            connection_name: form.connection_name,
            api_key: form.api_key,
            api_secret: form.api_secret,
            passphrase:
              form.exchange === "OKX" || form.exchange === "BITGET"
                ? form.passphrase
                : undefined,
          };
    try {
      await apiFetch("/api/exchange-accounts", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      closeModal();
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "添加失败");
    } finally {
      setPending(false);
    }
  }

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

  async function remove() {
    if (!confirmDelete) return;
    setActionId(`${confirmDelete.id}-delete`);
    try {
      await apiFetch(`/api/exchange-accounts/${confirmDelete.id}`, {
        method: "DELETE",
      });
      setConfirmDelete(null);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除失败");
    } finally {
      setActionId("");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="连接中心"
        title="交易所账户"
        description="添加纯只读凭证、检查权限和管理同步。所有密钥字段均由后端认证加密保存。"
        action={
          <button type="button" className="button-primary" onClick={() => setModal(true)}>
            <Plus className="h-4 w-4" />
            添加账户
          </button>
        }
      />

      {error && !modal && (
        <div className="mb-4 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-500">
          {error}
        </div>
      )}

      {!accounts ? (
        error ? <ErrorState message={error} retry={load} /> : <LoadingState rows={5} />
      ) : accounts.length === 0 ? (
        <div className="panel"><EmptyState title="还没有交易所账户" description="添加第一个纯只读 API Key 或公开账户地址。" /></div>
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
                    <p className="muted mt-1 font-mono text-xs">{account.masked_identifier}</p>
                  </div>
                </div>
                <Badge tone={account.connection_status === "CONNECTED" ? "positive" : "warning"}>
                  {account.connection_status === "CONNECTED" ? "已连接" : account.connection_status}
                </Badge>
              </div>

              <div className="mt-5 grid grid-cols-2 gap-4 border-y py-4 text-xs sm:grid-cols-3" style={{ borderColor: "var(--line)" }}>
                <Info label="统计开始" value={dateTime(account.tracking_started_at)} />
                <Info label="最后同步" value={dateTime(account.last_synced_at)} />
                <Info label="数据完整性" value={account.data_completeness === "COMPLETE" ? "完整" : "统计不完整"} />
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <Badge tone={account.permission_status.read ? "positive" : "warning"}>
                  <ShieldCheck className="mr-1 h-3 w-3" />只读
                </Badge>
                {["spot_trade", "futures_trade", "transfer", "withdraw"].map((permission) => (
                  <Badge key={permission} tone={account.permission_status[permission] ? "negative" : "neutral"}>
                    {permission.replace("_", " ")}: {account.permission_status[permission] ? "开启" : "关闭"}
                  </Badge>
                ))}
              </div>

              <div className="mt-5 flex flex-wrap gap-2">
                <button type="button" className="button-secondary flex-1" disabled={account.is_demo || !!actionId} onClick={() => action(account, "test")}>
                  <CheckCircle2 className="h-4 w-4" />
                  {actionId === `${account.id}-test` ? "测试中…" : "测试连接"}
                </button>
                <button type="button" className="button-secondary flex-1" disabled={!!actionId} onClick={() => action(account, "sync")}>
                  <RefreshCw className={`h-4 w-4 ${actionId === `${account.id}-sync` ? "animate-spin" : ""}`} />
                  立即同步
                </button>
                <button type="button" className="button-secondary h-11 w-11 p-0 text-rose-500" disabled={account.is_demo || !!actionId} onClick={() => setConfirmDelete(account)} aria-label={`删除 ${account.connection_name}`}>
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </article>
          ))}
        </section>
      )}

      {modal && (
        <Modal title="添加交易所账户" close={closeModal}>
          <form onSubmit={addAccount} autoComplete="off">
            <div className="grid grid-cols-2 gap-2">
              {(["BINANCE", "OKX", "BITGET", "HYPERLIQUID", "POLYMARKET"] as Exchange[]).map((exchange) => (
                <button
                  key={exchange}
                  type="button"
                  onClick={() => setForm({ ...initialForm, exchange })}
                  className={`min-h-11 rounded-xl border px-3 text-xs font-semibold ${form.exchange === exchange ? "border-mint-400 bg-mint-400/10 text-mint-400" : "muted"}`}
                  style={form.exchange !== exchange ? { borderColor: "var(--line)" } : undefined}
                >
                  {exchange}
                </button>
              ))}
            </div>
            <div className="mt-5 space-y-4">
              <Field label="连接名称">
                <input className="input" value={form.connection_name} onChange={(event) => setForm((value) => ({ ...value, connection_name: event.target.value }))} maxLength={80} required placeholder="例如：主账户只读" autoComplete="off" />
              </Field>
              {form.exchange === "HYPERLIQUID" || form.exchange === "POLYMARKET" ? (
                <>
                  <Field label={form.exchange === "POLYMARKET" ? "Polymarket 钱包或 Profile Address" : "公开钱包地址"}>
                    <input className="input font-mono" value={form.wallet_address} onChange={(event) => setForm((value) => ({ ...value, wallet_address: event.target.value }))} required pattern="0x[a-fA-F0-9]{40}" placeholder="0x…" autoComplete="off" />
                  </Field>
                  <div className="rounded-xl bg-mint-400/10 p-3 text-xs leading-5 text-mint-500 dark:text-mint-300">
                    {form.exchange === "POLYMARKET"
                      ? "可填写 Polymarket 登录钱包或公开 Profile / Proxy Wallet 地址，系统会自动解析 Profile 地址。请勿输入私钥、助记词或任何密码。"
                      : "Hyperliquid 只需要公开地址。请勿输入钱包私钥、助记词或任何密码。"}
                  </div>
                </>
              ) : (
                <>
                  <SecretField label="API Key" field="api_key" value={form.api_key} visible={!!visible.api_key} toggle={() => setVisible((state) => ({ ...state, api_key: !state.api_key }))} change={(value) => setForm((state) => ({ ...state, api_key: value }))} />
                  <SecretField label="API Secret" field="api_secret" value={form.api_secret} visible={!!visible.api_secret} toggle={() => setVisible((state) => ({ ...state, api_secret: !state.api_secret }))} change={(value) => setForm((state) => ({ ...state, api_secret: value }))} />
                  {(form.exchange === "OKX" || form.exchange === "BITGET") && (
                    <SecretField label="Passphrase" field="passphrase" value={form.passphrase} visible={!!visible.passphrase} toggle={() => setVisible((state) => ({ ...state, passphrase: !state.passphrase }))} change={(value) => setForm((state) => ({ ...state, passphrase: value }))} />
                  )}
                  <div className="rounded-xl bg-amber-500/10 p-3 text-xs leading-5 text-amber-600 dark:text-amber-300">
                    仅接受纯只读 API Key。检测到交易、划转或提币权限时将拒绝保存。
                  </div>
                </>
              )}
              {error && <p className="rounded-xl border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-500">{error}</p>}
              <button type="submit" className="button-primary w-full" disabled={pending}>
                <SubmitLabel pending={pending}>{pending ? "正在测试并加密…" : "测试连接并保存"}</SubmitLabel>
              </button>
            </div>
          </form>
        </Modal>
      )}

      {confirmDelete && (
        <Modal title="确认删除连接" close={() => setConfirmDelete(null)}>
          <div className="text-center">
            <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-rose-500/10 text-rose-500"><Trash2 className="h-5 w-5" /></div>
            <p className="mt-4 font-semibold">删除 {confirmDelete.connection_name}？</p>
            <p className="muted mt-2 text-sm leading-6">凭证密文、Nonce 与认证标签将立即删除，同步任务停止；非敏感历史统计将保留。</p>
            <div className="mt-6 grid grid-cols-2 gap-3">
              <button type="button" className="button-secondary" onClick={() => setConfirmDelete(null)}>取消</button>
              <button type="button" className="button-primary !bg-rose-500 !text-white" onClick={remove} disabled={!!actionId}>{actionId ? "删除中…" : "确认删除"}</button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><p className="muted text-[10px] uppercase">{label}</p><p className="mt-1 leading-5">{value}</p></div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="mb-2 block text-sm font-medium">{label}</span>{children}</label>;
}

function SecretField({ label, field, value, visible, toggle, change }: { label: string; field: string; value: string; visible: boolean; toggle: () => void; change: (value: string) => void }) {
  return (
    <Field label={label}>
      <span className="relative block">
        <KeyRound className="muted absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2" />
        <input className="input px-10 font-mono" name={field} type={visible ? "text" : "password"} value={value} onChange={(event) => change(event.target.value)} required minLength={8} maxLength={256} autoComplete="new-password" spellCheck={false} />
        <button type="button" onClick={toggle} className="muted absolute right-3 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center" aria-label={visible ? `隐藏${label}` : `显示${label}`}>
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </span>
    </Field>
  );
}

function Modal({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/65 p-0 backdrop-blur-sm sm:items-center sm:p-5" onMouseDown={close}>
      <section className="panel-solid max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-b-none p-5 sm:rounded-2xl sm:p-6" onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-mint-400/10 text-mint-400"><WalletCards className="h-4 w-4" /></div>
            <h2 className="font-semibold">{title}</h2>
          </div>
          <button type="button" className="button-secondary h-10 min-h-10 w-10 p-0" onClick={close} aria-label="关闭"><X className="h-4 w-4" /></button>
        </div>
        {children}
      </section>
    </div>
  );
}
