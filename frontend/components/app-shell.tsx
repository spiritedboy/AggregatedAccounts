"use client";

import {
  BarChart3,
  Compass,
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
  useRef,
  useState,
} from "react";
import { money, signedMoney, type DisplayCurrency } from "@/lib/format";
import { BackToTop } from "@/components/back-to-top";

const THEME_STORAGE_KEY = "atlas-theme";
const CURRENCY_STORAGE_KEY = "atlas-currency";
const USD_CNY_RATE_STORAGE_KEY = "atlas-usd-cny-rate";
const USD_CNY_RATE_DATE_STORAGE_KEY = "atlas-usd-cny-rate-date";
const USD_CNY_RATE_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=CNY";

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
      { href: "/dashboard", label: "今日驾驶舱", shortLabel: "今日", icon: LayoutDashboard },
      { href: "/positions", label: "当前仓位", shortLabel: "当前仓位", icon: Orbit },
      { href: "/history", label: "历史仓位", shortLabel: "历史仓位", icon: History },
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
  ["/dashboard", "/positions", "/history", "/pnl"].includes(item.href),
);

type CurrencyContextValue = {
  currency: DisplayCurrency;
  usdCnyRate: number;
  rateDate: string | null;
  formatMoney: (value: number) => string;
  formatSignedMoney: (value: number) => string;
};

const CurrencyContext = createContext<CurrencyContextValue>({
  currency: "USD",
  usdCnyRate: 1,
  rateDate: null,
  formatMoney: (value) => money(value),
  formatSignedMoney: (value) => signedMoney(value),
});

export function useCurrency() {
  return useContext(CurrencyContext);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [dark, setDark] = useState(true);
  const [currency, setCurrency] = useState<DisplayCurrency>("USD");
  const [usdCnyRate, setUsdCnyRate] = useState(1);
  const [rateDate, setRateDate] = useState<string | null>(null);
  const [rateReady, setRateReady] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const themeTransitionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    const nextDark = saved
      ? saved === "dark"
      : document.documentElement.classList.contains("dark");
    setDark(nextDark);
    document.documentElement.classList.toggle("dark", nextDark);
    document.documentElement.dataset.theme = nextDark ? "dark" : "light";
  }, []);

  useEffect(() => {
    const savedCurrency = window.localStorage.getItem(CURRENCY_STORAGE_KEY);
    const savedRate = Number(window.localStorage.getItem(USD_CNY_RATE_STORAGE_KEY));
    const savedDate = window.localStorage.getItem(USD_CNY_RATE_DATE_STORAGE_KEY);
    if (Number.isFinite(savedRate) && savedRate > 0) {
      setUsdCnyRate(savedRate);
      setRateReady(true);
      if (savedCurrency === "CNY") setCurrency("CNY");
    }
    if (savedDate) setRateDate(savedDate);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let midnightTimer: ReturnType<typeof setTimeout> | undefined;

    const localDate = () => {
      const now = new Date();
      return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    };
    const refreshRate = async () => {
      try {
        const response = await fetch(USD_CNY_RATE_URL, { cache: "no-store" });
        if (!response.ok) throw new Error(`汇率请求失败：${response.status}`);
        const payload = (await response.json()) as { date?: string; rates?: { CNY?: number } };
        const nextRate = Number(payload.rates?.CNY);
        if (!Number.isFinite(nextRate) || nextRate <= 0) throw new Error("汇率响应无效");
        if (cancelled) return;
        const nextDate = localDate();
        setUsdCnyRate(nextRate);
        setRateReady(true);
        setRateDate(payload.date ?? nextDate);
        window.localStorage.setItem(USD_CNY_RATE_STORAGE_KEY, String(nextRate));
        window.localStorage.setItem(USD_CNY_RATE_DATE_STORAGE_KEY, nextDate);
      } catch {
        // Keep the latest successful local rate; USD remains usable if no rate exists.
      }
    };
    const scheduleMidnightRefresh = () => {
      const now = new Date();
      const nextMidnight = new Date(now);
      nextMidnight.setHours(24, 0, 0, 0);
      midnightTimer = setTimeout(async () => {
        await refreshRate();
        scheduleMidnightRefresh();
      }, nextMidnight.getTime() - now.getTime());
    };

    const cachedDate = window.localStorage.getItem(USD_CNY_RATE_DATE_STORAGE_KEY);
    if (cachedDate !== localDate()) void refreshRate();
    scheduleMidnightRefresh();
    return () => {
      cancelled = true;
      if (midnightTimer) clearTimeout(midnightTimer);
    };
  }, []);

  function toggleTheme() {
    const next = !dark;
    const applyTheme = () => {
      window.localStorage.setItem(THEME_STORAGE_KEY, next ? "dark" : "light");
      document.documentElement.classList.toggle("dark", next);
      document.documentElement.dataset.theme = next ? "dark" : "light";
      setDark(next);
    };
    const transitionDocument = document as Document & {
      startViewTransition?: (callback: () => void) => { finished: Promise<void> };
    };

    if (transitionDocument.startViewTransition) {
      transitionDocument.startViewTransition(applyTheme);
      return;
    }

    document.documentElement.classList.add("theme-transitioning");
    applyTheme();
    if (themeTransitionTimer.current) clearTimeout(themeTransitionTimer.current);
    themeTransitionTimer.current = setTimeout(() => {
      document.documentElement.classList.remove("theme-transitioning");
      themeTransitionTimer.current = null;
    }, 450);
  }

  const currencyContext = useMemo(
    () => ({
      currency,
      usdCnyRate,
      rateDate,
      formatMoney: (value: number) => money(value, currency, usdCnyRate),
      formatSignedMoney: (value: number) => signedMoney(value, currency, usdCnyRate),
    }),
    [currency, rateDate, usdCnyRate],
  );

  function toggleCurrency() {
    setCurrency((current) => {
      const next = current === "USD" ? "CNY" : "USD";
      window.localStorage.setItem(CURRENCY_STORAGE_KEY, next);
      return next;
    });
  }

  const activePage = allNavItems.find((item) => pathname === item.href);
  const moreActive = ["/ledger", "/reconciliation", "/accounts"].includes(pathname);

  return (
    <CurrencyContext.Provider value={currencyContext}>
      <div className="min-h-screen lg:grid lg:grid-cols-[224px_1fr]">
        <aside
          className="sticky top-0 hidden h-screen border-r bg-[var(--surface)] px-3 py-5 lg:flex lg:flex-col"
          style={{
            borderColor: "var(--line)",
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
            className="mt-auto overflow-hidden rounded-[12px] border bg-[var(--surface-soft)] p-3"
            style={{
              borderColor: "var(--line)",
            }}
          >
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-[var(--positive)]" />
              <p className="mono-number text-[10px] font-semibold tracking-[0.08em]">READ ONLY</p>
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
              background: "color-mix(in srgb, var(--surface) 96%, transparent)",
              borderColor: "var(--line)",
              backdropFilter: "blur(10px)",
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
              <div className="mr-1 hidden items-center gap-2 text-[10px] sm:flex" aria-label="数据同步周期 60 秒">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--positive)]" />
                <span className="mono-number font-semibold tracking-[0.08em] text-[var(--muted)]">SYNC · 60S</span>
              </div>
              <button
                type="button"
                className="button-secondary h-10 min-h-10 px-3 font-mono text-xs font-bold tracking-wide"
                aria-label={currency === "USD" ? "切换为人民币 CNY" : "切换为美元 USD"}
                title={!rateReady ? "正在获取 USD/CNY 汇率" : currency === "CNY" ? `1 USD = ${usdCnyRate} CNY${rateDate ? ` · ${rateDate}` : ""}` : "当前以美元显示"}
                onClick={toggleCurrency}
                disabled={currency === "USD" && !rateReady}
              >
                {currency}
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

          <main className="mx-auto w-full min-w-0 max-w-[1540px] overflow-x-clip px-3 pb-[calc(6.75rem+env(safe-area-inset-bottom))] pt-4 sm:px-4 md:px-6 md:pb-8 md:pt-5 xl:px-8">
            {children}
          </main>
        </div>

        <nav
          className="fixed inset-x-3 bottom-[calc(.65rem+env(safe-area-inset-bottom))] z-40 grid grid-cols-5 rounded-[14px] border p-1 lg:hidden"
          style={{
            background: "color-mix(in srgb, var(--surface) 94%, transparent)",
            borderColor: "var(--line)",
            boxShadow: "0 10px 30px -16px rgba(0,0,0,.55)",
            backdropFilter: "blur(12px)",
          }}
          aria-label="移动端导航"
        >
          {mobileNavItems.map((item) => (
            <MobileNavItem key={item.href} item={item} active={pathname === item.href} />
          ))}
          <button
            type="button"
            className={`flex min-h-12 flex-col items-center justify-center gap-1 rounded-[9px] text-[10px] font-medium transition ${moreActive ? "nav-active" : "muted"}`}
            onClick={() => setDrawer(true)}
            aria-label="更多页面"
          >
            <Menu className="h-[18px] w-[18px]" />
            <span>更多</span>
          </button>
        </nav>

        <BackToTop />
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
    </CurrencyContext.Provider>
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
      {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-[var(--accent)]" />}
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
      className={`flex min-h-12 flex-col items-center justify-center gap-1 rounded-[9px] text-[10px] font-medium transition ${
        active ? "nav-active" : "muted"
      }`}
    >
      <Icon className="h-[18px] w-[18px]" />
      <span>{item.shortLabel}</span>
    </Link>
  );
}
