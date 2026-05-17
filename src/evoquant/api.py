from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from evoquant.domain import Market, RiskMode, StrategyStatus
from evoquant.services.backtest import BacktestRunner
from evoquant.services.data_hub import DataHub
from evoquant.services.evolution import EvolutionService, StrategyTemplate
from evoquant.services.paper import PaperTradingService
from evoquant.services.registry import StrategyRegistry
from evoquant.services.risk import RiskService
from evoquant.storage import SQLiteStore, loads


ADMIN_CONSOLE_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
)


class StrategyCreate(BaseModel):
    name: str
    market: Market
    asset_class: str
    template_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class StrategyStatusUpdate(BaseModel):
    status: StrategyStatus
    reason: str


class BacktestCreate(BaseModel):
    strategy_id: str
    equity: list[float]
    turnovers: list[float] = Field(default_factory=list)


class EvolutionCreate(BaseModel):
    template_id: str
    parameter_space: dict[str, list[Any]]
    max_candidates: int = 10


class PaperAccountCreate(BaseModel):
    name: str
    starting_cash: float


class PaperOrderCreate(BaseModel):
    account_id: str
    symbol: str
    market: Market
    quantity: float
    limit_price: float


class RiskUpdate(BaseModel):
    mode: RiskMode
    reason: str
    live_enabled: bool | None = None


def create_app(store: SQLiteStore | None = None) -> FastAPI:
    app = FastAPI(title="EvoQuant API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ADMIN_CONSOLE_ORIGINS),
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.state.store = store or SQLiteStore("var/evoquant.db")
    register_routes(app)
    return app


def register_routes(app: FastAPI) -> None:
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        store = _store(app)
        risk = RiskService(store).current()
        PaperTradingService(store)
        with store.connection() as conn:
            strategy_count = conn.execute("SELECT COUNT(*) AS count FROM strategies").fetchone()[
                "count"
            ]
            status_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM strategies
                GROUP BY status
                ORDER BY status ASC
                """
            ).fetchall()
            account_row = conn.execute(
                """
                SELECT COUNT(*) AS account_count, COALESCE(SUM(nav), 0) AS total_nav
                FROM paper_accounts
                """
            ).fetchone()
            audit_count = conn.execute(
                "SELECT COUNT(*) AS count FROM audit_events"
            ).fetchone()["count"]
        return {
            "strategy_count": int(strategy_count),
            "strategies_by_status": {
                row["status"]: int(row["count"]) for row in status_rows
            },
            "paper_account_count": int(account_row["account_count"]),
            "paper_total_nav": float(account_row["total_nav"]),
            "audit_event_count": int(audit_count),
            "risk": _jsonable(risk),
        }

    @app.get("/api/strategies")
    def list_strategies() -> list[dict[str, Any]]:
        with _store(app).connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, market, asset_class, template_id, parameters,
                       status, version, metrics
                FROM strategies
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "market": row["market"],
                "asset_class": row["asset_class"],
                "template_id": row["template_id"],
                "parameters": loads(row["parameters"]),
                "status": row["status"],
                "version": row["version"],
                "metrics": loads(row["metrics"]),
            }
            for row in rows
        ]

    @app.post("/api/strategies", status_code=201)
    def create_strategy(payload: StrategyCreate) -> dict[str, Any]:
        strategy = StrategyRegistry(_store(app)).create_strategy(
            name=payload.name,
            market=payload.market,
            asset_class=payload.asset_class,
            template_id=payload.template_id,
            parameters=payload.parameters,
        )
        return _jsonable(strategy)

    @app.patch("/api/strategies/{strategy_id}/status")
    def set_strategy_status(
        strategy_id: str, payload: StrategyStatusUpdate
    ) -> dict[str, Any]:
        try:
            strategy = StrategyRegistry(_store(app)).set_status(
                strategy_id, payload.status, payload.reason
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="strategy not found") from exc
        return _jsonable(strategy)

    @app.post("/api/backtests", status_code=201)
    def run_backtest(payload: BacktestCreate) -> dict[str, Any]:
        registry = StrategyRegistry(_store(app))
        try:
            strategy = registry.get_strategy(payload.strategy_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="strategy not found") from exc
        try:
            result = BacktestRunner().run(payload.equity, payload.turnovers)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        metrics = dict(result.metrics)
        registry.record_metrics(strategy.id, metrics)
        return {"strategy_id": strategy.id, "metrics": _jsonable(metrics)}

    @app.post("/api/evolution", status_code=201)
    def generate_candidates(payload: EvolutionCreate) -> dict[str, Any]:
        try:
            candidates = EvolutionService(_store(app)).generate_candidates(
                StrategyTemplate(payload.template_id, payload.parameter_space),
                payload.max_candidates,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"candidates": _jsonable(candidates)}

    @app.get("/api/paper/accounts")
    def list_paper_accounts() -> list[dict[str, Any]]:
        PaperTradingService(_store(app))
        with _store(app).connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, cash, nav
                FROM paper_accounts
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "cash": float(row["cash"]),
                "nav": float(row["nav"]),
            }
            for row in rows
        ]

    @app.post("/api/paper/accounts", status_code=201)
    def create_paper_account(payload: PaperAccountCreate) -> dict[str, Any]:
        account = PaperTradingService(_store(app)).create_account(
            payload.name, payload.starting_cash
        )
        return _jsonable(account)

    @app.post("/api/paper/orders", status_code=201)
    def create_paper_order(payload: PaperOrderCreate) -> dict[str, Any]:
        store = _store(app)
        service = PaperTradingService(store)
        risk = RiskService(store)
        risk.assert_live_disabled()
        try:
            risk.assert_paper_allowed()
            order = service.submit_order(
                payload.account_id,
                payload.symbol,
                payload.market,
                payload.quantity,
                payload.limit_price,
            )
            service.fill_order(order.id, payload.limit_price, fee=0.0)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="account not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {**_jsonable(order), "status": "filled"}

    @app.get("/api/paper/orders")
    def list_paper_orders() -> list[dict[str, Any]]:
        PaperTradingService(_store(app))
        with _store(app).connection() as conn:
            rows = conn.execute(
                """
                SELECT id, account_id, symbol, market, quantity, limit_price,
                       status, created_at
                FROM paper_orders
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "account_id": row["account_id"],
                "symbol": row["symbol"],
                "market": row["market"],
                "quantity": float(row["quantity"]),
                "limit_price": float(row["limit_price"]),
                "status": row["status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @app.get("/api/paper/fills")
    def list_paper_fills() -> list[dict[str, Any]]:
        PaperTradingService(_store(app))
        with _store(app).connection() as conn:
            rows = conn.execute(
                """
                SELECT id, order_id, account_id, symbol, market, quantity,
                       fill_price, fee, created_at
                FROM paper_fills
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "order_id": row["order_id"],
                "account_id": row["account_id"],
                "symbol": row["symbol"],
                "market": row["market"],
                "quantity": float(row["quantity"]),
                "fill_price": float(row["fill_price"]),
                "fee": float(row["fee"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @app.get("/api/paper/accounts/{account_id}/positions")
    def list_paper_positions(account_id: str) -> list[dict[str, Any]]:
        try:
            positions = PaperTradingService(_store(app)).list_positions(account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="account not found") from exc
        return _jsonable(positions)

    @app.get("/api/data-health")
    def data_health() -> dict[str, Any]:
        DataHub(_store(app))
        with _store(app).connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS dataset_count
                FROM datasets
                """
            ).fetchone()
        return {"dataset_count": int(row["dataset_count"])}

    @app.get("/api/risk")
    def get_risk() -> dict[str, Any]:
        return _jsonable(RiskService(_store(app)).current())

    @app.patch("/api/risk")
    def update_risk(payload: RiskUpdate) -> dict[str, Any]:
        if payload.live_enabled:
            raise HTTPException(
                status_code=400,
                detail="live trading cannot be enabled in EvoQuant MVP v1",
            )
        state = RiskService(_store(app)).set_mode(payload.mode, payload.reason)
        return _jsonable(state)

    @app.get("/api/audit-events")
    def list_audit_events() -> list[dict[str, Any]]:
        with _store(app).connection() as conn:
            rows = conn.execute(
                """
                SELECT id, entity_id, event_type, payload, created_at
                FROM audit_events
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "entity_id": row["entity_id"],
                "event_type": row["event_type"],
                "payload": loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def _store(app: FastAPI) -> SQLiteStore:
    return app.state.store


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, MappingProxyType | Mapping):
        return {key: _jsonable(nested) for key, nested in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(nested) for nested in value]
    return value


app = create_app()
