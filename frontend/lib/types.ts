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

export type PnlPoint = {
  period: string;
  investment_return: number;
  realized_pnl: number;
  funding_fee: number;
  trading_fee: number;
};
