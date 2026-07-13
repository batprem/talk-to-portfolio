"""Efficient-frontier core computations.

This preserves the workshop skill's numerical method: daily-return annualized
statistics, Dirichlet Monte Carlo long-only portfolios, simulation-picked optima,
and an analytic two-asset curve. Online data fetches fall back to the local CSV.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 252
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_PATH = REPO_ROOT / "datasets" / "stock_prices.csv"


def load_prices(
    source: str,
    tickers: list[str],
    csv_path: str | Path = DEFAULT_CSV_PATH,
    period: str = "5y",
) -> tuple[pd.DataFrame, str]:
    """Return wide price data and the source actually used."""
    csv_path = _resolve_csv_path(csv_path)
    source_used = source
    if source == "online":
        try:
            import yfinance as yf

            raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)
            prices = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
            prices = prices.dropna(how="all")
            if prices.empty:
                raise ValueError("yfinance returned no data")
            if isinstance(prices, pd.Series):
                prices = prices.to_frame(name=tickers[0] if tickers else "Close")
            return prices, "online"
        except Exception as exc:  # noqa: BLE001 - offline fallback is intentional.
            print(f"[frontier] online fetch failed ({exc}); falling back to CSV")
            source_used = "offline"

    df = pd.read_csv(csv_path, parse_dates=["Date"])
    wide = df.pivot(index="Date", columns="Ticker", values="Close").sort_index()
    if tickers:
        keep = [ticker for ticker in tickers if ticker in wide.columns]
        if keep:
            wide = wide[keep]
    return wide, source_used


def _resolve_csv_path(csv_path: str | Path) -> Path:
    path = Path(csv_path)
    if path.is_absolute() or path.exists():
        return path
    repo_relative = REPO_ROOT / path
    if repo_relative.exists():
        return repo_relative
    return path


def compute_stats(prices: pd.DataFrame) -> dict[str, Any]:
    """Annualized per-asset return, covariance, volatility from daily prices."""
    prices = prices.dropna()
    if prices.shape[1] < 2:
        raise ValueError("At least two assets with price history are required.")
    daily = prices.pct_change().dropna()
    if daily.empty:
        raise ValueError("Price history is too short to compute returns.")

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


def per_asset_sharpe(stats: dict[str, Any], rf: float) -> pd.Series:
    return (stats["ann_return"] - rf) / stats["ann_vol"]


def simulate_portfolios(
    stats: dict[str, Any],
    n_portfolios: int = 5000,
    rf: float = 0.02,
    seed: int = 42,
    weight_cap: float | None = None,
) -> pd.DataFrame:
    """Simulate random long-only portfolios whose weights sum to 1."""
    rng = np.random.default_rng(seed)
    mu = stats["ann_return"].values
    cov = stats["ann_cov"].values
    n_assets = len(mu)

    if weight_cap is not None:
        floor = 1.0 / n_assets
        if weight_cap <= floor + 1e-9:
            raise ValueError(
                f"Weight cap {weight_cap:.0%} is too low for {n_assets} assets; "
                f"raise the cap above {floor:.0%} or add more assets."
            )

    rows = []
    attempts = 0
    max_attempts = n_portfolios * 50
    while len(rows) < n_portfolios and attempts < max_attempts:
        attempts += 1
        weights = rng.dirichlet(np.ones(n_assets))
        if weight_cap is not None and weights.max() > weight_cap:
            continue
        ret = float(weights @ mu)
        vol = float(np.sqrt(weights @ cov @ weights))
        sharpe = (ret - rf) / vol if vol > 0 else np.nan
        rows.append((*weights, ret, vol, sharpe))

    columns = list(stats["tickers"]) + ["return", "volatility", "sharpe"]
    return pd.DataFrame(rows, columns=columns)


def find_optima(sim: pd.DataFrame) -> dict[str, pd.Series]:
    """Pick the min-variance and max-Sharpe portfolios from the simulation."""
    if sim.empty:
        raise ValueError(
            "No portfolios satisfied the constraints; relax the weight cap, add "
            "assets, or increase the number of simulations."
        )
    return {
        "min_variance": sim.loc[sim["volatility"].idxmin()],
        "max_sharpe": sim.loc[sim["sharpe"].idxmax()],
    }


def two_asset_curve(stats: dict[str, Any], rf: float = 0.02, points: int = 100) -> pd.DataFrame:
    """Analytic frontier for exactly two assets."""
    if len(stats["tickers"]) != 2:
        return pd.DataFrame()
    mu = stats["ann_return"].values
    cov = stats["ann_cov"].values
    rows = []
    for w0 in np.linspace(0, 1, points):
        weights = np.array([w0, 1 - w0])
        ret = float(weights @ mu)
        vol = float(np.sqrt(weights @ cov @ weights))
        sharpe = (ret - rf) / vol if vol > 0 else np.nan
        rows.append((w0, 1 - w0, ret, vol, sharpe))
    return pd.DataFrame(
        rows,
        columns=[stats["tickers"][0], stats["tickers"][1], "return", "volatility", "sharpe"],
    )


def run(
    source: str,
    tickers: list[str],
    csv_path: str | Path = DEFAULT_CSV_PATH,
    period: str = "5y",
    rf: float = 0.02,
    n_portfolios: int = 5000,
    seed: int = 42,
    weight_cap: float | None = None,
) -> dict[str, Any]:
    """End-to-end efficient frontier calculation."""
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
