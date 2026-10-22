// Mirrors apps/api/routes/instruments.py and apps/api/routes/stocks.py
// response models exactly. Keep these in sync with the Pydantic models -
// see docs/data_dictionary/technicals_api.md for the authoritative contract.

export type RangeKey = "1M" | "3M" | "6M" | "1Y" | "2Y" | "ALL";

export const RANGE_KEYS: RangeKey[] = ["1M", "3M", "6M", "1Y", "2Y", "ALL"];

export interface InstrumentSummary {
  symbol: string;
  exchange: string;
  company_name: string;
  logo_url?: string | null;
  sector: string | null;
  instrument_type: string;
  active: boolean;
  // Most recently *persisted* research_scores row (apps/worker/jobs.py ::
  // compute_all_scores_job) - null until that batch job has run for this
  // instrument, never computed live by this endpoint.
  score: number | null;
  confidence: number | null;
  band: string | null;
  fundamental_score: number | null;
  fundamental_band: string | null;
  is_multibagger: boolean | null;
  // Most recently persisted momentum_scans row at the default lookback
  // (apps/worker/jobs.py :: compute_all_momentum_scans_job) - null until
  // that batch job has run, or when the stock has insufficient history
  // to evaluate (never a fabricated true/false either way).
  momentum_pass: boolean | null;
  is_vcp_setup: boolean | null;
  is_52w_breakout?: boolean | null;
  distance_from_52w_high_pct: number | null;
  // Day-over-day % price change (apps/api/routes/instruments.py's
  // single window-function query) - null when an instrument has fewer
  // than two OHLCV bars ever ingested.
  day_change_pct: number | null;
  return_1w_pct: number | null;
  return_1m_pct: number | null;
  return_3m_pct: number | null;
  return_6m_pct: number | null;
  return_1y_pct: number | null;
  // Most recently persisted packages/analyst_estimates/ row.
  // `analyst_upside_pct` is computed server-side against this listing's
  // latest persisted close - null whenever the instrument has zero
  // analyst coverage (common for mid/small-cap NSE names).
  analyst_target_price: number | null;
  analyst_upside_pct: number | null;
  ml_forecast_5d_pct: number | null;
  analyst_recommendation: string | null;
  revenue_growth_yoy: number | null;
  pat_growth_yoy: number | null;
  tv_signal_1d?: string | null;
  tv_signal_1w?: string | null;
  tv_momentum_flag?: string | null;
  fii_current?: number | null;
  fii_change_qoq_pct?: number | null;
}

export type InstrumentSortKey =
  | "symbol"
  | "company_name"
  | "sector"
  | "score"
  | "fundamental_score"
  | "is_multibagger"
  | "momentum_pass"
  | "is_vcp_setup"
  | "distance_from_52w_high_pct"
  | "tv_momentum_flag"
  | "analyst_upside_pct"
  | "analyst_recommendation"
  | "ml_forecast_5d_pct"
  | "day_change_pct"
  | "return_1w_pct"
  | "return_1m_pct"
  | "return_3m_pct"
  | "return_6m_pct"
  | "return_1y_pct"
  | "revenue_growth_yoy"
  | "pat_growth_yoy"
  | "fii_current"
  | "fii_change_qoq_pct";
export type SortOrder = "asc" | "desc";

export interface SortCriterion {
  key: InstrumentSortKey;
  order: SortOrder;
}

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
  company_name?: string | null;
  logo_url?: string | null;
  sector?: string | null;
  industry?: string | null;
  description?: string | null;
  ai_summary?: string | null;
  key_points?: string | null;
  website_url?: string | null;
  range: RangeKey;
  start_date: string | null;
  end_date: string | null;
  bars: PriceBar[];
  data_freshness: DataFreshness;
  high_52w?: number | null;
  low_52w?: number | null;
  is_52w_breakout?: boolean;
  breakout_pct?: number | null;
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
  tv_signal_1d?: string | null;
  tv_signal_1w?: string | null;
  tv_momentum_flag?: string | null;
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
  market_cap_cr?: number | null;
  industry_pe?: number | null;
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
  is_vcp_setup?: boolean | null;
  vcp_reason?: string | null;
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
  is_vcp_setup?: boolean | null;
  vcp_reason?: string | null;
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

export interface PiotroskiTest {
  name: string;
  category: string;
  passed: boolean;
  value_display: string;
  description: string;
}

export interface PiotroskiResult {
  score: number;
  max_score: number;
  verdict: string;
  profitability_score: number;
  leverage_liquidity_score: number;
  operating_efficiency_score: number;
  tests: PiotroskiTest[];
}

export interface AltmanZResult {
  z_score: number | null;
  zone: string;
  description: string;
}

export interface BeneishMResult {
  m_score: number | null;
  zone: string;
  description: string;
}

export interface EarningsQualityResult {
  cfo_to_pat: number | null;
  cfo_to_pat_verdict: string;
  cash_conversion_cycle_days: number | null;
  debtor_days: number | null;
  debtor_days_yoy_change: number | null;
  inventory_days: number | null;
  free_cash_flow_latest: number | null;
}

export interface DuPontResult {
  roe_pct: number | null;
  net_profit_margin_pct: number | null;
  asset_turnover: number | null;
  financial_leverage: number | null;
  primary_driver: string;
}

export interface ForensicFlag {
  code: string;
  severity: string;
  title: string;
  detail: string;
}

export interface ForensicShieldResult {
  red_flags_count: number;
  is_clean: boolean;
  verdict: string;
  flags: ForensicFlag[];
}

export interface FinancialHealthResult {
  has_data: boolean;
  fiscal_year_latest: string | null;
  fiscal_year_previous: string | null;
  piotroski: PiotroskiResult | null;
  altman_z: AltmanZResult | null;
  beneish_m?: BeneishMResult | null;
  earnings_quality: EarningsQualityResult | null;
  dupont: DuPontResult | null;
  forensic_shield: ForensicShieldResult | null;
}

export interface ShareholdingQuarter {
  quarter: string;
  promoter: number | null;
  fii: number | null;
  dii: number | null;
  public: number | null;
  government: number | null;
  shareholders_count: number | null;
}

export interface ShareholdingFlowResult {
  has_data: boolean;
  latest_quarter: string | null;
  fii_current: number | null;
  fii_qoq_change: number | null;
  fii_yoy_change: number | null;
  dii_current: number | null;
  dii_qoq_change: number | null;
  dii_yoy_change: number | null;
  promoter_current: number | null;
  promoter_qoq_change: number | null;
  promoter_yoy_change: number | null;
  public_current: number | null;
  shareholders_count_current: number | null;
  shareholders_count_qoq_change: number | null;
  institutional_holding_current: number | null;
  institutional_holding_qoq_change: number | null;
  smart_money_verdict: string;
  smart_money_description: string;
  quarters_history: ShareholdingQuarter[];
}

export interface TechnicalHealthResult {
  has_data: boolean;
  current_price: number | null;
  ema_20: number | null;
  sma_50: number | null;
  sma_200: number | null;
  trend_alignment_grade: string;
  trend_summary: string;
  price_vs_20ema_pct: number | null;
  price_vs_50sma_pct: number | null;
  price_vs_200sma_pct: number | null;
  up_down_volume_ratio: number | null;
  volume_flow_verdict: string;
  accumulation_days_count_20d: number;
  is_volatility_squeeze: boolean;
  volatility_state: string;
  high_52w: number | null;
  low_52w: number | null;
  pct_from_52w_high: number | null;
  pct_from_52w_low: number | null;
  range_position_pct: number | null;
}

export interface StockDiagnosticResponse {
  symbol: string;
  company_name: string;
  financial_health: FinancialHealthResult;
  shareholding_flow: ShareholdingFlowResult;
  technical_health: TechnicalHealthResult;
}

export interface AiStatusResponse {
  connected: boolean;
  provider: string;
  location: string;
  model: string;
  models: string[];
  model_ready: boolean;
  error?: string;
}

export interface AiChatMessage {
  role: "user" | "assistant" | "model" | "system";
  content: string;
}

export interface AiChatRequest {
  message: string;
  symbol?: string;
  history?: AiChatMessage[];
  model?: string;
  temperature?: number;
}

export interface AiChatResponse {
  symbol: string | null;
  response: string;
  model: string;
  context_available: boolean;
  context_preview: string | null;
  raw_context: any | null;
}

export interface AiStockContextResponse {
  symbol: string;
  company_name: string;
  formatted_context: string;
  ground_truth: any;
}

export interface ForecastCallItem {
  symbol: string;
  company_name: string;
  pred_return_pct: number;
  act_return_pct: number;
  mape_pct: number;
}

export interface PrecisionTier {
  tier: string;
  label: string;
  count: number;
  pct: number;
  win_rate_pct: number;
}

export interface MlPerformanceResponse {
  as_of_date: string;
  horizon_days: number;
  evaluated_count: number;
  correct_count: number;
  incorrect_count: number;
  directional_win_rate_pct: number;
  avg_mape_pct: number;
  median_mape_pct: number;
  eval_start_date: string | null;
  eval_end_date: string | null;
  tiers: PrecisionTier[];
  top_bullish_calls: ForecastCallItem[];
  top_bearish_calls: ForecastCallItem[];
  pinpoint_calls: ForecastCallItem[];
}

export interface ChecklistCriterion {
  id: string;
  title: string;
  passed: boolean;
  summary: string;
  description: string;
  evidence: string;
  metrics: Record<string, any>;
}

export interface StockChecklistResult {
  instrument_id: string;
  symbol: string;
  company_name: string;
  logo_url?: string | null;
  sector: string | null;
  latest_close: number | null;
  conditions_met: number;
  total_conditions: number;
  quality_pct: number;
  quality_band: string;
  criteria: ChecklistCriterion[];
  roce: number | null;
  roe: number | null;
  debt_to_equity: number | null;
  revenue_growth_yoy: number | null;
  pat_growth_yoy: number | null;
  analyst_upside_pct: number | null;
  pe_percentile: number | null;
  momentum_pass: boolean | null;
}

export interface ChecklistSummaryResponse {
  as_of: string;
  total_evaluated: number;
  distribution: Record<string, number>;
  items: StockChecklistResult[];
}

export interface AiFactorMomentum {
  value_12_1_pct: number;
  stage2_passed?: boolean;
  reasoning: string;
}

export interface AiFactorValueEp {
  earnings_yield_pct: number;
  pe_ratio: number;
  reasoning: string;
}

export interface AiFactorQuality {
  roe_pct: number;
  roce_pct?: number;
  debt_to_equity: number;
  reasoning: string;
}

export interface AiFactorEarningsRevisions {
  analyst_upside_pct?: number | null;
  pat_growth_yoy_pct?: number;
  rev_growth_yoy_pct?: number;
  reasoning: string;
}

export interface AiAlphaPickSignals {
  momentum: AiFactorMomentum;
  value_ep: AiFactorValueEp;
  quality: AiFactorQuality;
  earnings_revisions: AiFactorEarningsRevisions;
}

export interface AiAlphaPickItem {
  rank: number;
  symbol: string;
  company_name: string;
  sector: string;
  current_price: number;
  conviction_tier: "EXCEPTIONAL" | "HIGH" | string;
  composite_alpha_score: number;
  alpha_thesis: string;
  signals: AiAlphaPickSignals;
  catalysts: string[];
  key_risks: string[];
  invalidation_level?: number | null;
}

export interface AiAlphaPicksResponse {
  generated_date: string;
  model_name: string;
  market_regime_context: string;
  total_candidates_analyzed: number;
  picks_count: number;
  picks: AiAlphaPickItem[];
}




