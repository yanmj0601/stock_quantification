from fastapi.testclient import TestClient

from evoquant.api import create_app
from evoquant.storage import SQLiteStore


def test_api_dashboard_strategy_backtest_and_risk_flow(tmp_path):
    client = TestClient(create_app(SQLiteStore(tmp_path / "state.db")))

    created = client.post(
        "/api/strategies",
        json={
            "name": "us_momentum_breakout",
            "market": "US",
            "asset_class": "equity",
            "template_id": "momentum",
            "parameters": {"lookback": 60},
        },
    )
    assert created.status_code == 201
    strategy_id = created.json()["id"]

    backtest = client.post(
        "/api/backtests",
        json={
            "strategy_id": strategy_id,
            "equity": [100000, 101000, 104000],
            "turnovers": [0.1, 0.2],
        },
    )
    assert backtest.status_code == 201
    assert backtest.json()["metrics"]["cagr"] > 0

    risk = client.get("/api/risk")
    assert risk.json()["live_enabled"] is False

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["strategy_count"] == 1
    assert dashboard.json()["risk"]["live_enabled"] is False


def test_healthz(tmp_path):
    client = TestClient(create_app(SQLiteStore(tmp_path / "state.db")))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_strategy_and_account_ids_return_404(tmp_path):
    client = TestClient(create_app(SQLiteStore(tmp_path / "state.db")))

    strategy = client.patch(
        "/api/strategies/missing/status",
        json={"status": "paper", "reason": "promote"},
    )
    order = client.post(
        "/api/paper/orders",
        json={
            "account_id": "missing",
            "symbol": "AAPL",
            "market": "US",
            "quantity": 1,
            "limit_price": 100,
        },
    )

    assert strategy.status_code == 404
    assert order.status_code == 404


def test_risk_cannot_enable_live_trading(tmp_path):
    client = TestClient(create_app(SQLiteStore(tmp_path / "state.db")))

    response = client.patch(
        "/api/risk",
        json={"mode": "paper-only", "reason": "v1 paper test", "live_enabled": True},
    )

    assert response.status_code == 400
    assert client.get("/api/risk").json()["live_enabled"] is False
