from datetime import date

import pytest
from fastapi.testclient import TestClient

from evoquant.api import create_app
from evoquant.api import _default_provider_factory
from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument
from evoquant.storage import SQLiteStore


class ApiFakeProvider:
    name = "fake"

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        assert index_id == "SP500"
        return [
            ProviderInstrument(
                symbol="AAPL",
                market=Market.US,
                name="Apple",
                name_zh="苹果",
                exchange="NASDAQ",
                currency="USD",
                sector="Technology",
                index_membership="SP500",
                tradable=True,
                lot_size=1,
            )
        ]

    def sync_bars(self, symbols, market, start, end, timeframe="1d"):
        assert symbols == ["AAPL"]
        assert market is Market.US
        assert timeframe == "1d"
        assert start <= date(2026, 1, 2) <= end
        return [
            ProviderBar(
                symbol="AAPL",
                market=Market.US,
                session=date(2026, 1, 2),
                open=99,
                high=101,
                low=98,
                close=100,
                volume=1000,
                amount=100000,
                adjusted=True,
                suspended=False,
                limit_up=False,
                limit_down=False,
                source="fake",
            )
        ]


class LowCoverageApiFakeProvider:
    name = "fake"

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        assert index_id == "SP500"
        return [
            ProviderInstrument(
                symbol=symbol,
                market=Market.US,
                name=symbol,
                name_zh=symbol,
                exchange="NASDAQ",
                currency="USD",
                sector="Technology",
                index_membership="SP500",
                tradable=True,
                lot_size=1,
            )
            for symbol in ("AAPL", "MSFT")
        ]

    def sync_bars(self, symbols, market, start, end, timeframe="1d"):
        assert symbols == ["AAPL", "MSFT"]
        return [
            ProviderBar(
                symbol="AAPL",
                market=Market.US,
                session=date(2026, 1, 1),
                open=99,
                high=101,
                low=98,
                close=100,
                volume=1000,
                amount=100000,
                adjusted=True,
                suspended=False,
                limit_up=False,
                limit_down=False,
                source="fake",
            ),
            ProviderBar(
                symbol="AAPL",
                market=Market.US,
                session=date(2026, 1, 2),
                open=100,
                high=102,
                low=99,
                close=101,
                volume=1000,
                amount=101000,
                adjusted=True,
                suspended=False,
                limit_up=False,
                limit_down=False,
                source="fake",
            ),
        ]


def _client(tmp_path, *, raise_server_exceptions=True, provider_factory=None):
    return TestClient(
        create_app(SQLiteStore(tmp_path / "state.db"), provider_factory=provider_factory),
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


def test_default_us_provider_prefers_tiingo_when_api_key_is_configured(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "secret")
    monkeypatch.delenv("EVOQUANT_US_PROVIDER", raising=False)

    provider = _default_provider_factory(Market.US)

    assert provider.name == "tiingo"


def test_default_us_provider_can_force_tiingo_and_report_missing_key(monkeypatch):
    monkeypatch.setenv("EVOQUANT_US_PROVIDER", "tiingo")
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TIINGO_API_KEY"):
        _default_provider_factory(Market.US)


def test_browser_origins_receive_cors_headers(tmp_path):
    client = _client(tmp_path)

    for origin in (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:57818",
        "http://localhost:57818",
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
    assert set(candidates[0]) == {"id", "template_id", "parameters"}
    assert candidates[0]["parameters"] == {
        "lookback": 20,
        "risk": {"stop": 0.08},
        "markets": ["US", "CN"],
    }


def test_empty_collection_endpoints_return_empty_contracts(tmp_path):
    client = _client(tmp_path)

    assert client.get("/api/strategies").json() == []
    assert client.get("/api/audit-events").json() == []
    assert client.get("/api/paper/accounts").json() == []

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["strategy_count"] == 0
    assert dashboard.json()["strategies_by_status"] == {}
    assert dashboard.json()["paper_account_count"] == 0
    assert dashboard.json()["paper_total_nav"] == 0.0


def test_evolution_candidate_can_be_registered_as_research_strategy(tmp_path):
    client = _client(tmp_path)

    generated = client.post(
        "/api/evolution",
        json={
            "template_id": "momentum",
            "parameter_space": {
                "market": ["CN"],
                "lookback": [40],
                "stop": [0.06],
            },
            "max_candidates": 1,
        },
    )
    assert generated.status_code == 201
    candidate = generated.json()["candidates"][0]

    registered = client.post(
        "/api/strategies",
        json={
            "name": f"{candidate['template_id']}_{candidate['id']}",
            "market": candidate["parameters"]["market"],
            "asset_class": "equity",
            "template_id": candidate["template_id"],
            "parameters": candidate["parameters"],
        },
    )

    assert registered.status_code == 201
    strategy = registered.json()
    assert strategy["status"] == "research"
    assert strategy["template_id"] == "momentum"
    assert strategy["market"] == "CN"
    assert strategy["parameters"] == {
        "market": "CN",
        "lookback": 40,
        "stop": 0.06,
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


def test_paper_orders_fills_and_positions_can_be_listed(tmp_path):
    client = _client(tmp_path)
    account = client.post(
        "/api/paper/accounts",
        json={"name": "paper-us", "starting_cash": 50000},
    ).json()

    created = client.post(
        "/api/paper/orders",
        json={
            "account_id": account["id"],
            "symbol": "AAPL",
            "market": "US",
            "quantity": 10,
            "limit_price": 185,
        },
    )

    assert created.status_code == 201
    assert created.json()["status"] == "filled"

    orders = client.get("/api/paper/orders")
    fills = client.get("/api/paper/fills")
    positions = client.get(f"/api/paper/accounts/{account['id']}/positions")

    assert orders.status_code == 200
    assert fills.status_code == 200
    assert positions.status_code == 200
    assert orders.json() == [
        {
            "id": created.json()["id"],
            "account_id": account["id"],
            "symbol": "AAPL",
            "market": "US",
            "quantity": 10.0,
            "limit_price": 185.0,
            "status": "filled",
            "created_at": created.json()["created_at"],
        }
    ]
    assert fills.json()[0] == {
        "id": fills.json()[0]["id"],
        "order_id": created.json()["id"],
        "account_id": account["id"],
        "symbol": "AAPL",
        "market": "US",
        "quantity": 10.0,
        "fill_price": 185.0,
        "fee": 0.0,
        "created_at": fills.json()[0]["created_at"],
    }
    assert positions.json() == [
        {
            "account_id": account["id"],
            "symbol": "AAPL",
            "market": "US",
            "quantity": 10.0,
            "average_cost": 185.0,
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


def test_signal_scan_api_returns_snapshot(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/signals/scans",
        json={
            "strategy_template": "cross_sectional_momentum",
            "markets": ["US"],
            "parameters": {
                "top_n": 1,
                "exit_rank": 2,
                "lookback_long": 120,
                "lookback_short": 20,
                "max_weight": 0.08,
                "min_amount": 1000,
                "max_volatility": 10,
                "max_drawdown": 1,
            },
        },
    )

    assert response.status_code in {201, 400}
    assert response.status_code != 500


def test_order_draft_api_lifecycle(tmp_path):
    client = _client(tmp_path)
    account = client.post(
        "/api/paper/accounts",
        json={"name": "paper-us", "starting_cash": 100000},
    ).json()

    draft = client.post(
        "/api/paper/drafts",
        json={
            "scan_id": "scan_1",
            "account_id": account["id"],
            "strategy_id": "strategy_1",
            "symbol": "AAPL",
            "market": "US",
            "side": "buy",
            "target_weight": 0.08,
            "current_weight": 0,
            "reference_price": 100,
            "reason": "api smoke",
            "risk_flags": [],
            "trade_session": "2026-01-05",
        },
    )
    assert draft.status_code == 201

    approved = client.patch(f"/api/paper/drafts/{draft.json()['id']}/approve")
    submitted = client.patch(f"/api/paper/drafts/{draft.json()['id']}/submit")

    assert approved.status_code == 200
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"


def test_schedule_api_returns_default_market_schedules(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/schedules")

    assert response.status_code == 200
    markets = {row["market"] for row in response.json()}
    assert {"US", "CN"}.issubset(markets)


def test_data_sync_api_uses_provider_and_persists_market_data(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    client = TestClient(
        create_app(store, provider_factory=lambda market: ApiFakeProvider())
    )

    response = client.post("/api/data-sync/US")

    assert response.status_code == 201
    job = response.json()
    assert job["market"] == "US"
    assert job["provider"] == "fake"
    assert job["coverage"] == 1.0

    jobs = client.get("/api/data-sync/jobs").json()
    assert jobs[0]["id"] == job["id"]
    with store.connection() as conn:
        instrument = conn.execute(
            "SELECT symbol, name_zh FROM instruments WHERE market = 'US'"
        ).fetchone()
        bar = conn.execute(
            "SELECT symbol, close, source FROM market_bars WHERE market = 'US'"
        ).fetchone()
    assert dict(instrument) == {"symbol": "AAPL", "name_zh": "苹果"}
    assert dict(bar) == {"symbol": "AAPL", "close": 100.0, "source": "fake"}

    scan = client.post(
        "/api/signals/scans",
        json={
            "strategy_template": "cross_sectional_momentum",
            "markets": ["US"],
            "parameters": {
                "top_n": 1,
                "hold_rank": 2,
                "lookback_long": 1,
                "lookback_short": 1,
                "max_weight": 0.08,
                "min_amount": 1000,
                "max_volatility": 10,
                "max_drawdown": 1,
            },
        },
    )
    assert scan.status_code in {201, 400}
    assert scan.status_code != 500


def test_instruments_api_lists_stock_pool_with_cache_status(tmp_path):
    client = _client(tmp_path, provider_factory=lambda market: ApiFakeProvider())
    sync = client.post("/api/data-sync/US")
    assert sync.status_code == 201

    response = client.get("/api/instruments?market=US")

    assert response.status_code == 200
    assert response.json() == [
        {
            "symbol": "AAPL",
            "market": "US",
            "name": "Apple",
            "name_zh": "苹果",
            "exchange": "NASDAQ",
            "currency": "USD",
            "sector": "Technology",
            "index_membership": "SP500",
            "tradable": True,
            "lot_size": 1,
            "bar_count": 1,
            "first_session": "2026-01-02",
            "latest_session": "2026-01-02",
        }
    ]


def test_instrument_sync_api_populates_pool_without_downloading_bars(tmp_path):
    client = _client(tmp_path, provider_factory=lambda market: ApiFakeProvider())

    response = client.post("/api/data-sync/US/instruments")

    assert response.status_code == 201
    assert response.json() == {
        "market": "US",
        "provider": "fake",
        "instrument_count": 1,
    }
    instruments = client.get("/api/instruments?market=US").json()
    assert instruments[0]["symbol"] == "AAPL"
    assert instruments[0]["bar_count"] == 0


def test_bar_sync_job_api_starts_background_job_and_lists_progress(tmp_path):
    client = _client(tmp_path, provider_factory=lambda market: ApiFakeProvider())
    assert client.post("/api/data-sync/US/instruments").status_code == 201

    created = client.post(
        "/api/data-sync/US/bars/jobs",
        json={"mode": "initial", "batch_size": 1},
    )
    jobs = client.get("/api/data-sync/bar-jobs")

    assert created.status_code == 201
    assert created.json()["market"] == "US"
    assert created.json()["mode"] == "initial"
    assert jobs.status_code == 200
    assert jobs.json()[0]["id"] == created.json()["id"]
    assert jobs.json()[0]["total_symbols"] == 1


def test_bar_sync_retry_api_creates_job_for_failed_symbols(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    client = TestClient(
        create_app(store, provider_factory=lambda market: LowCoverageApiFakeProvider())
    )
    assert client.post("/api/data-sync/US/instruments").status_code == 201

    created = client.post(
        "/api/data-sync/US/bars/jobs",
        json={"mode": "initial", "batch_size": 2},
    )
    retry = client.post(
        f"/api/data-sync/bar-jobs/{created.json()['id']}/retry",
        json={"batch_size": 1},
    )

    assert retry.status_code == 201
    payload = retry.json()
    assert payload["mode"] == "retry"
    assert payload["target_symbols"] == ["MSFT"]
    assert payload["total_symbols"] == 1


def test_data_sync_api_maps_provider_failures_to_client_error(tmp_path):
    def failing_provider(_market):
        raise RuntimeError("provider dependency missing")

    client = _client(
        tmp_path,
        provider_factory=failing_provider,
        raise_server_exceptions=False,
    )

    response = client.post("/api/data-sync/US")

    assert response.status_code == 400
    assert response.json()["detail"] == "provider dependency missing"


def test_signal_scan_api_uses_latest_sync_coverage_gate(tmp_path):
    client = _client(tmp_path, provider_factory=lambda market: LowCoverageApiFakeProvider())
    sync = client.post("/api/data-sync/US")
    assert sync.status_code == 201
    assert sync.json()["coverage"] == 0.5

    response = client.post(
        "/api/signals/scans",
        json={
            "strategy_template": "cross_sectional_momentum",
            "markets": ["US"],
            "parameters": {
                "top_n": 1,
                "hold_rank": 2,
                "lookback_long": 1,
                "lookback_short": 1,
                "max_weight": 0.08,
                "min_amount": 1000,
                "max_volatility": 10,
                "max_drawdown": 1,
            },
        },
    )

    assert response.status_code == 400
    assert "coverage below 70%" in response.json()["detail"]
