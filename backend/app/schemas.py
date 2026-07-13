from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FrontierRequest(BaseModel):
    source: Literal["online", "offline"] = "online"
    tickers: list[str] = Field(
        default_factory=lambda: ["PTT.BK", "CPALL.BK", "KBANK.BK", "ADVANC.BK"],
        min_length=2,
        max_length=20,
    )
    csv_path: str = "datasets/stock_prices.csv"
    period: Literal["1y", "2y", "3y", "5y", "10y"] = "5y"
    rf: float = Field(0.02, ge=0.0, le=1.0)
    n_portfolios: int = Field(5000, ge=1000, le=20000)
    seed: int = 42
    weight_cap: float | None = Field(default=None, gt=0.0, le=1.0)

    @field_validator("tickers")
    @classmethod
    def clean_tickers(cls, value: list[str]) -> list[str]:
        cleaned = [ticker.strip().upper() for ticker in value if ticker.strip()]
        if len(cleaned) < 2:
            raise ValueError("At least two tickers are required.")
        return cleaned


class PortfolioPoint(BaseModel):
    weights: dict[str, float]
    return_: float | None = Field(serialization_alias="return", alias="return")
    volatility: float | None
    sharpe: float | None

    model_config = ConfigDict(populate_by_name=True)


class AssetStats(BaseModel):
    return_: float | None = Field(serialization_alias="return", alias="return")
    volatility: float | None
    sharpe: float | None
    latest_price: float | None
    latest_price_date: str | None
    first_price: float | None
    first_price_date: str | None
    price_source: str
    yahoo_finance_url: str | None

    model_config = ConfigDict(populate_by_name=True)


class Verification(BaseModel):
    min_variance_weight_sum: float
    max_sharpe_weight_sum: float
    best_single_asset_sharpe: float | None
    max_sharpe_beats_best_single: bool


class FrontierResponse(BaseModel):
    inputs: FrontierRequest
    source_used: Literal["online", "offline"]
    assets: list[str]
    asset_stats: dict[str, AssetStats]
    portfolio_cloud: list[PortfolioPoint]
    optima: dict[str, PortfolioPoint]
    frontier_curve: list[PortfolioPoint]
    verification: Verification


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    inputs: FrontierRequest | None = None
    frontier_context: str | dict[str, Any] | None = None
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    available: bool
    status: Literal["ok", "unavailable", "error"]
    action: Literal["answer", "update"]
    reply: str
    updates: dict[str, Any]
