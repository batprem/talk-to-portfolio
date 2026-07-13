from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app import chat, frontier
from app.schemas import (
    AssetStats,
    ChatRequest,
    ChatResponse,
    FrontierRequest,
    FrontierResponse,
    PortfolioPoint,
    Verification,
)

app = FastAPI(title="Efficient Frontier API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/frontier", response_model=FrontierResponse)
def compute_frontier(request: FrontierRequest) -> FrontierResponse:
    try:
        result = frontier.run(
            source=request.source,
            tickers=request.tickers,
            csv_path=request.csv_path,
            period=request.period,
            rf=request.rf,
            n_portfolios=request.n_portfolios,
            seed=request.seed,
            weight_cap=request.weight_cap,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Offline dataset not found: {exc}") from exc

    tickers = result["stats"]["tickers"]
    normalized_request = request.model_copy(update={"tickers": tickers})
    return FrontierResponse(
        inputs=normalized_request,
        source_used=result["source_used"],
        assets=tickers,
        asset_stats=_asset_stats(result),
        portfolio_cloud=_portfolio_points(result["sim"], tickers),
        optima={name: _row_point(row, tickers) for name, row in result["optima"].items()},
        frontier_curve=_portfolio_points(result["curve"], tickers),
        verification=_verification(result, tickers),
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    available, status_message = chat.codex_status()
    if not available:
        return ChatResponse(
            available=False,
            status="unavailable",
            action="answer",
            reply=status_message,
            updates={},
        )

    if isinstance(request.frontier_context, str) and request.frontier_context.strip():
        context = request.frontier_context
    elif isinstance(request.frontier_context, dict):
        context = _jsonish_context(request.frontier_context)
    else:
        context = "No portfolio context was supplied."

    try:
        result = await run_in_threadpool(
            chat.run_codex_chat,
            context=context,
            question=request.message,
            history=[item.model_dump() for item in request.history],
        )
    except Exception as exc:  # noqa: BLE001 - chat must not break the app.
        return ChatResponse(
            available=True,
            status="error",
            action="answer",
            reply=f"AI chat failed gracefully: {exc}",
            updates={},
        )

    return ChatResponse(
        available=True,
        status="ok",
        action=result["action"],
        reply=result["reply"],
        updates=result["updates"],
    )


def _safe_float(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _safe_date(value: Any) -> str | None:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value) if value is not None else None
    if pd.isna(timestamp):
        return None
    return timestamp.date().isoformat()


def _row_point(row: pd.Series, tickers: list[str]) -> PortfolioPoint:
    return PortfolioPoint(
        weights={ticker: _safe_float(row[ticker]) or 0.0 for ticker in tickers},
        return_=_safe_float(row["return"]),
        volatility=_safe_float(row["volatility"]),
        sharpe=_safe_float(row["sharpe"]),
    )


def _portfolio_points(frame: pd.DataFrame, tickers: list[str]) -> list[PortfolioPoint]:
    if frame.empty:
        return []
    return [_row_point(row, tickers) for _, row in frame.iterrows()]


def _asset_stats(result: dict[str, Any]) -> dict[str, AssetStats]:
    stats = result["stats"]
    sharpe = result["asset_sharpe"]
    return {
        ticker: AssetStats(
            return_=_safe_float(stats["ann_return"][ticker]),
            volatility=_safe_float(stats["ann_vol"][ticker]),
            sharpe=_safe_float(sharpe[ticker]),
            **_asset_price_metadata(result, ticker),
        )
        for ticker in stats["tickers"]
    }


def _asset_price_metadata(result: dict[str, Any], ticker: str) -> dict[str, Any]:
    prices = result["prices"]
    source_used = result["source_used"]
    price_source = "yahoo_finance" if source_used == "online" else "offline_csv"
    yahoo_finance_url = (
        f"https://finance.yahoo.com/quote/{quote(ticker, safe='')}"
        if source_used == "online"
        else None
    )

    if ticker not in prices:
        return {
            "latest_price": None,
            "latest_price_date": None,
            "first_price": None,
            "first_price_date": None,
            "price_source": price_source,
            "yahoo_finance_url": yahoo_finance_url,
        }

    valid_prices = prices[ticker].dropna()
    if valid_prices.empty:
        return {
            "latest_price": None,
            "latest_price_date": None,
            "first_price": None,
            "first_price_date": None,
            "price_source": price_source,
            "yahoo_finance_url": yahoo_finance_url,
        }

    first_date = valid_prices.index[0]
    latest_date = valid_prices.index[-1]
    return {
        "latest_price": _safe_float(valid_prices.iloc[-1]),
        "latest_price_date": _safe_date(latest_date),
        "first_price": _safe_float(valid_prices.iloc[0]),
        "first_price_date": _safe_date(first_date),
        "price_source": price_source,
        "yahoo_finance_url": yahoo_finance_url,
    }


def _verification(result: dict[str, Any], tickers: list[str]) -> Verification:
    min_variance = result["optima"]["min_variance"]
    max_sharpe = result["optima"]["max_sharpe"]
    best_single = _safe_float(result["asset_sharpe"].max())
    max_sharpe_value = _safe_float(max_sharpe["sharpe"])
    return Verification(
        min_variance_weight_sum=float(min_variance[tickers].sum()),
        max_sharpe_weight_sum=float(max_sharpe[tickers].sum()),
        best_single_asset_sharpe=best_single,
        max_sharpe_beats_best_single=(
            best_single is not None and max_sharpe_value is not None and max_sharpe_value > best_single
        ),
    )


def _jsonish_context(context: dict[str, Any]) -> str:
    lines = []
    for key, value in context.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
