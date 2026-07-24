export type Label = "win" | "loss" | "breakeven" | "invalid" | null;
export type Direction = "long" | "short";

export interface StrategySummary {
  name: string;
  root: string;
  version: number;
  signals: number;
  labeled: number;
  unlabeled: number;
  wins: number;
  losses: number;
  invalid: number;
  win_rate: number | null;
  long: number;
  short: number;
  pine_available?: boolean;
  metadata?: Record<string, unknown> | null;
}

export interface Dataset {
  id: number;
  symbol: string;
  interval: string;
  market_type: string;
  timezone: string;
  start_time: string;
  end_time: string;
  row_count: number;
  source: string;
  strategies: StrategySummary[];
}

export interface Signal {
  id: number;
  timestamp: string;
  direction: Direction;
  label: Label;
  notes: string;
  pnl_pct: number | null;
  bars_held: number | null;
  indicator_name: string;
}

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ReviewData {
  dataset: Dataset;
  indicator: string;
  summary: {
    total: number;
    labeled: number;
    unlabeled: number;
    wins: number;
    losses: number;
    invalid: number;
    selected_position: number;
  };
  selected: Signal;
  signals: Signal[];
  visible_signals: Signal[];
  candles: Candle[];
}

export interface AnalysisData {
  indicator_name: string;
  total_signals: number;
  remaining: number;
  invalid: number;
  decisive: number;
  overall: Stat;
  directions: { long: Stat; short: Stat };
  feature_comparison: FeatureComparison[];
  feature_profile: { feature: string; name: string; median: number; samples: number }[];
}

export interface Stat {
  samples: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface FeatureComparison {
  feature: string;
  name: string;
  win_median: number;
  loss_median: number;
  gap: number;
  importance: number;
  winner_tendency: string;
  loser_tendency: string;
}
