"use client";

import {
  BarChart3,
  Eye,
  EyeOff,
  History,
  LayoutDashboard,
  LogOut,
  Moon,
  Orbit,
  PanelLeft,
  Sun,
  WalletCards,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { apiFetch } from "@/lib/api";

const nav = [
  { href: "/dashboard", label: "总览", icon: LayoutDashboard },
  { href: "/positions", label: "当前仓位", icon: Orbit },
  { href: "/history", label: "历史仓位", icon: History },
  { href: "/pnl", label: "收益分析", icon: BarChart3 },
  { href: "/accounts", label: "交易所账户", icon: WalletCards },
];

type PrivacyContextValue = {
  hidden: boolean;
  toggle: () => void;
};

const PrivacyContext = createContext<PrivacyContextValue>({
  hidden: false,
  toggle: () => undefined,
});

export function usePrivacy() {
  return useContext(PrivacyContext);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [dark, setDark] = useState(true);
  const [hidden, setHidden] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    apiFetch<{ authenticated: boolean }>("/api/auth/status")
      .then(() => setReady(true))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  async function logout() {
    await apiFetch("/api/auth/logout", { method: "POST" });
    window.location.assign("/login");
  }

  const privacy = useMemo(
    () => ({ hidden, toggle: () => setHidden((value) => !value) }),
    [hidden],
  );

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex items-center gap-3 text-sm muted">
          <Orbit className="h-5 w-5 animate-spin text-mint-400" />
          正在验证安全会话…
        </div>
      </div>
    );
  }

  return (
    <PrivacyContext.Provider value={privacy}>
      <div className="min-h-screen md:grid md:grid-cols-[248px_1fr]">
        <aside className="sticky top-0 hidden h-screen border-r p-4 md:flex md:flex-col" style={{ borderColor: "var(--line)" }}>
          <Brand />
          <nav className="mt-8 space-y-1.5" aria-label="主导航">
            {nav.map((item) => (
              <NavItem key={item.href} {...item} active={pathname === item.href} />
            ))}
          </nav>
          <div className="mt-auto rounded-2xl border p-4" style={{ borderColor: "var(--line)" }}>
            <p className="eyebrow">Read only</p>
            <p className="mt-2 text-sm font-semibold">零交易权限架构</p>
            <p className="muted mt-1 text-xs leading-5">
              平台仅查询账户数据，不包含任何交易、划转或提币能力。
            </p>
          </div>
        </aside>

        <div className="min-w-0">
          <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b px-4 backdrop-blur-xl md:px-8" style={{ background: "color-mix(in srgb, var(--bg) 84%, transparent)", borderColor: "var(--line)" }}>
            <button
              type="button"
              className="button-secondary h-10 min-h-10 w-10 p-0 md:hidden"
              aria-label="打开菜单"
              onClick={() => setDrawer(true)}
            >
              <PanelLeft className="h-4 w-4" />
            </button>
            <div className="hidden items-center gap-2 text-xs md:flex">
              <span className="h-2 w-2 rounded-full bg-mint-400 shadow-[0_0_14px_rgba(51,214,173,.8)]" />
              <span className="muted">聚合服务在线</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="button-secondary h-10 min-h-10 w-10 p-0"
                aria-label={hidden ? "显示金额" : "隐藏金额"}
                onClick={() => setHidden((value) => !value)}
              >
                {hidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
              <button
                type="button"
                className="button-secondary h-10 min-h-10 w-10 p-0"
                aria-label="切换主题"
                onClick={() => setDark((value) => !value)}
              >
                {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
              <button
                type="button"
                className="button-secondary h-10 min-h-10 w-10 p-0"
                aria-label="退出登录"
                onClick={logout}
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </header>

          <main className="mx-auto w-full max-w-[1600px] px-4 pb-28 pt-6 md:px-8 md:pb-10 md:pt-8">
            {children}
          </main>
        </div>

        <nav className="fixed inset-x-3 bottom-3 z-40 grid grid-cols-5 rounded-2xl border p-1.5 shadow-panel backdrop-blur-xl md:hidden" style={{ background: "var(--surface)", borderColor: "var(--line)" }} aria-label="移动端导航">
          {nav.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex min-h-12 flex-col items-center justify-center gap-1 rounded-xl text-[10px] ${active ? "bg-mint-400/15 text-mint-400" : "muted"}`}
              >
                <Icon className="h-4 w-4" />
                <span>{item.label.replace("交易所", "")}</span>
              </Link>
            );
          })}
        </nav>

        {drawer && (
          <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm md:hidden" onClick={() => setDrawer(false)}>
            <aside className="h-full w-[82%] max-w-xs border-r p-4" style={{ background: "var(--surface-solid)", borderColor: "var(--line)" }} onClick={(event) => event.stopPropagation()}>
              <div className="flex items-center justify-between">
                <Brand />
                <button type="button" className="button-secondary h-10 min-h-10 w-10 p-0" onClick={() => setDrawer(false)} aria-label="关闭菜单">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <nav className="mt-8 space-y-1.5">
                {nav.map((item) => (
                  <NavItem
                    key={item.href}
                    {...item}
                    active={pathname === item.href}
                    onClick={() => setDrawer(false)}
                  />
                ))}
              </nav>
            </aside>
          </div>
        )}
      </div>
    </PrivacyContext.Provider>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="grid h-10 w-10 place-items-center rounded-xl bg-mint-400 text-ink-950 shadow-[0_10px_30px_-10px_rgba(51,214,173,.9)]">
        <Orbit className="h-5 w-5" />
      </div>
      <div>
        <p className="text-sm font-bold tracking-wide">ATLAS LEDGER</p>
        <p className="muted text-[10px] uppercase tracking-[0.16em]">Portfolio Intelligence</p>
      </div>
    </div>
  );
}

function NavItem({
  href,
  label,
  icon: Icon,
  active,
  onClick,
}: (typeof nav)[number] & { active: boolean; onClick?: () => void }) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={`flex min-h-11 items-center gap-3 rounded-xl px-3.5 text-sm font-medium transition ${
        active ? "bg-mint-400/15 text-mint-500 dark:text-mint-300" : "muted hover:bg-black/5 dark:hover:bg-white/5"
      }`}
    >
      <Icon className="h-[18px] w-[18px]" />
      {label}
    </Link>
  );
}
