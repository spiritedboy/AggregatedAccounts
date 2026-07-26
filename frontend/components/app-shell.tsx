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
  Sparkles,
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

const THEME_STORAGE_KEY = "atlas-theme";

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
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    const nextDark = saved
      ? saved === "dark"
      : document.documentElement.classList.contains("dark");
    setDark(nextDark);
    document.documentElement.classList.toggle("dark", nextDark);
    document.documentElement.dataset.theme = nextDark ? "dark" : "light";
  }, []);

  function toggleTheme() {
    setDark((current) => {
      const next = !current;
      window.localStorage.setItem(THEME_STORAGE_KEY, next ? "dark" : "light");
      document.documentElement.classList.toggle("dark", next);
      document.documentElement.dataset.theme = next ? "dark" : "light";
      return next;
    });
  }

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
        <aside className="sticky top-0 hidden h-screen border-r p-4 md:flex md:flex-col" style={{ borderColor: "var(--line)", background: "linear-gradient(180deg, var(--accent-soft), transparent 38%)" }}>
          <Brand />
          <nav className="mt-8 space-y-1.5" aria-label="主导航">
            {nav.map((item) => (
              <NavItem key={item.href} {...item} active={pathname === item.href} />
            ))}
          </nav>
          <div className="panel mt-auto relative overflow-hidden p-4">
            <div className="absolute -right-8 -top-8 h-24 w-24 rounded-full bg-violet-500/15 blur-xl" />
            <p className="eyebrow"><Sparkles className="mr-1 h-3 w-3" /> Read only</p>
            <p className="mt-3 text-sm font-semibold">安心看资产，不碰交易</p>
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
              <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_14px_rgba(52,211,153,.9)]" />
              <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 font-medium text-emerald-600 dark:text-emerald-300">聚合服务在线</span>
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
                onClick={toggleTheme}
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
                className={`flex min-h-12 flex-col items-center justify-center gap-1 rounded-xl text-[10px] transition ${active ? "nav-active" : "muted"}`}
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
      <div className="brand-bubble relative grid h-10 w-10 place-items-center rounded-2xl text-white">
        <Orbit className="h-5 w-5" />
        <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full border-2 border-[var(--bg)] bg-cyan-300" />
      </div>
      <div>
        <p className="text-sm font-bold tracking-wide">ATLAS LEDGER</p>
        <p className="muted text-[10px] tracking-[0.08em]">让每笔资产更清楚</p>
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
        active ? "nav-active" : "muted hover:bg-violet-500/10 hover:text-violet-500 dark:hover:text-violet-300"
      }`}
    >
      <Icon className="h-[18px] w-[18px]" />
      {label}
    </Link>
  );
}
