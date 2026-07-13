export type DataSource = "online" | "offline";

export interface FrontierInputs {
  source: DataSource;
  tickers: string[];
  csv_path: string;
  period: string;
  rf: number;
  n_portfolios: number;
  seed: number;
  weight_cap?: number | null;
}

export type NumericRecord = Record<string, unknown>;

export interface FrontierResponse {
  inputs?: Partial<FrontierInputs>;
  source_used?: string;
  assets?: string[];
  asset_stats?: Record<string, NumericRecord> | NumericRecord[];
  portfolio_cloud?: NumericRecord[];
  frontier_curve?: NumericRecord[];
  optima?: Record<string, NumericRecord>;
  verification?: Record<string, unknown> | unknown[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  message: string;
  inputs: FrontierInputs;
  frontier_context: FrontierContext | null;
  history: ChatMessage[];
}

export interface FrontierContext {
  source_used?: string;
  assets?: string[];
  optima?: FrontierResponse["optima"];
  verification?: FrontierResponse["verification"];
}

export interface ChatResponse {
  action?: "answer" | "update" | "recompute" | string;
  reply?: string;
  updates?: Partial<FrontierInputs>;
  status?: string;
}

export interface ChartPoint {
  risk: number;
  ret: number;
  sharpe?: number;
  label?: string;
  raw: NumericRecord;
}
