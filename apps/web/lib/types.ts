// Mirrors apps/api/routes/instruments.py and apps/api/routes/stocks.py
// response models exactly. Keep these in sync with the Pydantic models -
// see docs/data_dictionary/technicals_api.md for the authoritative contract.

export type RangeKey = "1M" | "3M" | "6M" | "1Y" | "2Y" | "ALL";

export const RANGE_KEYS: RangeKey[] = ["1M", "3M", "6M", "1Y", "2Y", "ALL"];

export interface InstrumentSummary {
  symbol: string;
  exchange: string;
  company_name: string;
  sector: string | null;
  instrument_type: string;
  active: boolean;
  // Most recently *persisted* research_scores row (apps/worker/jobs.py ::
  // compute_all_scores_job) - null until that batch job has run for this
  // instrument, never computed live by this endpoint.
  score: number | null;
  confidence: number | null;
  band: string | null;
  // Most recently persisted momentum_scans row at the default lookback
  // (apps/worker/jobs.py :: compute_all_momentum_scans_job) - null until
  // that batch job has run, or when the stock has insufficient history
  // to evaluate (never a fabricated true/false either way).
  momentum_pass: boolean | null;
  distance_from_52w_high_pct: number | null;
  // Day-over-day % price change (apps/api/routes/instruments.py's
  // single window-function query) - null when an instrument has fewer
  // than two OHLCV bars ever ingested.
  day_change_pct: number | null;
  // Most recently persisted packages/analyst_estimates/ row.
  // `analyst_upside_pct` is computed server-side against this listing's
  // latest persisted close - null whenever the instrument has zero
  // analyst coverage (common for mid/small-cap NSE names).
  analyst_target_price: number | null;
  analyst_upside_pct: number | null;
  analyst_recommendation: string | null;
  revenue_growth_yoy: number | null;
  pat_growth_yoy: number | null;
}

export type InstrumentSortKey =
  | "symbol"
  | "company_name"
  | "sector"
  | "score"
  | "momentum_pass"
  | "analyst_upside_pct"
  | "day_change_pct"
  | "revenue_growth_yoy"
  | "pat_growth_yoy";
export type SortOrder = "asc" | "desc";

export interface DataFreshness {
  latest_trading_date: string | null;
  as_of: string;
  data_age_days: number | null;
  stale: boolean;
}

export interface PriceBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adjusted_close: number;
  volume: number;
}

export interface PriceResponse {
  symbol: string;
  exchange: string;
  range: RangeKey;
  start_date: string | null;
  end_date: string | null;
  bars: PriceBar[];
  data_freshness: DataFreshness;
}

export interface IndicatorSnapshot {
  as_of_date: string;
  close: number;
  adjusted_close: number;
  sma_20: number | null;
  sma_50: number | null;
  sma_100: number | null;
  sma_150: number | null;
  sma_200: number | null;
  ema_9: number | null;
  ema_20: number | null;
  ema_50: number | null;
  ema_200: number | null;
  adx_14: number | null;
  rsi_14: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  roc_12: number | null;
  stochastic_k: number | null;
  stochastic_d: number | null;
  atr_14: number | null;
  bollinger_upper: number | null;
  bollinger_mid: number | null;
  bollinger_lower: number | null;
  rolling_volatility_20: number | null;
  volume_sma_20: number | null;
  relative_volume_20: number | null;
  obv: number | null;
  fifty_two_week_high: number | null;
  fifty_two_week_low: number | null;
  distance_from_52w_high_pct: number | null;
  distance_from_52w_low_pct: number | null;
  breakout_20d: boolean;
  breakdown_20d: boolean;
}

export interface IndicatorSeries {
  dates: string[];
  close: number[];
  volume: number[];
  ema_20: (number | null)[];
  ema_50: (number | null)[];
  ema_200: (number | null)[];
  rsi_14: (number | null)[];
  macd_line: (number | null)[];
  macd_signal: (number | null)[];
  macd_histogram: (number | null)[];
}

export interface TechnicalsResponse {
  symbol: string;
  exchange: string;
  range: RangeKey;
  as_of_date: string;
  snapshot: IndicatorSnapshot;
  series: IndicatorSeries;
  data_freshness: DataFreshness;
}

export interface RelativeStrengthHorizon {
  stock_return_pct: number | null;
  peer_avg_return_pct: number | null;
  relative_strength_pct: number | null;
  reason: string | null;
}

export interface RelativeStrengthResponse {
  symbol: string;
  exchange: string;
  sector: string | null;
  peer_universe: "seeded_sector_peers";
  peer_count: number;
  peer_symbols: string[];
  as_of_date: string | null;
  metrics: Record<string, RelativeStrengthHorizon>;
  data_freshness: DataFreshness;
}

export interface ApiErrorBody {
  detail: string;
}

// Mirrors apps/api/routes/fundamentals.py, market.py, scoring.py response models.

export interface RawFundamentals {
  period_end: string | null;
  period_type: string | null;
  revenue: number | null;
  ebitda: number | null;
  ebit: number | null;
  pat: number | null;
  eps: number | null;
  operating_cash_flow: number | null;
  free_cash_flow: number | null;
  total_assets: number | null;
  total_liabilities: number | null;
  total_debt: number | null;
  cash: number | null;
  equity: number | null;
  shares_outstanding: number | null;
  dividend_yield: number | null;
  // Added for the Fundamental Score's Leverage sub-score (SCORING.md).
  // `current_assets`/`current_liabilities` are `null` for banks
  // specifically (no current/non-current balance-sheet split) and for
  // any instrument where neither provider had the field - see
  // DATA_SOURCES.md.
  interest_expense: number | null;
  current_assets: number | null;
  current_liabilities: number | null;
  source: string | null;
  source_timestamp: string | null;
  data_age_days: number | null;
}

export interface DerivedMetrics {
  revenue_growth_yoy: number | null;
  ebitda_growth_yoy: number | null;
  pat_growth_yoy: number | null;
  eps_growth_yoy: number | null;
  roe: number | null;
  roce_simplified: number | null;
  debt_to_equity: number | null;
  net_debt_to_ebitda: number | null;
  operating_margin: number | null;
  fcf_margin: number | null;
  // New derived metrics (SCORING.md "Fundamental Score"). `financial_leverage`
  // and `peg_ratio` are exposed for transparency only - not part of the score.
  roa: number | null;
  net_profit_margin: number | null;
  asset_turnover: number | null;
  financial_leverage: number | null;
  interest_coverage: number | null;
  current_ratio: number | null;
  peg_ratio: number | null;
}

export interface FundamentalSubScores {
  growth: number | null;
  profitability: number | null;
  leverage: number | null;
  efficiency: number | null;
}

export interface FundamentalScore {
  overall: number | null;
  band: string | null;
  sub_scores: FundamentalSubScores;
  methodology_version: string;
}

export interface ValuationMetrics {
  pe: number | null;
  pb: number | null;
  ev_ebitda: number | null;
  ev_sales: number | null;
  dividend_yield: number | null;
  fcf_yield: number | null;
  market_cap: number | null;
  enterprise_value: number | null;
  data_age_days: number | null;
  stale: boolean;
}

export interface QuarterlyPoint {
  period_end: string;
  revenue: number | null;
  pat: number | null;
  revenue_growth_yoy: number | null;
  pat_growth_yoy: number | null;
}

export interface QuarterlyFundamentals {
  points: QuarterlyPoint[];
  quarters_available: number;
  revenue_at_all_time_high: boolean | null;
  pat_at_all_time_high: boolean | null;
  latest_period_end: string | null;
  source: string | null;
  data_age_days: number | null;
}

export interface FundamentalsResponse {
  symbol: string;
  exchange: string;
  as_of: string;
  has_fundamental_data: boolean;
  message: string | null;
  raw: RawFundamentals;
  derived: DerivedMetrics;
  valuation: ValuationMetrics;
  fundamental_score: FundamentalScore;
  quarterly: QuarterlyFundamentals | null;
}

export interface MarketRegimeResponse {
  date: string;
  regime: string;
  nifty_close: number;
  nifty_vs_200dma_pct: number | null;
  breadth_above_50dma_pct: number | null;
  breadth_above_200dma_pct: number | null;
  rolling_volatility_pct: number | null;
  rule_version: string;
  breadth_universe: string;
  computed_at: string;
}

export interface ScoreComponent {
  name: string;
  weight: number;
  weight_used: number;
  score: number | null;
  contribution: number;
  available: boolean;
  reason: string | null;
  evidence: string[];
}

export type BullBearStrength = "strong" | "moderate" | "mild";

export interface BullBearEntry {
  evidence_id: string;
  metric_name: string;
  interpretation: string;
  magnitude: number;
  strength: BullBearStrength;
}

export interface ScoreResponse {
  instrument_id: string;
  symbol: string;
  exchange: string;
  as_of_date: string;
  computed_at: string;
  score: number | null;
  confidence: number;
  band: string | null;
  methodology_version: string;
  components: ScoreComponent[];
  bull_case: BullBearEntry[];
  bear_case: BullBearEntry[];
  cache_hit: boolean;
}

// Mirrors apps/api/routes/momentum.py / packages/momentum/service.py::MomentumScanResponse.

export interface MomentumCondition {
  name: string;
  passed: boolean;
  value: number;
  threshold: number;
  description: string;
}

export interface MomentumScanResponse {
  instrument_id: string;
  symbol: string;
  exchange: string;
  scan_date: string | null;
  evaluable: boolean;
  passed: boolean | null;
  conditions: MomentumCondition[];
  distance_from_52w_high_pct: number | null;
  rs_rank: number | null;
  rs_rank_universe: string;
  sma200_trend_lookback_days: number;
  methodology_version: string;
  computed_at: string;
  reason: string | null;
  cache_hit: boolean;
}

export interface EvidenceItem {
  id: string;
  evidence_type: string;
  metric_name: string;
  value_numeric: number | null;
  value_text: string | null;
  unit: string | null;
  observed_at: string;
  published_at: string | null;
  source_name: string;
  source_reference: string | null;
  source_timestamp: string;
  methodology_version: string;
  confidence: number | null;
  created_at: string;
}

export interface EvidenceListResponse {
  symbol: string;
  exchange: string;
  count: number;
  capped_at: number;
  items: EvidenceItem[];
}

// Mirrors apps/api/routes/analyst.py::AnalystRatingResponse.
export interface AnalystRatingResponse {
  symbol: string;
  exchange: string;
  has_coverage: boolean;
  target_mean_price: number | null;
  target_high_price: number | null;
  target_low_price: number | null;
  target_median_price: number | null;
  current_price: number | null;
  upside_pct: number | null;
  recommendation_mean: number | null;
  recommendation_key: string | null;
  number_of_analyst_opinions: number | null;
  source: string | null;
  source_timestamp: string | null;
  data_age_days: number | null;
  reason: string | null;
  cache_hit: boolean;
}

// Mirrors apps/api/routes/market.py::ScoreDistributionResponse.
export interface ScoreBandCount {
  band: string;
  count: number;
}

export interface ScoreDistributionResponse {
  as_of: string;
  universe_size: number;
  unscored_count: number;
  bands: ScoreBandCount[];
}

// Mirrors apps/api/routes/market.py::SectorsResponse.
export interface SectorSummary {
  sector: string;
  instrument_count: number;
  avg_score: number | null;
  avg_day_change_pct: number | null;
  momentum_pass_count: number;
}

export interface SectorsResponse {
  as_of: string;
  sectors: SectorSummary[];
}

export const COMPONENT_LABELS: Record<string, string> = {
  technical_structure: "Technical Structure",
  momentum: "Momentum",
  fundamentals: "Fundamentals",
  valuation: "Valuation",
  sector_relative_strength: "Sector Relative Strength",
  market_regime: "Market Regime",
  risk_quality: "Risk Quality",
};
