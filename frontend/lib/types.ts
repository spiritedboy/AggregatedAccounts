export type Envelope<T> = {
  success: boolean;
  data: T;
  error: { message: string } | null;
  timestamp: string;
};

export type ExchangeAccount = {
  id: string;
  exchange: string;
  connection_name: string;
  masked_identifier: string;
  is_active: boolean;
  is_demo: boolean;
  connection_status: string;
  permission_status: Record<string, boolean | null>;
  data_completeness: string;
  tracking_started_at: string;
  last_synced_at: string | null;
};

export type AssetBalance = {
  asset: string;
  account_type: string;
  available: number;
  locked: number;
  value_usd: number | null;
  price_source: string;
  recorded_at: string;
};

export type AccountBalance = {
  exchange: string;
  account_id: string;
  connection_name: string;
  total_equity_usd: number;
  available_balance_usd: number;
  margin_balance_usd: number;
  unrealized_pnl_usd: number;
  unvalued_asset_count: number;
  price_source: string;
  recorded_at: string;
  assets: AssetBalance[];
};

export type Position = {
  id: string;
  exchange: string;
  exchange_account_id: string;
  tracking_period_id: string;
  symbol: string;
  normalized_symbol: string;
  market_type: string;
  side: "LONG" | "SHORT";
  position_size: number;
  position_value_usd: number;
  entry_price: number;
  mark_price: number;
  liquidation_price: number | null;
  leverage: number;
  margin_mode: string;
  margin_used: number;
  unrealized_pnl: number;
  tracking_unrealized_pnl_change: number;
  unrealized_pnl_percent: number;
  realized_pnl: number;
  funding_fee: number;
  trading_fee: number;
  open_time: string;
  tracking_started_at: string;
  is_initial_position: boolean;
  update_time: string;
};

export type ClosedPosition = {
  id: string;
  exchange: string;
  symbol: string;
  normalized_symbol: string;
  side: "LONG" | "SHORT";
  open_time: string;
  close_time: string;
  average_entry_price: number;
  average_exit_price: number;
  max_position_size: number;
  realized_pnl: number;
  funding_fee: number;
  trading_fee: number;
  net_pnl: number;
  return_percent: number;
  data_source: string;
  data_completeness: string;
  tracking_started_at: string;
};

export type DashboardData = {
  estimated_total_equity: number;
  available_balance: number;
  margin_used: number;
  unrealized_pnl_change: number;
  today_pnl: number;
  cumulative_pnl: number;
  unvalued_asset_count: number;
  tracking_started_at: string | null;
  last_updated_at: string | null;
  by_exchange: Array<{
    exchange: string;
    connection_name: string;
    equity: number;
    available: number;
    unrealized_pnl: number;
    status: string;
    completeness: string;
  }>;
  equity_curve: Array<{ date: string; pnl: number; equity: number }>;
  positions: Position[];
  notice: string;
  demo_mode: boolean;
};

export type EquityCurveRange = "1d" | "1w" | "1m" | "6m" | "1y";

export type EquityCurveData = {
  range: EquityCurveRange;
  sample_interval: "5m";
  resolution: string;
  from: string;
  to: string;
  points: Array<{
    timestamp: string;
    equity: number;
    available_balance: number;
    margin_balance: number;
    unrealized_pnl: number;
    account_count: number;
    stale_account_count: number;
    source_latest_at: string | null;
  }>;
  change: {
    amount: number | null;
    percent: number | null;
  };
};

export type PnlPoint = {
  period: string;
  investment_return: number;
  cumulative_return: number;
  realized_pnl: number;
  unrealized_pnl_change: number;
  cumulative_unrealized_pnl_change: number;
  funding_fee: number;
  trading_fee: number;
  equity: number;
};

export type SyncStatusData = {
  summary: {
    total_accounts: number;
    healthy_accounts: number;
    stale_accounts: number;
    failing_accounts: number;
    running_accounts: number;
    checked_at: string;
  };
  accounts: Array<{
    account_id: string;
    exchange: string;
    connection_name: string;
    connection_status: string;
    data_completeness: string;
    last_synced_at: string | null;
    is_stale: boolean;
    stale_after_seconds: number;
    consecutive_failures: number;
    last_success_at: string | null;
    latest_job: {
      status: string;
      started_at: string;
      finished_at: string | null;
      duration_ms: number | null;
      records_written: number;
    } | null;
    last_error: {
      type: string;
      message: string;
      occurred_at: string;
    } | null;
  }>;
};

export type AccountingRecord = {
  id: string;
  exchange_account_id: string;
  exchange: string;
  connection_name: string;
  record_type:
    | "REALIZED_PNL"
    | "FUNDING_FEE"
    | "TRADING_FEE"
    | "DEPOSIT"
    | "WITHDRAW"
    | "WITHDRAWAL";
  subtype: string;
  asset: string;
  amount_usd: number;
  signed_amount_usd: number;
  symbol: string | null;
  record_time: string;
  source_record_id: string;
};

export type AccountingRecordsData = {
  items: AccountingRecord[];
  total: number;
  summary: {
    realized_pnl: number;
    funding_fee: number;
    trading_fee: number;
    deposits: number;
    withdrawals: number;
    net_cash_flow: number;
    net_effect: number;
  };
};

export type CompletenessComponent = {
  status: "COMPLETE" | "PARTIAL" | "UNSUPPORTED";
  last_synced_at: string | null;
  record_count: number;
  latest_record_at: string | null;
  reason: string;
};

export type DataCompletenessData = {
  summary: {
    total_accounts: number;
    complete_components: number;
    partial_components: number;
    unsupported_components: number;
    checked_at: string;
  };
  accounts: Array<{
    account_id: string;
    exchange: string;
    connection_name: string;
    overall_status: string;
    components: {
      equity: CompletenessComponent;
      balances: CompletenessComponent;
      positions: CompletenessComponent;
      closed_positions: CompletenessComponent;
      realized_pnl: CompletenessComponent;
      funding_fee: CompletenessComponent;
      trading_fee: CompletenessComponent;
      cash_flow: CompletenessComponent;
    };
  }>;
};

export type ReconciliationData = {
  totals: {
    initial_equity: number;
    current_equity: number;
    deposits: number;
    withdrawals: number;
    net_cash_flow: number;
    equity_return: number;
    realized_pnl: number;
    funding_fee: number;
    trading_fee: number;
    unrealized_pnl_change: number;
    component_return: number;
    variance: number;
    status: "MATCHED" | "REVIEW";
  };
  accounts: Array<{
    account_id: string;
    exchange: string;
    connection_name: string;
    tracking_started_at: string;
    last_synced_at: string | null;
    initial_equity: number;
    current_equity: number;
    deposits: number;
    withdrawals: number;
    net_cash_flow: number;
    equity_return: number;
    realized_pnl: number;
    funding_fee: number;
    trading_fee: number;
    unrealized_pnl_change: number;
    component_return: number;
    variance: number;
    tolerance: number;
    status: "MATCHED" | "REVIEW";
    data_completeness: string;
  }>;
  notice: string;
};

export type RiskData = {
  summary: {
    risk_level: "LOW" | "MEDIUM" | "HIGH";
    total_equity: number;
    total_position_value: number;
    max_drawdown_percent: number;
    largest_exchange_concentration_percent: number;
    largest_position_exposure_percent: number;
    margin_utilization_percent: number;
    nearest_liquidation_distance_percent: number | null;
  };
  exchange_concentration: Array<{
    exchange: string;
    equity: number;
    percent: number;
  }>;
  top_exposures: Array<{
    symbol: string;
    normalized_symbol: string;
    exchanges: string[];
    position_value: number;
    unrealized_pnl: number;
    equity_percent: number;
  }>;
  liquidation_risks: Array<{
    exchange: string;
    symbol: string;
    side: "LONG" | "SHORT";
    distance_percent: number;
  }>;
};
