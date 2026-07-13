import type {
  ChatMessage,
  ChatRequest,
  ChatResponse,
  FrontierContext,
  FrontierInputs,
  FrontierResponse
} from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

export function sanitizeInputs(inputs: FrontierInputs): FrontierInputs {
  return {
    ...inputs,
    tickers: inputs.tickers
      .map((ticker) => ticker.trim().toUpperCase())
      .filter(Boolean),
    csv_path: inputs.csv_path.trim(),
    period: inputs.period.trim(),
    rf: Number(inputs.rf),
    n_portfolios: Math.max(
      1000,
      Math.min(20000, Math.round(Number(inputs.n_portfolios)))
    ),
    seed: Math.round(Number(inputs.seed)),
    weight_cap:
      inputs.weight_cap === null ||
      inputs.weight_cap === undefined ||
      Number.isNaN(Number(inputs.weight_cap))
        ? null
        : Number(inputs.weight_cap)
  };
}

export function buildFrontierPayload(inputs: FrontierInputs) {
  const sanitized = sanitizeInputs(inputs);

  return {
    source: sanitized.source,
    tickers: sanitized.tickers,
    csv_path: sanitized.csv_path,
    period: sanitized.period,
    rf: sanitized.rf,
    n_portfolios: sanitized.n_portfolios,
    seed: sanitized.seed,
    weight_cap: sanitized.weight_cap ?? null
  };
}

export function applyInputUpdates(
  current: FrontierInputs,
  updates: Partial<FrontierInputs> | undefined
): FrontierInputs {
  if (!updates) return current;

  const merged: FrontierInputs = {
    ...current,
    ...updates,
    tickers: Array.isArray(updates.tickers) ? updates.tickers : current.tickers
  };

  return sanitizeInputs(merged);
}

export async function postFrontier(
  inputs: FrontierInputs
): Promise<FrontierResponse> {
  const response = await fetch("/api/frontier", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(buildFrontierPayload(inputs))
  });

  if (!response.ok) {
    throw new Error(`Frontier request failed with ${response.status}`);
  }

  return (await response.json()) as FrontierResponse;
}

export function buildFrontierContext(
  frontier: FrontierResponse | null
): FrontierContext | null {
  if (!frontier) return null;

  return {
    source_used: frontier.source_used,
    assets: frontier.assets,
    optima: frontier.optima,
    verification: frontier.verification
  };
}

export async function postChat(
  message: string,
  inputs: FrontierInputs,
  frontier: FrontierResponse | null,
  history: ChatMessage[]
): Promise<ChatResponse> {
  const payload: ChatRequest = {
    message,
    inputs: buildFrontierPayload(inputs),
    frontier_context: buildFrontierContext(frontier),
    history
  };

  const response = await fetch("/api/chat", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    throw new Error(`Chat request failed with ${response.status}`);
  }

  return (await response.json()) as ChatResponse;
}
