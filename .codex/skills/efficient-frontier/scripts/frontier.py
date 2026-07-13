"""Efficient-frontier core computations (numpy/pandas only, no scipy).

This module is intentionally dependency-light so it can run anywhere and be
imported by the Streamlit dashboard *or* called standalone to print numbers for
the Verify step. The teaching approach (per workshop Lab 3.2) is Monte-Carlo:
simulate many random long-only portfolios, then pick the min-variance and
max-Sharpe points from the cloud. That makes the "portfolio cloud + frontier
curve" idea visible rather than hiding it inside a solver.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

TRADING_DAYS = 252  # annualization factor for daily data


def load_prices(
    source: str,
    tickers: list[str],
    csv_path: str = "datasets/stock_prices.csv",
    period: str = "5y",
) -> tuple[pd.DataFrame, str]:
    """Return a wide price frame (index=Date, columns=tickers, values=Close).

    source="online"  -> yfinance download for `tickers` over `period`.
    source="offline" -> read the long-format CSV (Date,Ticker,Close) and pivot.

    Returns (prices, source_used). If online is requested but fails or returns
    nothing, this transparently falls back to offline so a blocked venue network
    never breaks the demo. `source_used` records what actually happened.
    """
    source_used = source
    if source == "online":
        try:
            import yfinance as yf

            raw = yf.download(
                tickers, period=period, auto_adjust=True, progress=False
            )
            # yfinance returns a column MultiIndex; grab the Close level.
            prices = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
            prices = prices.dropna(how="all")
            if prices.empty:
                raise ValueError("yfinance returned no data")
            return prices, "online"
        except Exception as exc:  # noqa: BLE001 - fall back on any failure
            print(f"[frontier] online fetch failed ({exc}); falling back to CSV")
            source_used = "offline"

    # Offline: long format Date,Ticker,Close -> wide.
    df = pd.read_csv(csv_path, parse_dates=["Date"])
    wide = df.pivot(index="Date", columns="Ticker", values="Close").sort_index()
    if tickers:
        keep = [t for t in tickers if t in wide.columns]
        if keep:
            wide = wide[keep]
    return wide, source_used


def compute_stats(prices: pd.DataFrame) -> dict:
    """Annualized per-asset return, covariance, volatility from daily prices."""
    prices = prices.dropna()
    daily = prices.pct_change().dropna()
    mean_daily = daily.mean()
    cov_daily = daily.cov()

    ann_return = mean_daily * TRADING_DAYS
    ann_cov = cov_daily * TRADING_DAYS
    ann_vol = daily.std() * np.sqrt(TRADING_DAYS)
    return {
        "tickers": list(prices.columns),
        "ann_return": ann_return,
        "ann_cov": ann_cov,
        "ann_vol": ann_vol,
        "daily": daily,
    }


def per_asset_sharpe(stats: dict, rf: float) -> pd.Series:
    return (stats["ann_return"] - rf) / stats["ann_vol"]


def simulate_portfolios(
    stats: dict,
    n_portfolios: int = 5000,
    rf: float = 0.02,
    seed: int = 42,
    weight_cap: float | None = None,
) -> pd.DataFrame:
    """Simulate random long-only portfolios (weights sum to 1).

    Dirichlet sampling gives even coverage of the simplex. `weight_cap` (e.g.
    0.4) optionally rejects portfolios that put more than that in one asset,
    which is a realistic concentration limit students can toggle.
    """
    rng = np.random.default_rng(seed)
    mu = stats["ann_return"].values
    cov = stats["ann_cov"].values
    n_assets = len(mu)

    # A long-only portfolio of n assets always has some weight >= 1/n (they sum to
    # 1), so a cap at or below 1/n is infeasible — every sample would be rejected,
    # leaving an empty result. Fail early with an actionable message instead.
    if weight_cap is not None:
        floor = 1.0 / n_assets
        if weight_cap <= floor + 1e-9:
            raise ValueError(
                f"Weight cap {weight_cap:.0%} is too low for {n_assets} assets — each "
                f"asset needs at least {floor:.0%} because weights must sum to 100%. "
                f"Raise the cap above {floor:.0%} or add more assets."
            )

    rows = []
    attempts = 0
    max_attempts = n_portfolios * 50
    while len(rows) < n_portfolios and attempts < max_attempts:
        attempts += 1
        w = rng.dirichlet(np.ones(n_assets))
        if weight_cap is not None and w.max() > weight_cap:
            continue
        ret = float(w @ mu)
        vol = float(np.sqrt(w @ cov @ w))
        sharpe = (ret - rf) / vol if vol > 0 else np.nan
        rows.append((*w, ret, vol, sharpe))

    cols = list(stats["tickers"]) + ["return", "volatility", "sharpe"]
    return pd.DataFrame(rows, columns=cols)


def find_optima(sim: pd.DataFrame) -> dict:
    """Pick the min-variance and max-Sharpe portfolios from the simulation."""
    if sim.empty:
        # Defensive: an infeasible cap is caught earlier, but never idxmin an empty
        # frame (it raises a cryptic "argmin of an empty sequence").
        raise ValueError(
            "No portfolios satisfied the constraints — try relaxing the weight cap, "
            "adding assets, or increasing the number of simulations."
        )
    min_var = sim.loc[sim["volatility"].idxmin()]
    max_sharpe = sim.loc[sim["sharpe"].idxmax()]
    return {"min_variance": min_var, "max_sharpe": max_sharpe}


def two_asset_curve(stats: dict, rf: float = 0.02, points: int = 100) -> pd.DataFrame:
    """Analytic frontier for exactly two assets: sweep asset-0 weight 0->1.

    For a 2-asset portfolio the frontier is a smooth curve, so plotting the
    sweep gives a cleaner line than the random cloud alone.
    """
    if len(stats["tickers"]) != 2:
        return pd.DataFrame()
    mu = stats["ann_return"].values
    cov = stats["ann_cov"].values
    rows = []
    for w0 in np.linspace(0, 1, points):
        w = np.array([w0, 1 - w0])
        ret = float(w @ mu)
        vol = float(np.sqrt(w @ cov @ w))
        sharpe = (ret - rf) / vol if vol > 0 else np.nan
        rows.append((w0, 1 - w0, ret, vol, sharpe))
    return pd.DataFrame(
        rows, columns=[stats["tickers"][0], stats["tickers"][1], "return", "volatility", "sharpe"]
    )


def run(
    source: str,
    tickers: list[str],
    csv_path: str = "datasets/stock_prices.csv",
    period: str = "5y",
    rf: float = 0.02,
    n_portfolios: int = 5000,
    seed: int = 42,
    weight_cap: float | None = None,
) -> dict:
    """End-to-end: load -> stats -> simulate -> optima. Returns everything the
    dashboard (or a print-only Verify run) needs."""
    prices, source_used = load_prices(source, tickers, csv_path, period)
    stats = compute_stats(prices)
    sim = simulate_portfolios(stats, n_portfolios, rf, seed, weight_cap)
    optima = find_optima(sim)
    return {
        "prices": prices,
        "source_used": source_used,
        "stats": stats,
        "sim": sim,
        "optima": optima,
        "asset_sharpe": per_asset_sharpe(stats, rf),
        "curve": two_asset_curve(stats, rf),
        "rf": rf,
    }


if __name__ == "__main__":
    # Standalone Verify run: prints the numbers without launching Streamlit.
    import argparse

    p = argparse.ArgumentParser(description="Efficient frontier (print-only)")
    p.add_argument("--source", default="offline", choices=["online", "offline"])
    p.add_argument("--tickers", default="ABC,XYZ")
    p.add_argument("--csv", default="datasets/stock_prices.csv")
    p.add_argument("--period", default="5y")
    p.add_argument("--rf", type=float, default=0.02)
    p.add_argument("--n", type=int, default=5000)
    args = p.parse_args()

    res = run(
        args.source,
        [t.strip() for t in args.tickers.split(",") if t.strip()],
        csv_path=args.csv,
        period=args.period,
        rf=args.rf,
        n_portfolios=args.n,
    )
    tickers = res["stats"]["tickers"]
    print(f"Data source used: {res['source_used']}  |  Assets: {tickers}  |  rf={args.rf:.1%}")
    print("\nPer-asset annualized:")
    summary = pd.DataFrame(
        {
            "return": res["stats"]["ann_return"],
            "volatility": res["stats"]["ann_vol"],
            "sharpe": res["asset_sharpe"],
        }
    )
    print(summary.round(4).to_string())

    for name, row in res["optima"].items():
        w = row[tickers]
        print(f"\n{name}:")
        print(f"  weights   : {dict(w.round(4))}  (sum={w.sum():.4f})")
        print(f"  return    : {row['return']:.4f}")
        print(f"  volatility: {row['volatility']:.4f}")
        print(f"  sharpe    : {row['sharpe']:.4f}")

    best_single = res["asset_sharpe"].max()
    ms = res["optima"]["max_sharpe"]["sharpe"]
    print(
        f"\nVerify: max-Sharpe portfolio Sharpe {ms:.4f} vs best single-asset "
        f"{best_single:.4f} -> {'HIGHER (diversification works)' if ms > best_single else 'not higher'}"
    )
