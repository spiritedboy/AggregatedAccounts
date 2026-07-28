"use client";

import {
  BarChart3,
  Compass,
  Eye,
  EyeOff,
  History,
  LayoutDashboard,
  Menu,
  Moon,
  Orbit,
  ReceiptText,
  Scale,
  Sun,
  type LucideIcon,
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

const THEME_STORAGE_KEY = "atlas-theme";

type NavItemData = {
  href: string;
  label: string;
  shortLabel: string;
  icon: LucideIcon;
};

const navGroups: Array<{ label: string; items: NavItemData[] }> = [
  {
    label: "资产",
    items: [
      { href: "/dashboard", label: "资产总览", shortLabel: "总览", icon: LayoutDashboard },
      { href: "/positions", label: "当前仓位", shortLabel: "仓位", icon: Orbit },
      { href: "/history", label: "历史仓位", shortLabel: "历史", icon: History },
    ],
  },
  {
    label: "分析",
    items: [
      { href: "/pnl", label: "收益分析", shortLabel: "收益", icon: BarChart3 },
      { href: "/reconciliation", label: "风险与对账", shortLabel: "风险", icon: Scale },
    ],
  },
  {
    label: "数据",
    items: [
      { href: "/ledger", label: "账务流水", shortLabel: "流水", icon: ReceiptText },
      { href: "/accounts", label: "交易所账户", shortLabel: "账户", icon: WalletCards },
    ],
  },
];

const allNavItems = navGroups.flatMap((group) => group.items);
const mobileNavItems = allNavItems.filter((item) =>
  ["/dashboard", "/positions", "/pnl", "/ledger"].includes(item.href),
);

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

  const privacy = useMemo(
    () => ({ hidden, toggle: () => setHidden((value) => !value) }),
    [hidden],
  );

  const activePage = allNavItems.find((item) => pathname === item.href);
  const moreActive = ["/history", "/reconciliation", "/accounts"].includes(pathname);

  return (
    <PrivacyContext.Provider value={privacy}>
      <div className="min-h-screen lg:grid lg:grid-cols-[224px_1fr]">
        <aside
          className="sticky top-0 hidden h-screen border-r px-4 py-5 lg:flex lg:flex-col"
          style={{
            borderColor: "var(--line)",
            background:
              "linear-gradient(180deg, color-mix(in srgb, var(--accent-soft) 72%, var(--surface)) 0%, var(--surface) 34%, color-mix(in srgb, var(--aqua-soft) 45%, var(--surface)) 100%)",
          }}
        >
          <Brand />

          <nav className="mt-8 space-y-6" aria-label="主导航">
            {navGroups.map((group) => (
              <div key={group.label}>
                <p className="muted mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em]">
                  {group.label}
                </p>
                <div className="space-y-1">
                  {group.items.map((item) => (
                    <NavItem key={item.href} item={item} active={pathname === item.href} />
                  ))}
                </div>
              </div>
            ))}
          </nav>

          <div
            className="mt-auto overflow-hidden rounded-[20px] border p-4"
            style={{
              borderColor: "var(--line)",
              background:
                "linear-gradient(135deg, var(--accent-soft), var(--aqua-soft) 62%, var(--warning-soft))",
            }}
          >
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
              </span>
              <p className="text-xs font-semibold">资产拼图在线</p>
            </div>
            <p className="muted mt-2 text-[11px] leading-5">
              只读取公开资产视图，不提供交易、划转或提币功能。
            </p>
          </div>
        </aside>

        <div className="min-w-0">
          <header
            className="sticky top-0 z-30 flex h-16 items-center justify-between border-b px-4 lg:px-7"
            style={{
              background: "color-mix(in srgb, var(--surface) 86%, transparent)",
              borderColor: "var(--line)",
              backdropFilter: "blur(18px)",
            }}
          >
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                className="button-secondary h-10 min-h-10 w-10 p-0 lg:hidden"
                aria-label="打开菜单"
                onClick={() => setDrawer(true)}
              >
                <Menu className="h-[18px] w-[18px]" />
              </button>
              <div className="lg:hidden">
                <Brand compact />
              </div>
              <div className="hidden items-center gap-2 lg:flex">
                <Compass className="h-4 w-4 text-[var(--accent)]" />
                <span className="muted text-xs">ATLAS /</span>
                <span className="text-xs font-semibold">{activePage?.label ?? "资产观测"}</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div className="mr-1 hidden items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] sm:flex" style={{ borderColor: "var(--line)", background: "var(--surface-soft)" }}>
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                <span className="muted">五个平台 · 60 秒更新</span>
              </div>
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
            </div>
          </header>

          <main className="mx-auto w-full max-w-[1540px] px-4 pb-28 pt-5 md:px-6 md:pb-10 md:pt-7 xl:px-8">
            {children}
          </main>
        </div>

        <nav
          className="fixed inset-x-3 bottom-3 z-40 grid grid-cols-5 rounded-[22px] border p-1.5 lg:hidden"
          style={{
            background: "color-mix(in srgb, var(--surface) 94%, transparent)",
            borderColor: "var(--line)",
            boxShadow: "var(--panel-shadow-hover)",
            backdropFilter: "blur(18px)",
          }}
          aria-label="移动端导航"
        >
          {mobileNavItems.map((item) => (
            <MobileNavItem key={item.href} item={item} active={pathname === item.href} />
          ))}
          <button
            type="button"
            className={`flex min-h-12 flex-col items-center justify-center gap-1 rounded-xl text-[10px] font-medium transition ${moreActive ? "nav-active" : "muted"}`}
            onClick={() => setDrawer(true)}
            aria-label="更多页面"
          >
            <Menu className="h-[18px] w-[18px]" />
            <span>更多</span>
          </button>
        </nav>

        {drawer && (
          <div
            className="fixed inset-0 z-50 bg-slate-950/55 backdrop-blur-sm lg:hidden"
            onClick={() => setDrawer(false)}
          >
            <aside
              className="h-full w-[84%] max-w-sm border-r p-5"
              style={{ background: "var(--surface)", borderColor: "var(--line)" }}
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                <Brand />
                <button
                  type="button"
                  className="button-secondary h-10 min-h-10 w-10 p-0"
                  onClick={() => setDrawer(false)}
                  aria-label="关闭菜单"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <nav className="mt-8 space-y-6" aria-label="抽屉导航">
                {navGroups.map((group) => (
                  <div key={group.label}>
                    <p className="muted mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em]">
                      {group.label}
                    </p>
                    <div className="space-y-1">
                      {group.items.map((item) => (
                        <NavItem
                          key={item.href}
                          item={item}
                          active={pathname === item.href}
                          onClick={() => setDrawer(false)}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </nav>
              <div className="soft-block mt-8 p-4">
                <p className="text-xs font-semibold">公开只读视图</p>
                <p className="muted mt-1 text-[11px] leading-5">
                  页面中的金额和仓位仅供查看，不能从这里发起任何资产操作。
                </p>
              </div>
            </aside>
          </div>
        )}
      </div>
    </PrivacyContext.Provider>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div className={`brand-bubble relative grid place-items-center rounded-xl ${compact ? "h-9 w-9" : "h-10 w-10"}`}>
        <Orbit className="h-5 w-5" />
        <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-[var(--surface)] bg-cyan-300" />
      </div>
      <div className={compact ? "hidden sm:block" : ""}>
        <p
          className="text-[13px] font-extrabold tracking-[0.08em]"
          style={{ fontFamily: "var(--font-display), var(--font-body), sans-serif" }}
        >
          ATLAS LEDGER
        </p>
        <div className="mt-0.5 flex items-center gap-1.5">
          <span className="h-1 w-1 rounded-full bg-[var(--aqua)]" />
          <p className="muted text-[9px] tracking-[0.08em]">YOUR ASSET UNIVERSE</p>
        </div>
      </div>
    </div>
  );
}

function NavItem({
  item,
  active,
  onClick,
}: {
  item: NavItemData;
  active: boolean;
  onClick?: () => void;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onClick}
      className={`relative flex min-h-10 items-center gap-3 rounded-[10px] px-3 text-sm font-medium transition ${
        active ? "nav-active" : "muted hover:bg-[var(--surface-soft)] hover:text-[var(--text)]"
      }`}
    >
      {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-white/80" />}
      <Icon className="h-[17px] w-[17px]" />
      {item.label}
    </Link>
  );
}

function MobileNavItem({ item, active }: { item: NavItemData; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={`flex min-h-12 flex-col items-center justify-center gap-1 rounded-xl text-[10px] font-medium transition ${
        active ? "nav-active" : "muted"
      }`}
    >
      <Icon className="h-[18px] w-[18px]" />
      <span>{item.shortLabel}</span>
    </Link>
  );
}
