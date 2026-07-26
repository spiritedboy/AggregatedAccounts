"use client";

import { ArrowRight, LockKeyhole, Orbit, ShieldCheck } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    fetch("/api/auth/status", { credentials: "same-origin", cache: "no-store" }).then(
      (response) => {
        if (response.ok) window.location.assign("/dashboard");
      },
    );
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      await apiFetch("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setPassword("");
      window.location.assign("/dashboard");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="relative grid min-h-screen overflow-hidden lg:grid-cols-[1.15fr_.85fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden p-12 lg:flex xl:p-16">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(51,214,173,.18),transparent_38%),linear-gradient(145deg,#07100f_0%,#102622_100%)]" />
        <div className="absolute -bottom-32 -right-24 h-[34rem] w-[34rem] rounded-full border border-mint-400/15" />
        <div className="absolute -bottom-20 -right-4 h-[25rem] w-[25rem] rounded-full border border-mint-400/10" />
        <div className="relative flex items-center gap-3 text-white">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-mint-400 text-ink-950">
            <Orbit className="h-6 w-6" />
          </div>
          <div>
            <p className="font-bold tracking-[0.08em]">ATLAS LEDGER</p>
            <p className="text-[10px] uppercase tracking-[0.2em] text-white/45">
              Portfolio Intelligence
            </p>
          </div>
        </div>
        <div className="relative max-w-2xl text-white">
          <p className="eyebrow">Unified capital view</p>
          <h1 className="mt-5 text-5xl font-semibold leading-[1.08] tracking-[-0.04em] xl:text-6xl">
            看清每一笔资本，
            <br />
            不触碰任何交易。
          </h1>
          <p className="mt-7 max-w-xl text-base leading-8 text-white/58">
            将 Binance、OKX、Bitget 与 Hyperliquid 的账户权益、仓位和收益整合进一张只读视图。
          </p>
        </div>
        <div className="relative flex items-center gap-6 text-xs text-white/45">
          <span>AES-256-GCM</span>
          <span className="h-1 w-1 rounded-full bg-mint-400" />
          <span>HTTPONLY SESSION</span>
          <span className="h-1 w-1 rounded-full bg-mint-400" />
          <span>READ ONLY</span>
        </div>
      </section>

      <section className="flex items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-md">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-mint-400 text-ink-950">
              <Orbit className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-bold">ATLAS LEDGER</p>
              <p className="muted text-[10px] uppercase tracking-[0.15em]">Portfolio Intelligence</p>
            </div>
          </div>
          <p className="eyebrow">Private workspace</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight">欢迎回来</h2>
          <p className="muted mt-3 text-sm leading-6">
            输入此平台的访问密码。凭证只会发送至后端验证，不会保存在浏览器中。
          </p>

          <form className="mt-8 space-y-5" onSubmit={submit}>
            <label className="block">
              <span className="mb-2 block text-sm font-medium">访问密码</span>
              <span className="relative block">
                <LockKeyhole className="muted absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2" />
                <input
                  className="input pl-10"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  autoFocus
                  required
                  placeholder="输入访问密码"
                  aria-describedby={error ? "login-error" : undefined}
                />
              </span>
            </label>
            {error && (
              <p
                id="login-error"
                className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-500"
              >
                {error}
              </p>
            )}
            <button type="submit" className="button-primary w-full" disabled={pending}>
              {pending ? "正在验证…" : "安全进入"}
              {!pending && <ArrowRight className="h-4 w-4" />}
            </button>
          </form>

          <div className="mt-8 flex items-start gap-3 rounded-2xl border p-4" style={{ borderColor: "var(--line)" }}>
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-mint-400" />
            <p className="muted text-xs leading-5">
              登录会话使用 HttpOnly、SameSite=Lax Cookie；连续失败会触发限频保护。
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
