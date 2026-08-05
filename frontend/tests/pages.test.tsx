import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AccountsPage from "@/app/accounts/page";
import DashboardPage from "@/app/dashboard/page";
import HistoryPage from "@/app/history/page";
import LedgerPage from "@/app/ledger/page";
import PnlPage from "@/app/pnl/page";
import PositionsPage from "@/app/positions/page";
import ReconciliationPage from "@/app/reconciliation/page";
import { AppShell, useCurrency } from "@/components/app-shell";

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
  unrealized_pnl_percent: 14.29,
  realized_pnl: 0,
  funding_fee: -3,
  trading_fee: 5,
  open_time: "2026-07-20T00:00:00Z",
  tracking_started_at: "2026-07-01T00:00:00Z",
  is_initial_position: true,
  update_time: "2026-07-26T00:00:00Z",
};

const shortPosition = {
  ...position,
  id: "p2",
  symbol: "ETHUSDT",
  normalized_symbol: "ETH-USDT-PERP",
  side: "SHORT",
  position_value_usd: 50000,
  unrealized_pnl: 1000,
  unrealized_pnl_percent: 2,
};

const polymarketPosition = {
  ...position,
  id: "p3",
  exchange: "POLYMARKET",
  symbol: "Will the market close higher?",
  normalized_symbol: "POLYMARKET-POSITION",
  display_symbol: "集成测试会通过吗？ · 是",
  original_symbol: "Will the integration test pass? · Yes",
  translation_status: "READY",
  translation_provider: "BAIDU_LLM",
  market_type: "PREDICTION",
  position_value_usd: 40000,
  unrealized_pnl: -50,
  unrealized_pnl_percent: -0.125,
};

const riskData = {
  summary: {
    risk_level: "LOW",
    total_equity: 100000,
    total_position_value: 28000,
    max_drawdown_percent: 8.5,
    largest_exchange_concentration_percent: 42,
    largest_position_exposure_percent: 28,
    margin_utilization_percent: 5.6,
    nearest_liquidation_distance_percent: 35,
  },
  exchange_concentration: [{ exchange: "BINANCE", equity: 42000, percent: 42 }],
  top_exposures: [
    {
      symbol: "BTCUSDT",
      normalized_symbol: "BTC-USDT-PERP",
      exchanges: ["BINANCE"],
      position_value: 28000,
      unrealized_pnl: 800,
      equity_percent: 28,
    },
  ],
  liquidation_risks: [
    { exchange: "BINANCE", symbol: "BTCUSDT", side: "LONG", distance_percent: 35 },
  ],
};

const syncStatus = {
  summary: {
    total_accounts: 1,
    healthy_accounts: 1,
    stale_accounts: 0,
    failing_accounts: 0,
    running_accounts: 0,
    checked_at: "2026-07-26T00:00:00Z",
  },
  accounts: [
    {
      account_id: account.id,
      exchange: "BINANCE",
      connection_name: account.connection_name,
      connection_status: "CONNECTED",
      data_completeness: "COMPLETE",
      last_synced_at: account.last_synced_at,
      is_stale: false,
      stale_after_seconds: 120,
      consecutive_failures: 0,
      last_success_at: account.last_synced_at,
      latest_job: {
        status: "SUCCESS",
        started_at: account.last_synced_at,
        finished_at: account.last_synced_at,
        duration_ms: 380,
        records_written: 6,
      },
      last_error: null,
    },
  ],
};

const reconciliationData = {
  totals: {
    initial_equity: 95000,
    current_equity: 100000,
    deposits: 1000,
    withdrawals: 0,
    net_cash_flow: 1000,
    equity_return: 4000,
    realized_pnl: 3400,
    funding_fee: -20,
    trading_fee: 40,
    net_realized_pnl: 3340,
    current_position_pnl: 660,
    initial_position_pnl: 0,
    component_return: 4000,
    variance: 0,
    status: "MATCHED",
  },
  accounts: [
    {
      account_id: account.id,
      exchange: "BINANCE",
      connection_name: account.connection_name,
      tracking_started_at: account.tracking_started_at,
      last_synced_at: account.last_synced_at,
      initial_equity: 95000,
      current_equity: 100000,
      deposits: 1000,
      withdrawals: 0,
      net_cash_flow: 1000,
      equity_return: 4000,
      realized_pnl: 3400,
      funding_fee: -20,
      trading_fee: 40,
      net_realized_pnl: 3340,
      current_position_pnl: 660,
      initial_position_pnl: 0,
      component_return: 4000,
      variance: 0,
      tolerance: 100,
      status: "MATCHED",
      data_completeness: "COMPLETE",
    },
  ],
  quality: {
    status: "HEALTHY",
    issue_count: 0,
    error_count: 0,
    warning_count: 0,
    issues: [],
  },
  notice: "reconciliation notice",
};

const completenessData = {
  summary: {
    total_accounts: 1,
    complete_components: 8,
    partial_components: 0,
    unsupported_components: 0,
    checked_at: account.last_synced_at,
  },
  accounts: [
    {
      account_id: account.id,
      exchange: account.exchange,
      connection_name: account.connection_name,
      overall_status: "COMPLETE",
      components: Object.fromEntries(
        [
          "equity",
          "balances",
          "positions",
          "closed_positions",
          "realized_pnl",
          "funding_fee",
          "trading_fee",
          "cash_flow",
        ].map((key) => [
          key,
          {
            status: "COMPLETE",
            last_synced_at: account.last_synced_at,
            record_count: key === "positions" ? 0 : 1,
            latest_record_at: account.last_synced_at,
            reason: "最近一次数据拉取成功",
          },
        ]),
      ),
    },
  ],
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
  it("renders dashboard metrics, charts, and demo banner", async () => {
    const user = userEvent.setup();
    installFetch({
      "/api/dashboard/bootstrap": {
        dashboard: {
          estimated_total_equity: 100000,
          available_balance: 62000,
          margin_used: 18000,
          current_position_pnl: 520,
          cumulative_net_pnl: 4200,
          unrealized_pnl_change: 520,
          today_pnl: 230,
          cumulative_pnl: 4200,
          unvalued_asset_count: 1,
          unvalued_assets: [
            {
              exchange: "BINANCE",
              connection_name: "Binance 演示账户",
              asset: "LDUSDT",
              account_type: "SPOT",
              quantity: 0.36257566,
              price_source: "BINANCE_SPOT_TICKER",
            },
          ],
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
        risk: riskData,
        equity_curve: {
          range: "1d",
          sample_interval: "5m",
          resolution: "5m",
          from: "2026-07-25T00:00:00Z",
          to: "2026-07-26T00:00:00Z",
          points: [
            {
              timestamp: "2026-07-25T00:00:00Z",
              equity: 99000,
              available_balance: 61000,
              margin_balance: 18000,
              unrealized_pnl: 400,
              account_count: 1,
              stale_account_count: 0,
              source_latest_at: "2026-07-25T00:00:00Z",
            },
            {
              timestamp: "2026-07-26T00:00:00Z",
              equity: 100000,
              available_balance: 62000,
              margin_balance: 18000,
              unrealized_pnl: 520,
              account_count: 1,
              stale_account_count: 0,
              source_latest_at: "2026-07-26T00:00:00Z",
            },
          ],
          change: { amount: 1000, percent: 1.010101 },
        },
      },
    });
    render(<DashboardPage />);
    expect(await screen.findByText("估算总权益")).toBeInTheDocument();
    expect(screen.getByText(/当前为演示数据/)).toBeInTheDocument();
    expect(screen.getByText("净值曲线")).toBeInTheDocument();
    expect(screen.getByText("资产分布")).toBeInTheDocument();
    expect(screen.getByText(/净值变化：/)).toBeInTheDocument();
    expect(screen.getByText("1年")).toBeInTheDocument();
    expect(screen.getByText("做多")).toBeInTheDocument();
    expect(screen.getByText("累计净收益")).toBeInTheDocument();
    expect(screen.getByText("已实现毛收益 + 资金费 − 手续费")).toBeInTheDocument();
    expect(screen.getByText("当前持仓收益")).toBeInTheDocument();
    expect(screen.getByText("当前仓位“当前未实现盈亏”求和")).toBeInTheDocument();
    expect(screen.getByText(/LDUSDT · BINANCE/)).toBeInTheDocument();
    expect(screen.getByText(/数量 0.36257566/)).toBeInTheDocument();
    expect(screen.queryByText(/统计期变化/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "1年" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/dashboard/bootstrap?range=1y"),
        expect.anything(),
      ),
    );
  });

  it("renders localized position sides and sorts current positions by value and PnL", async () => {
    const user = userEvent.setup();
    installFetch({
      "/api/positions/current": {
        items: [shortPosition, polymarketPosition, position],
        total: 3,
      },
      "/api/exchange-accounts": [account],
    });
    render(<PositionsPage />);
    expect(await screen.findAllByText("BTC-USDT-PERP")).not.toHaveLength(0);
    expect(screen.getAllByText(/US\$800\.00/)).not.toHaveLength(0);
    expect(screen.getAllByText("本金 US$5,600.00")).not.toHaveLength(0);
    expect(screen.getAllByText("14.29%")).not.toHaveLength(0);
    expect(screen.getAllByRole("button", { name: "仓位价值计算说明" })).not.toHaveLength(0);
    expect(screen.getAllByRole("button", { name: "仓位本金计算说明" })).not.toHaveLength(0);
    expect(document.querySelector(".table-shell-sticky")).toBeInTheDocument();
    expect(screen.getByRole("tooltip", { name: /仓位价值 =/ })).toHaveClass("top-full");
    expect(screen.queryByText(/统计期变化/)).not.toBeInTheDocument();
    expect(screen.getAllByText("做多")).not.toHaveLength(0);
    expect(screen.getAllByText("做空")).not.toHaveLength(0);
    expect(screen.getAllByText("持有")).not.toHaveLength(0);
    expect(screen.getAllByText("集成测试会通过吗？ · 是")).not.toHaveLength(0);
    expect(screen.getAllByText("AI译")).not.toHaveLength(0);
    expect(screen.getAllByText("Will the integration test pass? · Yes")).not.toHaveLength(0);
    expect(screen.queryByText("LONG")).not.toBeInTheDocument();
    expect(screen.queryByText("SHORT")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /平仓/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /下单/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /仓位价值排序：未排序/ }));
    let rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("BTC-USDT-PERP")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /仓位价值排序：升序/ }));
    rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("ETH-USDT-PERP")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /未实现盈亏排序：未排序/ }));
    rows = screen.getAllByRole("row").slice(1);
    expect(
      within(rows[0]).getByText("Will the integration test pass? · Yes"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /未实现盈亏排序：升序/ }));
    rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("ETH-USDT-PERP")).toBeInTheDocument();
  });

  it("renders history and sorts filtered page results by net PnL", async () => {
    const user = userEvent.setup();
    installFetch({
      "/api/exchange-accounts": [account],
      "/api/positions/history": {
        total: 2,
        items: [
          {
            id: "c1",
            exchange: "HYPERLIQUID",
            symbol: "xyz:CXMT",
            normalized_symbol: "CXMT-USDT-PERP",
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
            leverage: 5,
            margin_used: 1520,
            return_percent: 12.76,
            data_source: "EXCHANGE_FILLS",
            data_completeness: "PARTIAL",
            tracking_started_at: "2026-07-01T00:00:00Z",
          },
          {
            id: "c2",
            exchange: "BINANCE",
            symbol: "ETHUSDT",
            normalized_symbol: "ETH-USDT-PERP",
            side: "LONG",
            open_time: "2026-07-03T00:00:00Z",
            close_time: "2026-07-04T00:00:00Z",
            average_entry_price: 2500,
            average_exit_price: 2475,
            max_position_size: 1,
            realized_pnl: -25,
            funding_fee: 0,
            trading_fee: 1,
            net_pnl: -26,
            leverage: 0,
            margin_used: 0,
            return_percent: -20.8,
            data_source: "EXCHANGE_API",
            data_completeness: "COMPLETE",
            tracking_started_at: "2026-07-01T00:00:00Z",
          },
        ],
      },
    });
    render(<HistoryPage />);
    expect(await screen.findAllByText("交易所成交 API")).not.toHaveLength(0);
    expect(screen.getAllByText("部分完整")).not.toHaveLength(0);
    expect(screen.getAllByText("12.76%")).not.toHaveLength(0);
    expect(screen.getAllByText("价格变动 -1%")).not.toHaveLength(0);
    expect(screen.queryByText("杠杆数据不足")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "历史仓位收益率计算说明" })).not.toHaveLength(0);
    expect(screen.getByLabelText("盈亏")).toBeInTheDocument();
    expect(screen.getByLabelText("账户")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /导出 CSV/ })).toBeInTheDocument();
    expect(screen.getAllByText("做多")).not.toHaveLength(0);
    expect(screen.getAllByText("做空")).not.toHaveLength(0);
    expect(screen.queryByText("LONG")).not.toBeInTheDocument();
    expect(screen.queryByText("SHORT")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /净收益排序：未排序/ }));
    let rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("ETH-USDT-PERP")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /净收益排序：升序/ }));
    rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("CXMT-USDT-PERP")).toBeInTheDocument();
  });

  it("renders PnL analytics and all period selectors", async () => {
    const point = {
      period: "2026-07-26",
      investment_return: 120,
      cumulative_return: 120,
      realized_pnl: 100,
      unrealized_pnl_change: 25,
      cumulative_unrealized_pnl_change: 25,
      funding_fee: -2,
      trading_fee: 3,
      equity: 10120,
    };
    installFetch({
      "/api/pnl/bootstrap": {
        summary: {
          period_initial_equity: 10000,
          period_investment_return: 120,
          period_realized_pnl: 100,
          period_net_realized_pnl: 95,
          current_position_pnl: 18,
          period_unrealized_pnl_change: 25,
          period_funding_fee: -2,
          period_trading_fee: 3,
          best_day: 120,
          worst_day: -30,
          profitable_days: 12,
          losing_days: 4,
          notice: "仅统计添加 API Key 后产生的数据",
        },
        daily: [point],
        weekly: [point],
        monthly: [point],
        by_exchange: [
          {
            exchange: "BINANCE",
            realized_pnl: 100,
            funding_fee: -2,
            trading_fee: 3,
            investment_return: 120,
          },
        ],
        by_side: {
          long: { count: 8, net_pnl: 160, average_net_pnl: 20, win_rate: 62.5, average_win: 48, average_loss: -26.67 },
          short: { count: 4, net_pnl: -40, average_net_pnl: -10, win_rate: 25, average_win: 30, average_loss: -23.33 },
          count_ratio: 2,
        },
        trade_quality: {
          count: 12,
          net_pnl: 120,
          average_net_pnl: 10,
          win_rate: 50,
          average_win: 45,
          average_loss: -25,
          payoff_ratio: 1.8,
          profit_factor: 1.8,
          best_trade: { exchange: "BINANCE", symbol: "BTC-USDT-PERP", side: "LONG", net_pnl: 120, close_time: "2026-07-26T00:00:00Z" },
          worst_trade: { exchange: "OKX", symbol: "ETH-USDT-PERP", side: "SHORT", net_pnl: -80, close_time: "2026-07-25T00:00:00Z" },
        },
      },
    });
    render(<PnlPage />);
    expect(await screen.findByText("累计净收益")).toBeInTheDocument();
    expect(screen.getAllByText("已实现毛收益")).not.toHaveLength(0);
    expect(screen.getByText("已实现毛收益 + 资金费 - 手续费")).toBeInTheDocument();
    expect(screen.getByText("当前持仓收益")).toBeInTheDocument();
    expect(screen.getByText("当前仓位“当前未实现盈亏”求和")).toBeInTheDocument();
    expect(screen.getByText("多空表现")).toBeInTheDocument();
    expect(screen.getByText("8 笔")).toBeInTheDocument();
    expect(screen.getByText("4 笔")).toBeInTheDocument();
    expect(screen.getByText("交易质量")).toBeInTheDocument();
    expect(screen.getByText("最大单笔盈利")).toBeInTheDocument();
    expect(screen.getByText("最大单笔亏损")).toBeInTheDocument();
    expect(screen.getAllByText("盈利因子")).not.toHaveLength(0);
    expect(screen.getByText("2.00 : 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "每日" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "每周" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "每月" })).toBeInTheDocument();
  });

  it("renders accounting records and sorts filtered page results by financial impact", async () => {
    const user = userEvent.setup();
    installFetch({
      "/api/accounting/bootstrap": {
        records: {
          total: 2,
          summary: {
            realized_pnl: 120,
            funding_fee: -2,
            trading_fee: 3,
            deposits: 10,
            withdrawals: 0,
            net_cash_flow: 10,
            net_realized_pnl: 115,
            net_effect: 125,
          },
          items: [
            {
              id: "ledger-2",
              exchange_account_id: account.id,
              exchange: "BINANCE",
              connection_name: account.connection_name,
              record_type: "DEPOSIT",
              subtype: "DEPOSIT",
              asset: "USDT",
              amount_usd: 10,
              signed_amount_usd: 10,
              symbol: null,
              record_time: account.last_synced_at,
              source_record_id: "deposit-source-2",
            },
            {
              id: "ledger-1",
              exchange_account_id: account.id,
              exchange: "BINANCE",
              connection_name: account.connection_name,
              record_type: "FUNDING_FEE",
              subtype: "FUNDING_FEE",
              asset: "USDT",
              amount_usd: -2,
              signed_amount_usd: -2,
              symbol: "BTCUSDT",
              record_time: account.last_synced_at,
              source_record_id: "funding-source-1",
            },
          ],
        },
        completeness: completenessData,
      },
    });
    render(<LedgerPage />);
    expect(await screen.findByText("数据完整性明细")).toBeInTheDocument();
    expect(screen.getAllByText("资金费").length).toBeGreaterThan(0);
    expect(screen.getByText("累计净收益")).toBeInTheDocument();
    expect(screen.getByText("已实现毛收益 + 资金费 − 手续费")).toBeInTheDocument();
    expect(screen.getAllByText("已实现毛收益")).not.toHaveLength(0);
    expect(screen.getByText("funding-source-1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /导出 CSV/ })).toBeInTheDocument();
    expect(screen.getByText("8 项完整")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /账务影响排序：未排序/ }));
    let rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("funding-source-1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /账务影响排序：升序/ }));
    rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("deposit-source-2")).toBeInTheDocument();
  });

  it("renders the account page as configuration-managed read-only status", async () => {
    installFetch({
      "/api/accounts/bootstrap": {
        accounts: [account],
        sync_status: syncStatus,
        balances: [
          {
            exchange: "BINANCE",
            account_id: account.id,
            connection_name: account.connection_name,
            total_equity_usd: 10000,
            available_balance_usd: 8000,
            margin_balance_usd: 2000,
            unrealized_pnl_usd: 100,
            unvalued_asset_count: 0,
            price_source: "BINANCE_FAPI_AND_SPOT_TICKER",
            recorded_at: account.last_synced_at,
            assets: [
              {
                asset: "USDT",
                account_type: "SPOT",
                available: 25,
                locked: 0,
                value_usd: 25,
                price_source: "STABLECOIN_PARITY",
                recorded_at: account.last_synced_at,
              },
            ],
          },
        ],
      },
    });
    render(<AccountsPage />);
    expect(await screen.findAllByText("主账户只读")).not.toHaveLength(0);
    expect(screen.getByRole("navigation", { name: "移动端导航" })).toBeInTheDocument();
    expect(screen.getAllByText(/账户由服务器配置文件统一管理/)).not.toHaveLength(0);
    expect(screen.getByText("逐资产余额")).toBeInTheDocument();
    expect(screen.getByText("USDT")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加账户" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /删除/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /测试连接/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /立即同步/ })).not.toBeInTheDocument();
  });

  it("renders reconciliation and risk analytics", async () => {
    installFetch({
      "/api/analytics/bootstrap": {
        reconciliation: reconciliationData,
        risk: riskData,
      },
    });
    render(<ReconciliationPage />);
    expect(await screen.findAllByText(/US\$4,000\.00/)).not.toHaveLength(0);
    expect(screen.getAllByText("累计净收益")).not.toHaveLength(0);
    expect(screen.getByText("已实现毛收益 + 资金费 − 手续费")).toBeInTheDocument();
    expect(screen.getAllByText("当前持仓收益")).not.toHaveLength(0);
    expect(screen.getByText("LOW")).toBeInTheDocument();
    expect(screen.getAllByText(/BTCUSDT/)).not.toHaveLength(0);
    expect(screen.getByText("数据异常检查")).toBeInTheDocument();
    expect(screen.getByText("最近一次同步检查通过。")).toBeInTheDocument();
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

  it("switches monetary values to CNY while keeping the selected unit locally", async () => {
    installFetch({});
    const now = new Date();
    const localDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    window.localStorage.setItem("atlas-usd-cny-rate", "7");
    window.localStorage.setItem("atlas-usd-cny-rate-date", localDate);

    function CurrencyProbe() {
      const { formatMoney } = useCurrency();
      return <span>{formatMoney(100)}</span>;
    }

    render(
      <AppShell>
        <CurrencyProbe />
      </AppShell>,
    );
    expect(await screen.findByText(/US\$100\.00/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "切换为人民币 CNY" }));
    expect(await screen.findByText(/¥700\.00/)).toBeInTheDocument();
    expect(window.localStorage.getItem("atlas-currency")).toBe("CNY");
  });

  it("converts position PnL but keeps entry price and position value in USD", async () => {
    installFetch({
      "/api/positions/current": { items: [position], total: 1 },
      "/api/exchange-accounts": [account],
    });
    const now = new Date();
    const localDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    window.localStorage.setItem("atlas-usd-cny-rate", "7");
    window.localStorage.setItem("atlas-usd-cny-rate-date", localDate);

    render(<PositionsPage />);
    expect(await screen.findAllByText(/US\$800\.00/)).not.toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "切换为人民币 CNY" }));

    expect(await screen.findAllByText(/¥5,600\.00/)).not.toHaveLength(0);
    expect(screen.getAllByText(/US\$28,000\.00/)).not.toHaveLength(0);
    expect(screen.getAllByText(/US\$68,000\.00/)).not.toHaveLength(0);
  });
});
