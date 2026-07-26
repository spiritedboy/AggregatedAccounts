import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AccountsPage from "@/app/accounts/page";
import DashboardPage from "@/app/dashboard/page";
import HistoryPage from "@/app/history/page";
import LoginPage from "@/app/login/page";
import PnlPage from "@/app/pnl/page";
import PositionsPage from "@/app/positions/page";
import { AppShell } from "@/components/app-shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="chart" />,
}));

function envelope(data: unknown) {
  return new Response(
    JSON.stringify({ success: true, data, error: null, timestamp: new Date().toISOString() }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

const account = {
  id: "b46267a1-f6b1-4b4f-a46f-9660d32ac214",
  exchange: "BINANCE",
  connection_name: "主账户只读",
  masked_identifier: "abcd••••••••wxyz",
  is_active: true,
  is_demo: false,
  connection_status: "CONNECTED",
  permission_status: {
    read: true,
    spot_trade: false,
    futures_trade: false,
    transfer: false,
    withdraw: false,
  },
  data_completeness: "COMPLETE",
  tracking_started_at: "2026-07-01T00:00:00Z",
  last_synced_at: "2026-07-26T00:00:00Z",
};

const position = {
  id: "p1",
  exchange: "BINANCE",
  exchange_account_id: account.id,
  tracking_period_id: "t1",
  symbol: "BTCUSDT",
  normalized_symbol: "BTC-USDT-PERP",
  market_type: "PERPETUAL",
  side: "LONG",
  position_size: 0.4,
  position_value_usd: 28000,
  entry_price: 68000,
  mark_price: 70000,
  liquidation_price: 45000,
  leverage: 5,
  margin_mode: "CROSS",
  margin_used: 5600,
  unrealized_pnl: 800,
  tracking_unrealized_pnl_change: 520,
  unrealized_pnl_percent: 1.85,
  realized_pnl: 0,
  funding_fee: -3,
  trading_fee: 5,
  open_time: "2026-07-20T00:00:00Z",
  tracking_started_at: "2026-07-01T00:00:00Z",
  is_initial_position: true,
  update_time: "2026-07-26T00:00:00Z",
};

function installFetch(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/auth/status")) return envelope({ authenticated: true });
      const match = Object.entries(routes).find(([path]) => url.includes(path));
      return match ? envelope(match[1]) : envelope({});
    }),
  );
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.classList.add("dark");
  Object.defineProperty(document, "cookie", {
    writable: true,
    value: "portfolio_csrf=test-csrf",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("portfolio pages", () => {
  it("renders the login page with a protected password field", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            success: false,
            data: null,
            error: { message: "请先登录" },
            timestamp: new Date().toISOString(),
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    render(<LoginPage />);
    const input = screen.getByLabelText("访问密码");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("button", { name: /安全进入/ })).toBeInTheDocument();
  });

  it("renders dashboard metrics, charts, and demo banner", async () => {
    installFetch({
      "/api/dashboard/summary": {
        estimated_total_equity: 100000,
        available_balance: 62000,
        margin_used: 18000,
        unrealized_pnl_change: 520,
        today_pnl: 230,
        cumulative_pnl: 4200,
        unvalued_asset_count: 1,
        tracking_started_at: "2026-07-01T00:00:00Z",
        last_updated_at: "2026-07-26T00:00:00Z",
        by_exchange: [
          {
            exchange: "BINANCE",
            connection_name: "Binance 演示账户",
            equity: 100000,
            available: 62000,
            unrealized_pnl: 520,
            status: "CONNECTED",
            completeness: "COMPLETE",
          },
        ],
        equity_curve: [{ date: "2026-07-26", pnl: 4200, equity: 100000 }],
        positions: [position],
        notice: "仅统计添加 API Key 后产生的数据",
        demo_mode: true,
      },
    });
    render(<DashboardPage />);
    expect(await screen.findByText("估算总权益")).toBeInTheDocument();
    expect(screen.getByText(/当前为演示数据/)).toBeInTheDocument();
    expect(screen.getByText("净值曲线")).toBeInTheDocument();
    expect(screen.getByText("资产分布")).toBeInTheDocument();
  });

  it("renders current positions without trading controls", async () => {
    installFetch({
      "/api/positions/current": { items: [position], total: 1 },
    });
    render(<PositionsPage />);
    expect(await screen.findAllByText("BTC-USDT-PERP")).not.toHaveLength(0);
    expect(screen.getAllByText(/US\$800\.00/)).not.toHaveLength(0);
    expect(screen.getAllByText(/统计期变化/)).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: /平仓/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /下单/ })).not.toBeInTheDocument();
  });

  it("renders history with CSV export and reconstruction label", async () => {
    installFetch({
      "/api/positions/history": {
        total: 1,
        items: [
          {
            id: "c1",
            exchange: "OKX",
            symbol: "ETH-USDT-SWAP",
            normalized_symbol: "ETH-USDT-PERP",
            side: "SHORT",
            open_time: "2026-07-01T00:00:00Z",
            close_time: "2026-07-02T00:00:00Z",
            average_entry_price: 3800,
            average_exit_price: 3700,
            max_position_size: 2,
            realized_pnl: 200,
            funding_fee: -2,
            trading_fee: 4,
            net_pnl: 194,
            return_percent: 2.5,
            data_source: "RECONSTRUCTED",
            data_completeness: "PARTIAL",
            tracking_started_at: "2026-07-01T00:00:00Z",
          },
        ],
      },
    });
    render(<HistoryPage />);
    expect(await screen.findByText("本地重建")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /导出 CSV/ })).toBeInTheDocument();
  });

  it("renders PnL analytics and all period selectors", async () => {
    const point = {
      period: "2026-07-26",
      investment_return: 120,
      realized_pnl: 100,
      funding_fee: -2,
      trading_fee: 3,
    };
    installFetch({
      "/api/pnl/summary": {
        period_initial_equity: 10000,
        period_investment_return: 120,
        period_realized_pnl: 100,
        period_unrealized_pnl_change: 25,
        period_funding_fee: -2,
        period_trading_fee: 3,
        best_day: 120,
        worst_day: -30,
        profitable_days: 12,
        losing_days: 4,
        notice: "仅统计添加 API Key 后产生的数据",
      },
      "/api/pnl/daily": [point],
      "/api/pnl/weekly": [point],
      "/api/pnl/monthly": [point],
      "/api/pnl/by-exchange": [
        {
          exchange: "BINANCE",
          realized_pnl: 100,
          funding_fee: -2,
          trading_fee: 3,
          investment_return: 120,
        },
      ],
    });
    render(<PnlPage />);
    expect(await screen.findByText("累计收益")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "每日" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "每周" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "每月" })).toBeInTheDocument();
  });

  it("keeps exchange secrets in password inputs and exposes mobile navigation", async () => {
    installFetch({ "/api/exchange-accounts": [account] });
    render(<AccountsPage />);
    await screen.findByText("主账户只读");
    expect(screen.getByRole("navigation", { name: "移动端导航" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "添加账户" }));
    const secret = screen.getByLabelText("API Secret");
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("autocomplete", "new-password");
    expect(screen.getByText(/仅接受纯只读 API Key/)).toBeInTheDocument();
  });

  it("requires explicit confirmation before deleting an account", async () => {
    installFetch({ "/api/exchange-accounts": [account] });
    render(<AccountsPage />);
    await screen.findByText("主账户只读");
    fireEvent.click(screen.getByRole("button", { name: "删除 主账户只读" }));
    expect(screen.getByText("删除 主账户只读？")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认删除" })).toBeInTheDocument();
  });

  it("persists the selected theme when the app shell remounts", async () => {
    installFetch({});
    window.localStorage.setItem("atlas-theme", "light");

    const first = render(
      <AppShell>
        <div>主题测试页面</div>
      </AppShell>,
    );
    await screen.findByText("主题测试页面");
    await waitFor(() => expect(document.documentElement).not.toHaveClass("dark"));

    await userEvent.click(screen.getByRole("button", { name: "切换主题" }));
    expect(window.localStorage.getItem("atlas-theme")).toBe("dark");
    expect(document.documentElement).toHaveClass("dark");

    first.unmount();
    document.documentElement.classList.remove("dark");
    render(
      <AppShell>
        <div>主题测试页面</div>
      </AppShell>,
    );
    await screen.findByText("主题测试页面");
    await waitFor(() => expect(document.documentElement).toHaveClass("dark"));
  });
});
