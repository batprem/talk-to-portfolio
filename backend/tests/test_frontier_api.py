import pandas as pd
from fastapi.testclient import TestClient

from app import frontier
from app.main import app


client = TestClient(app)


def test_frontier_offline_returns_json_safe_portfolio_cloud():
    response = client.post(
        "/api/frontier",
        json={
            "source": "offline",
            "tickers": ["ABC", "XYZ"],
            "n_portfolios": 1000,
            "seed": 7,
            "rf": 0.02,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_used"] == "offline"
    assert body["assets"] == ["ABC", "XYZ"]
    assert body["inputs"]["tickers"] == ["ABC", "XYZ"]
    assert len(body["portfolio_cloud"]) == 1000
    assert len(body["frontier_curve"]) == 100
    assert set(body["optima"]) == {"min_variance", "max_sharpe"}

    abc_stats = body["asset_stats"]["ABC"]
    assert abc_stats["return"] is not None
    assert abc_stats["volatility"] is not None
    assert abc_stats["sharpe"] is not None
    assert abc_stats["first_price"] == 100.0
    assert abc_stats["first_price_date"] == "2024-01-02"
    assert abc_stats["latest_price"] == 123.74
    assert abc_stats["latest_price_date"] == "2024-03-29"
    assert abc_stats["price_source"] == "offline_csv"
    assert abc_stats["yahoo_finance_url"] is None

    max_sharpe = body["optima"]["max_sharpe"]
    assert abs(sum(max_sharpe["weights"].values()) - 1.0) < 1e-9
    assert max_sharpe["return"] is not None
    assert max_sharpe["volatility"] is not None
    assert max_sharpe["sharpe"] is not None


def test_frontier_online_source_includes_yahoo_reference_url(monkeypatch):
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 10.5, 11.0, 11.8],
            "BBB": [20.0, 20.4, 20.1, 20.9],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
    )

    def fake_load_prices(source, tickers, csv_path, period):
        assert source == "online"
        return prices[tickers], "online"

    monkeypatch.setattr(frontier, "load_prices", fake_load_prices)

    response = client.post(
        "/api/frontier",
        json={
            "source": "online",
            "tickers": ["AAA", "BBB"],
            "n_portfolios": 1000,
            "seed": 7,
        },
    )

    assert response.status_code == 200
    stats = response.json()["asset_stats"]["AAA"]
    assert stats["first_price"] == 10.0
    assert stats["first_price_date"] == "2024-01-02"
    assert stats["latest_price"] == 11.8
    assert stats["latest_price_date"] == "2024-01-05"
    assert stats["price_source"] == "yahoo_finance"
    assert stats["yahoo_finance_url"] == "https://finance.yahoo.com/quote/AAA"


def test_frontier_rejects_infeasible_weight_cap():
    response = client.post(
        "/api/frontier",
        json={
            "source": "offline",
            "tickers": ["ABC", "XYZ"],
            "n_portfolios": 1000,
            "weight_cap": 0.5,
        },
    )

    assert response.status_code == 400
    assert "Weight cap" in response.json()["detail"]
