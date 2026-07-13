import type { FrontierResponse, NumericRecord } from "./types";

export interface AssetReferencePrice {
  ticker: string;
  latestPrice?: unknown;
  latestPriceDate?: string;
  firstPrice?: unknown;
  firstPriceDate?: string;
  priceSource?: string;
  yahooFinanceUrl?: string;
  hasPriceContext: boolean;
}

function textField(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function safeHttpUrl(value: unknown): string | undefined {
  const candidate = textField(value);
  if (!candidate) return undefined;

  try {
    const parsed = new URL(candidate);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? candidate
      : undefined;
  } catch {
    return undefined;
  }
}

function buildReferenceRow(
  record: NumericRecord,
  fallbackTicker: string
): AssetReferencePrice {
  const ticker =
    textField(record.ticker) ??
    textField(record.symbol) ??
    textField(record.asset) ??
    fallbackTicker;
  const latestPrice = record.latest_price;
  const firstPrice = record.first_price;
  const latestPriceDate = textField(record.latest_price_date);
  const firstPriceDate = textField(record.first_price_date);
  const priceSource = textField(record.price_source);
  const yahooFinanceUrl = safeHttpUrl(record.yahoo_finance_url);

  return {
    ticker,
    latestPrice,
    latestPriceDate,
    firstPrice,
    firstPriceDate,
    priceSource,
    yahooFinanceUrl,
    hasPriceContext:
      latestPrice !== undefined ||
      firstPrice !== undefined ||
      latestPriceDate !== undefined ||
      firstPriceDate !== undefined ||
      priceSource !== undefined ||
      yahooFinanceUrl !== undefined
  };
}

export function normalizeAssetReferenceRows(
  frontier: FrontierResponse | null
): AssetReferencePrice[] {
  if (!frontier?.asset_stats) return [];

  if (Array.isArray(frontier.asset_stats)) {
    return frontier.asset_stats.map((record, index) =>
      buildReferenceRow(
        record,
        frontier.assets?.[index] ?? `Asset ${index + 1}`
      )
    );
  }

  return Object.entries(frontier.asset_stats).map(([ticker, record]) =>
    buildReferenceRow(record as NumericRecord, ticker)
  );
}
