// Tipos do contrato definitivo em docs/API.md. Monetários e inteiros grandes chegam como string.

export type Lottery = 'megasena' | 'lotofacil' | 'quina';
export const LOTTERIES: readonly Lottery[] = ['megasena', 'lotofacil', 'quina'];
export type WindowLabel = '30' | '100' | '300' | '1000' | 'all';
export const WINDOWS: readonly WindowLabel[] = ['30', '100', '300', '1000', 'all'];

export interface Fraction {
  numerator: string;
  denominator: string;
}

export interface Health {
  status: 'ok' | 'degraded';
  database: 'up' | 'down';
}

export interface LotteryInfo {
  slug: Lottery;
  name: string;
  pool_size: number;
  draw_size: number;
  min_bet_size: number;
  max_bet_size: number;
  simple_price: string;
  price_source: string;
  price_checked_on: string;
  draw_count: number;
  last_contest: number | null;
  last_draw_date: string | null;
}

export interface DrawSummary {
  id: string;
  lottery_slug: Lottery;
  contest: number;
  draw_date: string;
  numbers: number[];
}

export interface DrawList {
  limit: number;
  offset: number;
  count: number;
  total: number;
  items: DrawSummary[];
}

export interface Prize {
  hits: number;
  winners: number;
  payout_amount: string;
}

export interface DrawDetail extends DrawSummary {
  prizes: Prize[];
  extra: {
    winner_locations: unknown;
    accumulated_main: string | null;
    total_collected: string | null;
    next_estimate: string | null;
    special_accumulated: string | null;
    observation: string | null;
  } | null;
  source_sha256: string;
  ingest_run_id: string;
}

export interface Collector {
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  next_attempt_at: string | null;
}

export interface IngestionLottery {
  lottery_slug: Lottery;
  name: string;
  draw_count: number;
  first_contest: number | null;
  last_contest: number | null;
  last_draw_date: string | null;
  gap_count: number;
  open_divergences: number;
  quarantined_rows: number;
  prize_tier_rows: number;
  collector: Collector | null;
}

export interface IngestionRun {
  id: string;
  lottery_slug: Lottery;
  status: string;
  started_at: string;
  completed_at: string | null;
  row_count: number | null;
  inserted_count: number | null;
  unchanged_count: number | null;
  prize_changed_count: number | null;
  divergent_count: number | null;
  quarantined_count: number | null;
  checkpoint_contest: number | null;
  adapter_version: string | null;
  source_sha256: string | null;
  error_message: string | null;
}

export interface Divergence {
  id: string;
  lottery_slug: Lottery;
  contest: number;
  status: 'open' | 'accepted' | 'rejected';
  previous_value: { draw_date: string; numbers: number[] };
  current_value: { draw_date: string; numbers: number[] };
  detected_at: string;
  resolution_note: string | null;
}

export interface QuarantineRow {
  id: string;
  lottery_slug: Lottery;
  contest: number | null;
  kind: 'draw' | 'prize';
  reason: string;
  source_line: number | null;
  created_at: string;
}

export interface Job {
  id: string;
  kind: 'ingest' | 'analyze' | 'experiment' | 'suggestion' | string;
  lottery_slug: Lottery | null;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  attempts: number;
  error: string | null;
  params: unknown;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ProbTier {
  hits: number;
  is_prize_tier: boolean;
  exact: Fraction;
  probability: number;
  one_in: number | null;
  at_least: Fraction;
  at_least_probability: number;
}

export interface TicketsJackpot {
  count: number;
  contests: number;
  probability: number;
  one_in: number | null;
  fraction?: Fraction;
  budget?: string | number;
  spent?: string | number;
}

export interface Probabilities {
  lottery: Lottery;
  bet_size: number;
  draw_size: number;
  pool_size: number;
  total_combinations: string;
  simple_games: string;
  simple_price: string;
  bet_cost: string;
  price_source: string;
  formula_version: string;
  tiers: ProbTier[];
  tickets_jackpot: TicketsJackpot | null;
  assumptions: string[];
}

export interface AnalysisRun {
  id: string;
  lottery_slug: Lottery;
  method: string;
  window_label: string;
  window_size: number | null;
  window_start_contest: number;
  window_end_contest: number;
  sample_size: number;
  code_version: string;
  seed: string | number | null;
  completed_at: string;
  params: Record<string, unknown>;
}

export interface WindowInfo {
  window_label: string;
  window_start_contest: number;
  window_end_contest: number;
  sample_size: number;
  completed_at: string;
}

export interface NumberStat {
  number: number;
  frequency: number;
  relative_frequency: number;
  expected_frequency: number;
  z_score: number;
  ci_low: number;
  ci_high: number;
  current_delay: number;
  max_delay: number;
  mean_gap: number | null;
}

export interface GofDist {
  values: number[];
  observed: number[];
  expected?: number[];
  gof?: { chi2: number; df: number; p_value: number };
  mean?: number;
  expected_mean?: number;
  note?: string;
}

export interface StatsDistributions {
  sum: {
    mean: number;
    median: number;
    std: number;
    variance: number;
    min: number;
    max: number;
    range: number;
    expected_mean: number;
    expected_variance: number;
    histogram: { edges: number[]; counts: number[] };
  };
  parity: { note?: string; evens_per_draw: GofDist };
  low_high: { note?: string; low_per_draw: GofDist };
  groups_of_ten: { range: [number, number]; mean_per_draw: number; expected_mean_per_draw: number }[];
  volante: {
    rows: number;
    columns: number;
    row_mean_per_draw: number[];
    column_mean_per_draw: number[];
    expected_row_mean: number;
    expected_column_mean: number;
  };
  consecutive: {
    pairs_per_draw_distribution: { values: number[]; observed: number[] };
    mean: number;
    expected_mean: number;
  };
  spacing?: Record<string, unknown>;
  repeated_from_previous: GofDist;
  appearance_gaps?: {
    bins: number[];
    observed: number[];
    expected_geometric: number[];
    mean: number;
    expected_mean: number;
    max: number;
    sample_size: number;
  };
}

export interface StatsMeta {
  sample_size: number;
  first_contest: number;
  last_contest: number;
  stats_version: string;
  seed: string | number | null;
  disclaimer: string;
  inference_available: boolean;
  combinations_available: boolean;
}

export interface Stats {
  analysis_run: AnalysisRun;
  numbers: NumberStat[];
  distributions: StatsDistributions;
  meta: StatsMeta;
  disclaimer: string;
}

export interface Inference {
  sample_size: number;
  chi_square_uniformity: {
    null_hypothesis: string;
    statistic: number;
    df: number;
    p_value_asymptotic: number;
    p_value_monte_carlo: number | null;
    limitation?: string;
  };
  entropy: {
    bits: number;
    max_bits: number;
    normalized: number;
    null_mean_bits: number;
    p_value_lower_tail: number;
    null_hypothesis?: string;
  };
  autocorrelation_lag1: {
    null_hypothesis: string;
    tests: number;
    significant_q05?: number;
    expected_false_positives_at_05?: number;
    max_abs_z: number;
    p_value_permutation_max_abs_z?: number;
    per_number: { number: number; z: number; p_value: number; q_value: number }[];
  };
  sum_ljung_box: { null_hypothesis: string; lags: number; acf: number[]; statistic: number; p_value: number };
  runs_test_sum?: { null_hypothesis: string; runs: number; expected_runs: number; z: number; p_value: number };
  window_stability?: { null_hypothesis: string; jsd_bits: number; p_value_permutation: number };
  change_point_sum?: {
    null_hypothesis: string;
    candidate_index: number;
    statistic: number;
    p_value_permutation: number;
    note?: string;
  };
}

export interface InferenceResponse {
  analysis_run: AnalysisRun;
  inference: Inference | null;
  available: boolean;
  disclaimer: string;
}

export interface ComboItem {
  combo_size: number;
  numbers: number[];
  observed: number;
  expected: number;
  lift: number;
  z_score: number;
  p_value: number;
  q_value: number;
  sample_size: number;
}

export interface ComboSizeMeta {
  tested: number;
  possible: number;
  expected_count: number;
  significant_q05: number;
  expected_false_positives_at_05: number;
}

export interface Combinations {
  analysis_run: AnalysisRun;
  size: number;
  order: 'over' | 'under';
  items: ComboItem[];
  meta: { sizes: Record<string, ComboSizeMeta> };
  note: string;
  disclaimer: string;
}

// ---- Modelos / experimentos / simulações / sugestões ----
export interface ModelInfo {
  name: string;
  label: string;
  family: 'baseline' | 'frequency' | 'delay' | 'ml';
  description: string;
  experimental: boolean;
  probabilistic: boolean;
  default: boolean;
}

export type ExperimentStatus = 'pending' | 'running' | 'succeeded' | 'failed';
export interface Progress {
  done: number;
  total: number;
  stage: string;
}

export interface ExperimentSummary {
  id: string;
  kind: 'backtest' | 'montecarlo';
  lottery_slug: Lottery;
  status: ExperimentStatus;
  models: string[];
  config: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: Progress | null;
  verdict_summary: string | null;
}

export type MetricVerdict =
  | 'worse_than_baseline'
  | 'indistinguishable'
  | 'better_not_significant'
  | 'better_significant_not_replicated'
  | 'better_replicated';

export interface ExperimentResult {
  model_name: string;
  metric_name: string;
  value: number | null;
  ci_low: number | null;
  ci_high: number | null;
  baseline_value: number | null;
  baseline_ci_low: number | null;
  baseline_ci_high: number | null;
  p_value: number | null;
  q_value: number | null;
  verdict: MetricVerdict | null;
  payload: Record<string, unknown> | null;
}

export type ConclusionVerdict = 'inconclusive' | 'no_evidence_of_advantage' | 'candidate_advantage_needs_replication';

export interface ExperimentDetail {
  experiment: {
    id: string;
    kind: 'backtest' | 'montecarlo';
    lottery_slug: Lottery;
    status: ExperimentStatus;
    config: Record<string, unknown>;
    seed: string | number | null;
    train_cutoff_contest: number | null;
    test_start_contest: number | null;
    test_end_contest: number | null;
    n_hypotheses: number | null;
    code_version: string | null;
    data_fingerprint: string | null;
    error: string | null;
    progress: Progress | null;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
  };
  results: ExperimentResult[];
  conclusion: { summary: string; verdict: ConclusionVerdict; limitations: string[] } | null;
  disclaimer: string;
}

export type BacktestRequest = {
  kind: 'backtest';
  lottery: Lottery;
  models?: string[];
  test_contests?: number;
  tickets_per_contest?: number;
  seeds?: number;
  baseline_replicates?: number;
  refit_every?: number;
  seed?: number;
};
export type MonteCarloRequest = {
  kind: 'montecarlo';
  lottery: Lottery;
  tickets_per_contest: number;
  contests: number;
  replicates: number;
  seed?: number;
};
export type ExperimentRequest = BacktestRequest | MonteCarloRequest;

export type Strategy = 'uniform_random' | 'diversity' | 'frequency_weighted' | 'delay_weighted';
export const STRATEGIES: readonly Strategy[] = ['uniform_random', 'diversity', 'frequency_weighted', 'delay_weighted'];

export interface SuggestionRequest {
  lottery: Lottery;
  strategy: Strategy;
  tickets?: number;
  budget?: number;
  seed?: number;
}

export interface SuggestionSummary {
  id: string;
  lottery_slug: Lottery;
  strategy: Strategy;
  status: ExperimentStatus;
  ticket_count: number | null;
  budget: string | number | null;
  created_at: string;
}

export interface SuggestionDetail {
  set: {
    id: string;
    lottery_slug: Lottery;
    strategy: Strategy;
    seed: string | number | null;
    status: ExperimentStatus;
    budget: string | number | null;
    ticket_count: number | null;
    based_on_contest: number | null;
    created_at: string;
    explanation: string | null;
    evidence: null | { experiment_id: string; model_name: string; verdict: string };
    jackpot_probability: { event: string; numerator: string; denominator: string; probability: number } | null;
    total_cost: string | number | null;
  };
  tickets: {
    position: number;
    numbers: number[];
    heuristic_score: number;
    score_interpretation: string;
    exact_jackpot_probability: Fraction;
    cost: string | number;
  }[];
  predictive_advantage_validated: boolean;
  illustrative_only: boolean;
  disclaimer: string;
}

export interface IngestionTrigger {
  job_id: string;
  status: string;
}
