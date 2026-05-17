from fastapi.testclient import TestClient

from evoquant.api import create_app
from evoquant.storage import SQLiteStore


def _client(tmp_path, *, raise_server_exceptions=True):
    return TestClient(
        create_app(SQLiteStore(tmp_path / "state.db")),
        raise_server_exceptions=raise_server_exceptions,
    )


def _create_strategy(client: TestClient) -> dict:
    response = client.post(
        "/api/strategies",
        json={
            "name": "us_momentum_breakout",
            "market": "US",
            "asset_class": "equity",
            "template_id": "momentum",
            "parameters": {
                "lookback": 60,
                "risk": {"stop": 0.08},
                "markets": ["US"],
            },
        },
    )
    assert response.status_code == 201
    return response.json()


def test_api_dashboard_strategy_backtest_and_risk_flow(tmp_path):
    client = _client(tmp_path)

    strategy_id = _create_strategy(client)["id"]

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
    client = _client(tmp_path)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_browser_origins_receive_cors_headers(tmp_path):
    client = _client(tmp_path)

    for origin in (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ):
        response = client.get("/api/risk", headers={"Origin": origin})

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin

        preflight = client.options(
            "/api/risk",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == origin
        assert "PATCH" in preflight.headers["access-control-allow-methods"]


def test_missing_strategy_and_account_ids_return_404(tmp_path):
    client = _client(tmp_path)

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
    client = _client(tmp_path)

    response = client.patch(
        "/api/risk",
        json={"mode": "paper-only", "reason": "v1 paper test", "live_enabled": True},
    )

    assert response.status_code == 400
    assert client.get("/api/risk").json()["live_enabled"] is False


def test_invalid_backtest_equity_returns_client_error(tmp_path):
    client = _client(tmp_path, raise_server_exceptions=False)
    strategy_id = _create_strategy(client)["id"]

    response = client.post(
        "/api/backtests",
        json={"strategy_id": strategy_id, "equity": [100000], "turnovers": []},
    )

    assert response.status_code in {400, 422}
    assert response.status_code != 500


def test_invalid_evolution_max_candidates_returns_client_error(tmp_path):
    client = _client(tmp_path, raise_server_exceptions=False)

    response = client.post(
        "/api/evolution",
        json={
            "template_id": "momentum",
            "parameter_space": {"lookback": [20, 60]},
            "max_candidates": 0,
        },
    )

    assert response.status_code in {400, 422}
    assert response.status_code != 500


def test_list_strategies_returns_json_safe_values(tmp_path):
    client = _client(tmp_path)
    created = _create_strategy(client)

    response = client.get("/api/strategies")

    assert response.status_code == 200
    strategies = response.json()
    assert strategies == [
        {
            "id": created["id"],
            "name": "us_momentum_breakout",
            "market": "US",
            "asset_class": "equity",
            "template_id": "momentum",
            "parameters": {
                "lookback": 60,
                "risk": {"stop": 0.08},
                "markets": ["US"],
            },
            "status": "research",
            "version": 1,
            "metrics": {},
        }
    ]


def test_evolution_returns_json_safe_candidate_parameters(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/evolution",
        json={
            "template_id": "momentum",
            "parameter_space": {
                "lookback": [20],
                "risk": [{"stop": 0.08}],
                "markets": [["US", "CN"]],
            },
            "max_candidates": 1,
        },
    )

    assert response.status_code == 201
    candidates = response.json()["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["template_id"] == "momentum"
    assert candidates[0]["parameters"] == {
        "lookback": 20,
        "risk": {"stop": 0.08},
        "markets": ["US", "CN"],
    }


def test_paper_accounts_can_be_created_and_listed(tmp_path):
    client = _client(tmp_path)

    created = client.post(
        "/api/paper/accounts",
        json={"name": "paper-us", "starting_cash": 50000},
    )
    listed = client.get("/api/paper/accounts")

    assert created.status_code == 201
    assert created.json()["name"] == "paper-us"
    assert created.json()["cash"] == 50000.0
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": created.json()["id"],
            "name": "paper-us",
            "cash": 50000.0,
            "nav": 50000.0,
        }
    ]


def test_data_health_returns_json_summary(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/data-health")

    assert response.status_code == 200
    assert response.json() == {"dataset_count": 0}


def test_audit_events_return_events_after_strategy_mutations(tmp_path):
    client = _client(tmp_path)
    strategy_id = _create_strategy(client)["id"]

    backtest = client.post(
        "/api/backtests",
        json={
            "strategy_id": strategy_id,
            "equity": [100000, 101000, 104000],
            "turnovers": [0.1, 0.2],
        },
    )
    assert backtest.status_code == 201

    response = client.get("/api/audit-events")

    assert response.status_code == 200
    events = response.json()
    assert [event["event_type"] for event in events] == [
        "strategy.created",
        "strategy.metrics_recorded",
    ]
    assert events[0]["entity_id"] == strategy_id
    assert events[0]["payload"] == {"name": "us_momentum_breakout"}
    assert events[1]["entity_id"] == strategy_id
    assert "cagr" in events[1]["payload"]
