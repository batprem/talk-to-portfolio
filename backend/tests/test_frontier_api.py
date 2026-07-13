from fastapi.testclient import TestClient

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

    max_sharpe = body["optima"]["max_sharpe"]
    assert abs(sum(max_sharpe["weights"].values()) - 1.0) < 1e-9
    assert max_sharpe["return"] is not None
    assert max_sharpe["volatility"] is not None
    assert max_sharpe["sharpe"] is not None


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
