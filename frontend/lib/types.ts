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
  display_symbol: string;
  original_symbol: string;
  translation_status: "NOT_APPLICABLE" | "PENDING" | "READY" | "FAILED";
  translation_provider: string;
  market_type: string;
  side: "LONG" | "SHORT";
  position_size: number;
  position_value_usd: number;
  entry_price: number;
  mark_price: number;
  liquidation_price: number | null;
  liquidation_distance_percent: number | null;
  liquidation_risk_level: LiquidationRiskLevel | null;
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

export type LiquidationRiskLevel = "SAFE" | "WATCH" | "DANGER";

export type ClosedPosition = {
  id: string;
  exchange: string;
  symbol: string;
  normalized_symbol: string;
  display_symbol: string;
  original_symbol: string;
  translation_status: "NOT_APPLICABLE" | "PENDING" | "READY" | "FAILED";
  translation_provider: string;
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
  leverage: number;
  margin_used: number;
  return_percent: number;
  data_source: string;
  data_completeness: string;
  tracking_started_at: string;
};

export type DashboardData = {
  schema_version: number;
  estimated_total_equity: number;
  available_balance: number;
  margin_used: number;
  current_position_pnl: number;
  cumulative_net_pnl: number;
  unrealized_pnl_change: number;
  today_pnl: number;
  today: {
    date: string;
    data_available: boolean;
    opening_equity: number | null;
    net_return: number;
    return_percent: number | null;
    realized_pnl: number;
    unrealized_pnl_change: number;
    funding_fee: number;
    trading_fee: number;
    net_cash_flow: number;
    component_return: number;
    reconciliation_difference: number;
    is_reconciled: boolean;
  };
  cumulative_pnl: number;
  unvalued_asset_count: number;
  unvalued_assets: Array<{
    exchange: string;
    connection_name: string;
    asset: string;
    account_type: string;
    quantity: number;
    price_source: string;
  }>;
  tracking_started_at: string | null;
  last_updated_at: string | null;
  positions_updated_at: string | null;
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
  position_highlights: {
    largest_winner: Position | null;
    largest_loser: Position | null;
  };
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
  net_cash_flow: number;
  equity: number;
};

export type BehaviorPeriod = "7d" | "30d" | "90d" | "all";

export type BehaviorMetricRow = {
  key: string;
  label: string;
  trade_count: number;
  win_rate: number;
  net_pnl: number;
  average_pnl: number;
  average_win: number;
  average_loss: number;
  payoff_ratio: number | null;
  payoff_ratio_unbounded: boolean;
  profit_factor: number | null;
  profit_factor_unbounded: boolean;
  gross_profit: number;
  gross_loss: number;
};

export type BehaviorInsight = {
  code:
    | "DURATION_BEST"
    | "HIGH_LEVERAGE_WEAK"
    | "SYMBOL_BEST"
    | "OPEN_SESSION_LOW_WIN_RATE"
    | "EXCHANGE_LOSS";
  tone: "positive" | "negative" | "warning";
  target_tab: "time" | "position" | "symbol";
  target_key: string;
  label?: string;
  trade_count: number;
  net_pnl: number;
  win_rate?: number;
  profit_factor?: number;
};

export type BehaviorAnalysis = {
  schema_version: number;
  period: BehaviorPeriod;
  timezone: "Asia/Shanghai";
  requested_from: string | null;
  effective_from: string | null;
  to: string;
  trade_count: number;
  minimum_insight_sample_size: number;
  data_quality: {
    invalid_duration_count: number;
    missing_leverage_count: number;
    missing_margin_count: number;
    position_size_basis: "HISTORICAL_MARGIN_USED_USD";
  };
  duration: BehaviorMetricRow[];
  open_session: BehaviorMetricRow[];
  weekday: BehaviorMetricRow[];
  leverage: BehaviorMetricRow[];
  position_size: BehaviorMetricRow[];
  symbols: BehaviorMetricRow[];
  sides: BehaviorMetricRow[];
  exchanges: BehaviorMetricRow[];
  insights: BehaviorInsight[];
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

export type AccountsBootstrapData = {
  accounts: ExchangeAccount[];
  sync_status: SyncStatusData;
  balances: AccountBalance[];
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
    net_realized_pnl: number;
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

export type AccountingBootstrapData = {
  records: AccountingRecordsData;
  completeness: DataCompletenessData;
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
    net_realized_pnl: number;
    current_position_pnl: number;
    initial_position_pnl: number;
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
    net_realized_pnl: number;
    current_position_pnl: number;
    initial_position_pnl: number;
    component_return: number;
    variance: number;
    tolerance: number;
    status: "MATCHED" | "REVIEW";
    data_completeness: string;
  }>;
  quality: {
    status: "HEALTHY" | "REVIEW";
    issue_count: number;
    error_count: number;
    warning_count: number;
    issues: Array<{
      code: string;
      severity: "ERROR" | "WARNING";
      entity: string;
      message: string;
      account_id: string;
      exchange: string;
      connection_name: string;
      checked_at: string | null;
    }>;
  };
  notice: string;
};

export type RiskData = {
  schema_version: number;
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
    position_id: string;
    exchange_account_id: string;
    exchange: string;
    symbol: string;
    normalized_symbol: string;
    side: "LONG" | "SHORT";
    mark_price: number;
    liquidation_price: number;
    distance_percent: number;
    risk_level: LiquidationRiskLevel;
    margin_mode: string;
  }>;
};

export type AnalyticsBootstrapData = {
  reconciliation: ReconciliationData;
  risk: RiskData;
};

export type DashboardBootstrapData = {
  dashboard: DashboardData;
  risk: RiskData;
  equity_curve: EquityCurveData;
};
