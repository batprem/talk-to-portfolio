import {
  BarChart3,
  Bot,
  CheckCircle2,
  Database,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  Upload,
  XCircle
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import {
  applyInputUpdates,
  buildFrontierPayload,
  postChat,
  postFrontier
} from "./api";
import type {
  ChatMessage,
  ChartPoint,
  FrontierInputs,
  FrontierResponse,
  NumericRecord
} from "./types";

const defaultInputs: FrontierInputs = {
  source: "online",
  tickers: ["PTT.BK", "CPALL.BK", "KBANK.BK", "ADVANC.BK"],
  csv_path: "datasets/stock_prices.csv",
  period: "5y",
  rf: 0.02,
  n_portfolios: 5000,
  seed: 42,
  weight_cap: null
};

const percentFormatter = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 2
});

const numberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 4
});

function finiteNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function pickNumber(record: NumericRecord, keys: string[]): number | undefined {
  for (const key of keys) {
    const value = finiteNumber(record[key]);
    if (value !== undefined) return value;
  }
  return undefined;
}

function normalizePoint(record: NumericRecord, label?: string): ChartPoint | null {
  const risk = pickNumber(record, [
    "risk",
    "volatility",
    "vol",
    "std",
    "stdev",
    "sigma"
  ]);
  const ret = pickNumber(record, [
    "return",
    "expected_return",
    "mean_return",
    "annual_return",
    "ret",
    "mu"
  ]);

  if (risk === undefined || ret === undefined) return null;

  return {
    risk,
    ret,
    sharpe: pickNumber(record, ["sharpe", "sharpe_ratio"]),
    label:
      label ??
      String(record.label ?? record.name ?? record.ticker ?? record.asset ?? ""),
    raw: record
  };
}

function normalizePoints(
  points: NumericRecord[] | undefined,
  labelPrefix: string
): ChartPoint[] {
  return (points ?? [])
    .map((point, index) => normalizePoint(point, `${labelPrefix} ${index + 1}`))
    .filter((point): point is ChartPoint => point !== null);
}

function getOptimaPoints(optima: FrontierResponse["optima"]): ChartPoint[] {
  if (!optima) return [];

  return Object.entries(optima)
    .map(([name, record]) => normalizePoint(record, name.replaceAll("_", " ")))
    .filter((point): point is ChartPoint => point !== null);
}

function getAssetPoints(frontier: FrontierResponse | null): ChartPoint[] {
  if (!frontier?.asset_stats) return [];

  if (Array.isArray(frontier.asset_stats)) {
    return frontier.asset_stats
      .map((record, index) =>
        normalizePoint(
          record,
          String(
            record.ticker ??
              record.symbol ??
              record.asset ??
              frontier.assets?.[index] ??
              `Asset ${index + 1}`
          )
        )
      )
      .filter((point): point is ChartPoint => point !== null);
  }

  return Object.entries(frontier.asset_stats)
    .map(([asset, record]) => normalizePoint(record as NumericRecord, asset))
    .filter((point): point is ChartPoint => point !== null);
}

function getWeights(record: NumericRecord | undefined): Record<string, number> {
  const rawWeights = record?.weights;
  if (!rawWeights || typeof rawWeights !== "object" || Array.isArray(rawWeights)) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(rawWeights as Record<string, unknown>)
      .map(([asset, value]) => [asset, finiteNumber(value)])
      .filter((entry): entry is [string, number] => entry[1] !== undefined)
  );
}

function formatValue(value: unknown): string {
  const numeric = finiteNumber(value);
  if (numeric !== undefined) {
    if (Math.abs(numeric) <= 1 && String(value).includes(".")) {
      return percentFormatter.format(numeric);
    }
    return numberFormatter.format(numeric);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined || value === "") return "None";
  return String(value);
}

function formatMetric(value: number | undefined, asPercent = false): string {
  if (value === undefined) return "n/a";
  return asPercent ? percentFormatter.format(value) : numberFormatter.format(value);
}

function shouldRecompute(responseAction?: string, hasUpdates?: boolean): boolean {
  const normalized = responseAction?.toLowerCase() ?? "";
  return Boolean(
    hasUpdates ||
      normalized.includes("update") ||
      normalized.includes("recompute") ||
      normalized.includes("rerun")
  );
}

function InputField({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function App() {
  const [inputs, setInputs] = useState<FrontierInputs>(defaultInputs);
  const [frontier, setFrontier] = useState<FrontierResponse | null>(null);
  const [isComputing, setIsComputing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "Ask for a change like cap every asset at 35%, compare a lower risk-free rate, or explain the current max-Sharpe mix."
    }
  ]);
  const [isChatting, setIsChatting] = useState(false);

  const selectedOptimum = useMemo(() => {
    const optima = frontier?.optima;
    if (!optima) return undefined;
    return (
      optima.max_sharpe ??
      optima.maxSharpe ??
      optima.tangency ??
      Object.values(optima)[0]
    );
  }, [frontier]);

  const runFrontier = async (nextInputs = inputs) => {
    setIsComputing(true);
    setError(null);
    try {
      const result = await postFrontier(nextInputs);
      setFrontier(result);
      return result;
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Unable to compute frontier";
      setError(message);
      throw caught;
    } finally {
      setIsComputing(false);
    }
  };

  const handleCompute = async (event?: FormEvent) => {
    event?.preventDefault();
    const sanitized = buildFrontierPayload(inputs);
    setInputs(sanitized);
    await runFrontier(sanitized);
  };

  const updateInput = <K extends keyof FrontierInputs>(
    key: K,
    value: FrontierInputs[K]
  ) => {
    setInputs((current) => ({ ...current, [key]: value }));
  };

  const handleChat = async (event: FormEvent) => {
    event.preventDefault();
    const message = chatInput.trim();
    if (!message || isChatting) return;

    const nextHistory: ChatMessage[] = [
      ...chatHistory,
      { role: "user", content: message }
    ];
    setChatHistory(nextHistory);
    setChatInput("");
    setIsChatting(true);
    setError(null);

    try {
      const response = await postChat(message, inputs, frontier, chatHistory);
      const reply =
        response.reply ??
        (response.status
          ? `Request completed with status: ${response.status}`
          : "Done.");
      const updatedHistory: ChatMessage[] = [
        ...nextHistory,
        { role: "assistant", content: reply }
      ];
      setChatHistory(updatedHistory);

      if (shouldRecompute(response.action, Boolean(response.updates))) {
        const nextInputs = applyInputUpdates(inputs, response.updates);
        setInputs(nextInputs);
        await runFrontier(nextInputs);
      }
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Unable to process chat";
      setError(message);
      setChatHistory((current) => [
        ...current,
        { role: "assistant", content: message }
      ]);
    } finally {
      setIsChatting(false);
    }
  };

  return (
    <main className="dashboard">
      <section className="topbar" aria-label="Dashboard summary">
        <div>
          <p className="eyebrow">Portfolio optimizer</p>
          <h1>Efficient Frontier Dashboard</h1>
        </div>
        <div className="status-pill">
          <Database size={16} />
          <span>{frontier?.source_used ?? inputs.source}</span>
        </div>
      </section>

      <section className="layout">
        <form className="panel controls-panel" onSubmit={handleCompute}>
          <div className="panel-heading">
            <SlidersHorizontal size={18} />
            <h2>Inputs</h2>
          </div>

          <div className="source-toggle" role="group" aria-label="Data source">
            <button
              type="button"
              className={inputs.source === "online" ? "active" : ""}
              onClick={() => updateInput("source", "online")}
            >
              <Sparkles size={16} />
              Online
            </button>
            <button
              type="button"
              className={inputs.source === "offline" ? "active" : ""}
              onClick={() => updateInput("source", "offline")}
            >
              <Upload size={16} />
              Offline CSV
            </button>
          </div>

          <InputField label="Tickers">
            <textarea
              value={inputs.tickers.join(", ")}
              onChange={(event) =>
                updateInput(
                  "tickers",
                  event.target.value
                    .split(/[,\n]/)
                    .map((ticker) => ticker.trim())
                    .filter(Boolean)
                )
              }
              rows={3}
              placeholder="PTT.BK, CPALL.BK, KBANK.BK, ADVANC.BK"
            />
          </InputField>

          <InputField label="CSV path">
            <input
              value={inputs.csv_path}
              onChange={(event) => updateInput("csv_path", event.target.value)}
              placeholder="datasets/stock_prices.csv"
            />
          </InputField>

          <div className="field-grid">
            <InputField label="Lookback">
              <input
                value={inputs.period}
                onChange={(event) => updateInput("period", event.target.value)}
                placeholder="5y"
              />
            </InputField>
            <InputField label="Risk-free rate">
              <input
                type="number"
                step="0.001"
                value={inputs.rf}
                onChange={(event) => updateInput("rf", Number(event.target.value))}
              />
            </InputField>
            <InputField label="Portfolios">
              <input
                type="number"
                min={1000}
                max={20000}
                step={1000}
                value={inputs.n_portfolios}
                onChange={(event) =>
                  updateInput("n_portfolios", Number(event.target.value))
                }
              />
            </InputField>
            <InputField label="Seed">
              <input
                type="number"
                step={1}
                value={inputs.seed}
                onChange={(event) => updateInput("seed", Number(event.target.value))}
              />
            </InputField>
          </div>

          <label className="check-row">
            <input
              type="checkbox"
              checked={inputs.weight_cap !== null && inputs.weight_cap !== undefined}
              onChange={(event) =>
                updateInput("weight_cap", event.target.checked ? 0.4 : null)
              }
            />
            <span>Apply max asset weight</span>
          </label>

          <InputField label="Weight cap">
            <input
              type="number"
              min={0.01}
              max={1}
              step={0.01}
              value={inputs.weight_cap ?? ""}
              onChange={(event) =>
                updateInput(
                  "weight_cap",
                  event.target.value === "" ? null : Number(event.target.value)
                )
              }
              placeholder="0.40"
            />
          </InputField>

          <button className="primary-action" disabled={isComputing} type="submit">
            {isComputing ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
            Compute frontier
          </button>
        </form>

        <section className="panel chart-panel">
          <div className="panel-heading">
            <BarChart3 size={18} />
            <h2>Risk / Return</h2>
          </div>
          <PortfolioChart frontier={frontier} isLoading={isComputing} />
          {error ? <p className="error-line">{error}</p> : null}
        </section>

        <MetricsPanel frontier={frontier} selectedOptimum={selectedOptimum} />
        <VerificationPanel frontier={frontier} />
        <ChatPanel
          chatInput={chatInput}
          history={chatHistory}
          isBusy={isChatting || isComputing}
          setChatInput={setChatInput}
          onSubmit={handleChat}
        />
      </section>
    </main>
  );
}

function PortfolioChart({
  frontier,
  isLoading
}: {
  frontier: FrontierResponse | null;
  isLoading: boolean;
}) {
  const cloud = normalizePoints(frontier?.portfolio_cloud, "Portfolio");
  const curve = normalizePoints(frontier?.frontier_curve, "Frontier");
  const optima = getOptimaPoints(frontier?.optima);
  const assets = getAssetPoints(frontier);
  const allPoints = [...cloud, ...curve, ...optima, ...assets];

  if (!frontier && !isLoading) {
    return (
      <div className="empty-state">
        <RefreshCw size={26} />
        <span>Run a frontier computation to populate the cloud.</span>
      </div>
    );
  }

  if (isLoading && allPoints.length === 0) {
    return (
      <div className="empty-state">
        <Loader2 className="spin" size={26} />
        <span>Computing portfolios...</span>
      </div>
    );
  }

  const xValues = allPoints.map((point) => point.risk);
  const yValues = allPoints.map((point) => point.ret);
  const minX = Math.min(...xValues);
  const maxX = Math.max(...xValues);
  const minY = Math.min(...yValues);
  const maxY = Math.max(...yValues);
  const padX = (maxX - minX || 0.1) * 0.08;
  const padY = (maxY - minY || 0.1) * 0.12;
  const bounds = {
    minX: minX - padX,
    maxX: maxX + padX,
    minY: minY - padY,
    maxY: maxY + padY
  };
  const width = 900;
  const height = 520;
  const margin = { top: 30, right: 32, bottom: 58, left: 70 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;

  const toX = (risk: number) =>
    margin.left +
    ((risk - bounds.minX) / (bounds.maxX - bounds.minX || 1)) * plotWidth;
  const toY = (ret: number) =>
    margin.top +
    (1 - (ret - bounds.minY) / (bounds.maxY - bounds.minY || 1)) * plotHeight;

  const curvePath = curve
    .sort((a, b) => a.risk - b.risk)
    .map((point) => `${toX(point.risk)},${toY(point.ret)}`)
    .join(" ");

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Portfolio risk return chart">
        <defs>
          <linearGradient id="frontierLine" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="#0f766e" />
            <stop offset="55%" stopColor="#2563eb" />
            <stop offset="100%" stopColor="#c2410c" />
          </linearGradient>
        </defs>

        {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
          const x = margin.left + tick * plotWidth;
          const y = margin.top + tick * plotHeight;
          return (
            <g key={tick}>
              <line
                x1={x}
                x2={x}
                y1={margin.top}
                y2={height - margin.bottom}
                className="grid-line"
              />
              <line
                x1={margin.left}
                x2={width - margin.right}
                y1={y}
                y2={y}
                className="grid-line"
              />
            </g>
          );
        })}

        <line
          x1={margin.left}
          x2={width - margin.right}
          y1={height - margin.bottom}
          y2={height - margin.bottom}
          className="axis-line"
        />
        <line
          x1={margin.left}
          x2={margin.left}
          y1={margin.top}
          y2={height - margin.bottom}
          className="axis-line"
        />

        {cloud.map((point, index) => (
          <circle
            key={`${point.risk}-${point.ret}-${index}`}
            cx={toX(point.risk)}
            cy={toY(point.ret)}
            r={2.6}
            className="cloud-point"
          >
            <title>
              {`${point.label}: risk ${formatMetric(point.risk, true)}, return ${formatMetric(
                point.ret,
                true
              )}, Sharpe ${formatMetric(point.sharpe)}`}
            </title>
          </circle>
        ))}

        {curvePath ? (
          <polyline points={curvePath} className="frontier-line" />
        ) : null}

        {assets.map((point) => (
          <g key={`asset-${point.label}`}>
            <circle
              cx={toX(point.risk)}
              cy={toY(point.ret)}
              r={6}
              className="asset-point"
            />
            <text
              x={toX(point.risk) + 9}
              y={toY(point.ret) - 8}
              className="point-label"
            >
              {point.label}
            </text>
          </g>
        ))}

        {optima.map((point) => (
          <g key={`optimum-${point.label}`}>
            <path
              d={`M ${toX(point.risk)} ${toY(point.ret) - 9} L ${
                toX(point.risk) + 8
              } ${toY(point.ret) + 7} L ${toX(point.risk) - 8} ${
                toY(point.ret) + 7
              } Z`}
              className="optimum-point"
            />
            <text
              x={toX(point.risk) + 12}
              y={toY(point.ret) + 4}
              className="point-label optimum-label"
            >
              {point.label}
            </text>
          </g>
        ))}

        <text x={width / 2} y={height - 18} className="axis-label">
          Volatility
        </text>
        <text
          x={20}
          y={height / 2}
          className="axis-label"
          transform={`rotate(-90 20 ${height / 2})`}
        >
          Expected return
        </text>
      </svg>
      <div className="legend">
        <span><i className="dot cloud" /> Simulated portfolios</span>
        <span><i className="line-swatch" /> Frontier</span>
        <span><i className="dot asset" /> Assets</span>
        <span><i className="triangle-swatch" /> Optima</span>
      </div>
    </div>
  );
}

function MetricsPanel({
  frontier,
  selectedOptimum
}: {
  frontier: FrontierResponse | null;
  selectedOptimum: NumericRecord | undefined;
}) {
  const optimumPoint = selectedOptimum
    ? normalizePoint(selectedOptimum, "Selected optimum")
    : null;
  const weights = getWeights(selectedOptimum);
  const sortedWeights = Object.entries(weights).sort((a, b) => b[1] - a[1]);

  return (
    <section className="panel metrics-panel">
      <div className="panel-heading">
        <Sparkles size={18} />
        <h2>Metrics & Weights</h2>
      </div>

      <div className="metric-strip">
        <div>
          <span>Return</span>
          <strong>{formatMetric(optimumPoint?.ret, true)}</strong>
        </div>
        <div>
          <span>Volatility</span>
          <strong>{formatMetric(optimumPoint?.risk, true)}</strong>
        </div>
        <div>
          <span>Sharpe</span>
          <strong>{formatMetric(optimumPoint?.sharpe)}</strong>
        </div>
      </div>

      <div className="weights-list">
        {sortedWeights.length > 0 ? (
          sortedWeights.map(([asset, weight]) => (
            <div className="weight-row" key={asset}>
              <div>
                <span>{asset}</span>
                <strong>{percentFormatter.format(weight)}</strong>
              </div>
              <div className="weight-track">
                <span style={{ width: `${Math.min(100, Math.max(0, weight * 100))}%` }} />
              </div>
            </div>
          ))
        ) : (
          <p className="muted">
            {frontier
              ? "No optimum weights were returned by the backend."
              : "Weights appear after a computation."}
          </p>
        )}
      </div>
    </section>
  );
}

function VerificationPanel({ frontier }: { frontier: FrontierResponse | null }) {
  const entries = Array.isArray(frontier?.verification)
    ? frontier.verification.map((value, index) => [`Check ${index + 1}`, value] as const)
    : Object.entries(frontier?.verification ?? {});

  return (
    <section className="panel verification-panel">
      <div className="panel-heading">
        <CheckCircle2 size={18} />
        <h2>Verification</h2>
      </div>

      <div className="verification-list">
        {entries.length > 0 ? (
          entries.map(([key, value]) => {
            const isFailure =
              value === false ||
              (typeof value === "string" && /fail|error|invalid/i.test(value));
            return (
              <div className="verification-row" key={key}>
                {isFailure ? <XCircle size={17} /> : <CheckCircle2 size={17} />}
                <span>{key.replaceAll("_", " ")}</span>
                <strong>{formatValue(value)}</strong>
              </div>
            );
          })
        ) : (
          <p className="muted">Backend verification details will appear here.</p>
        )}
      </div>
    </section>
  );
}

function ChatPanel({
  chatInput,
  history,
  isBusy,
  setChatInput,
  onSubmit
}: {
  chatInput: string;
  history: ChatMessage[];
  isBusy: boolean;
  setChatInput: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <section className="panel chat-panel">
      <div className="panel-heading">
        <Bot size={18} />
        <h2>Chat</h2>
      </div>

      <div className="chat-log" aria-live="polite">
        {history.map((message, index) => (
          <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
            <span>{message.content}</span>
          </div>
        ))}
      </div>

      <form className="chat-form" onSubmit={onSubmit}>
        <input
          value={chatInput}
          onChange={(event) => setChatInput(event.target.value)}
          placeholder="Ask for an explanation or parameter change"
          disabled={isBusy}
        />
        <button type="submit" disabled={isBusy || !chatInput.trim()} aria-label="Send chat message">
          {isBusy ? <Loader2 className="spin" size={18} /> : <MessageSquare size={18} />}
        </button>
      </form>
    </section>
  );
}

export default App;
