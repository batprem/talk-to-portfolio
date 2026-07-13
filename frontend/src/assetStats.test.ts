import { describe, expect, it } from "vitest";
import { normalizeAssetReferenceRows } from "./assetStats";
import type { FrontierResponse } from "./types";

describe("asset stat helpers", () => {
  it("normalizes reference prices from mapped asset stats", () => {
    const frontier = {
      asset_stats: {
        AAPL: {
          return: 0.1,
          latest_price: 220.12,
          latest_price_date: "2026-07-10",
          first_price: 190,
          first_price_date: "2025-07-10",
          price_source: "Yahoo Finance",
          yahoo_finance_url: "https://finance.yahoo.com/quote/AAPL"
        }
      }
    } as FrontierResponse;

    expect(normalizeAssetReferenceRows(frontier)).toEqual([
      {
        ticker: "AAPL",
        latestPrice: 220.12,
        latestPriceDate: "2026-07-10",
        firstPrice: 190,
        firstPriceDate: "2025-07-10",
        priceSource: "Yahoo Finance",
        yahooFinanceUrl: "https://finance.yahoo.com/quote/AAPL",
        hasPriceContext: true
      }
    ]);
  });

  it("uses array fallbacks and drops unsafe link protocols", () => {
    const frontier = {
      assets: ["PTT.BK"],
      asset_stats: [
        {
          return: 0.08,
          volatility: 0.2,
          yahoo_finance_url: "javascript:alert(1)"
        }
      ]
    } as FrontierResponse;

    expect(normalizeAssetReferenceRows(frontier)).toMatchObject([
      {
        ticker: "PTT.BK",
        yahooFinanceUrl: undefined,
        hasPriceContext: false
      }
    ]);
  });
});
