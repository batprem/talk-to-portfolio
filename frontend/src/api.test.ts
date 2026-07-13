import { describe, expect, it } from "vitest";
import { applyInputUpdates, buildFrontierPayload } from "./api";
import type { FrontierInputs } from "./types";

const baseInputs: FrontierInputs = {
  source: "online",
  tickers: [" aapl ", "MSFT"],
  csv_path: " ./prices.csv ",
  period: " 3y ",
  rf: 0.04,
  n_portfolios: 2500.4,
  seed: 42.7,
  weight_cap: undefined
};

describe("frontier api helpers", () => {
  it("builds the backend frontier payload with sanitized values", () => {
    expect(buildFrontierPayload(baseInputs)).toEqual({
      source: "online",
      tickers: ["AAPL", "MSFT"],
      csv_path: "./prices.csv",
      period: "3y",
      rf: 0.04,
      n_portfolios: 2500,
      seed: 43,
      weight_cap: null
    });
  });

  it("applies chat updates without dropping unchanged fields", () => {
    expect(
      applyInputUpdates(baseInputs, {
        tickers: ["spy", "qqq"],
        weight_cap: 0.35
      })
    ).toMatchObject({
      source: "online",
      tickers: ["SPY", "QQQ"],
      csv_path: "./prices.csv",
      period: "3y",
      weight_cap: 0.35
    });
  });
});
