export type AssetClass = "us_equity" | "crypto" | "forex" | "asia_equity";

export interface HealthResponse {
  status: string;
  service: string;
}

export interface AssetCatalogEntry {
  asset_class: string;
  provider: string;
  free_tier: boolean;
  mvp_enabled: boolean;
  default_benchmark?: string | null;
  notes: string;
  symbols: string[];
}

export interface AssetCatalogResponse {
  assets: AssetCatalogEntry[];
}

export interface CandleRecord {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  adjusted_close?: number | null;
  [key: string]: string | number | boolean | null | undefined;
}

export interface CandleResponse {
  symbol: string;
  asset_class: string;
  provider: string;
  source: string;
  interval: string;
  start_date: string;
  end_date: string;
  include_features: boolean;
  candles: CandleRecord[];
}

export interface BacktestRequest {
  symbols: string[];
  asset_class: AssetClass;
  strategy: "momentum";
  start_date: string;
  end_date: string;
  initial_capital: number;
  interval: "1d";
  save_results: boolean;
}

export interface MetricsResponse {
  total_return: number;
  annualized_return: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  calmar_ratio: number;
  alpha: number;
  beta: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  avg_trade_duration_days: number;
  volatility: number;
  var_95: number;
  cvar_95: number;
  information_ratio: number;
}

export interface EquityCurvePoint {
  timestamp: string;
  equity: number;
}

export interface DrawdownPoint {
  timestamp: string;
  drawdown: number;
}

export interface MonthlyReturnPoint {
  month: string;
  return_value: number;
}

export interface TradeResponse {
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  commission: number;
  slippage: number;
  timestamp: string;
  pnl: number;
  signal_source: string;
  signal_confidence: number;
}

export interface BacktestResponse {
  backtest_id: number | null;
  persisted: boolean;
  persistence_error: string | null;
  status: string;
  created_at: string | null;
  metrics: MetricsResponse;
  equity_curve: EquityCurvePoint[];
  drawdown_curve: DrawdownPoint[];
  trades: TradeResponse[];
  strategy_name: string;
  symbols: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  strategy_params: Record<string, unknown>;
}

export interface RiskAnalyticsResponse {
  backtest_id: number;
  status: string;
  strategy_name: string;
  symbols: string[];
  created_at: string;
  latest_equity: number;
  peak_equity: number;
  trough_equity: number;
  latest_drawdown: number;
  max_drawdown: number;
  volatility: number;
  var_95: number;
  cvar_95: number;
  alpha: number;
  beta: number;
  information_ratio: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  observation_count: number;
  risk_regime: string;
  monthly_returns: MonthlyReturnPoint[];
  drawdown_curve: DrawdownPoint[];
}

export interface RecentBacktestSummary {
  backtest_id: number;
  status: string;
  strategy_name: string;
  asset_class: string | null;
  symbols: string[];
  start_date: string;
  end_date: string;
  created_at: string;
  initial_capital: number;
  total_return: number | null;
  max_drawdown: number | null;
  sharpe_ratio: number | null;
  total_trades: number | null;
  persisted: boolean;
}

export interface RecentBacktestsResponse {
  items: RecentBacktestSummary[];
}

export interface DeleteBacktestResponse {
  backtest_id: number;
  deleted: boolean;
}
