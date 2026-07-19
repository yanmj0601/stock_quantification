from __future__ import annotations

import logging
import os
import threading
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from evoquant.domain import Market, RiskMode, SignalSide, StrategyStatus
from evoquant.providers.base import MarketDataProvider, ProviderInstrument
from evoquant.services.auto_sync import AutoBarSyncService
from evoquant.services.backtest import BacktestRunner
from evoquant.services.bar_sync import BarSyncJobService
from evoquant.services.drafts import PaperOrderDraftService
from evoquant.services.evolution import EvolutionService, StrategyTemplate
from evoquant.services.instruments import InstrumentMaster, InstrumentRecord
from evoquant.services.market_data import MarketDataService
from evoquant.services.paper import PaperTradingService
from evoquant.services.registry import StrategyRegistry
from evoquant.services.risk import RiskService
from evoquant.services.scheduler import SchedulerService
from evoquant.services.signals import SignalScanner
from evoquant.storage import SQLiteStore, loads


ADMIN_CONSOLE_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://127.0.0.1:57818",
    "http://localhost:57818",
)

LOGGER = logging.getLogger(__name__)


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


class RealBacktestCreate(BaseModel):
    market: Market
    universe: list[str]
    parameters: dict[str, Any]
    starting_cash: float = 100000.0


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


class PaperDraftCreate(BaseModel):
    scan_id: str
    account_id: str
    strategy_id: str
    symbol: str
    market: Market
    side: SignalSide
    target_weight: float
    current_weight: float
    reference_price: float
    reason: str
    risk_flags: list[str] = Field(default_factory=list)
    trade_session: date


class RiskUpdate(BaseModel):
    mode: RiskMode
    reason: str
    live_enabled: bool | None = None


class SignalScanCreate(BaseModel):
    strategy_template: str
    markets: list[Market]
    parameters: dict[str, Any]


class ScheduleUpdate(BaseModel):
    enabled: bool


class BarSyncJobCreate(BaseModel):
    mode: str = "initial"
    batch_size: int = 25


class BarSyncRetryCreate(BaseModel):
    batch_size: int = 1


ProviderFactory = Callable[[Market], MarketDataProvider]


def create_app(
    store: SQLiteStore | None = None,
    provider_factory: ProviderFactory | None = None,
    enable_auto_scheduler: bool = False,
) -> FastAPI:
    app = FastAPI(title="EvoQuant API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ADMIN_CONSOLE_ORIGINS),
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.state.store = store or SQLiteStore("var/evoquant.db")
    app.state.provider_factory = provider_factory or _default_provider_factory
    app.state.auto_scheduler_stop = threading.Event()
    if enable_auto_scheduler:
        _register_auto_scheduler(app)
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

    @app.post("/api/backtests/signal", status_code=201)
    def run_signal_backtest(payload: RealBacktestCreate) -> dict[str, Any]:
        store = _store(app)
        bars = MarketDataService(store).list_bars(
            payload.market, payload.universe, date(1900, 1, 1), date.today()
        )
        if not bars:
            raise HTTPException(status_code=400, detail="no cached bars for signal backtest")
        try:
            result = BacktestRunner().run_signal_backtest(
                market=payload.market,
                universe=payload.universe,
                bars=bars,
                parameters=payload.parameters,
                starting_cash=payload.starting_cash,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _jsonable(result)

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

    @app.post("/api/paper/drafts", status_code=201)
    def create_paper_draft(payload: PaperDraftCreate) -> dict[str, Any]:
        try:
            draft = PaperOrderDraftService(_store(app)).create_draft(
                scan_id=payload.scan_id,
                account_id=payload.account_id,
                strategy_id=payload.strategy_id,
                symbol=payload.symbol,
                market=payload.market,
                side=payload.side,
                target_weight=payload.target_weight,
                current_weight=payload.current_weight,
                reference_price=payload.reference_price,
                reason=payload.reason,
                risk_flags=payload.risk_flags,
                trade_session=payload.trade_session,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="account not found") from exc
        return _jsonable(draft)

    @app.get("/api/paper/drafts")
    def list_paper_drafts() -> list[dict[str, Any]]:
        return _jsonable(PaperOrderDraftService(_store(app)).list_drafts())

    @app.patch("/api/paper/drafts/{draft_id}/approve")
    def approve_paper_draft(draft_id: str) -> dict[str, Any]:
        try:
            return _jsonable(PaperOrderDraftService(_store(app)).approve(draft_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="draft not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/paper/drafts/{draft_id}/cancel")
    def cancel_paper_draft(draft_id: str) -> dict[str, Any]:
        try:
            return _jsonable(PaperOrderDraftService(_store(app)).cancel(draft_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="draft not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/paper/drafts/{draft_id}/submit")
    def submit_paper_draft(draft_id: str) -> dict[str, Any]:
        try:
            return _jsonable(PaperOrderDraftService(_store(app)).submit(draft_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="draft not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/data-health")
    def data_health() -> dict[str, Any]:
        with _store(app).connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS dataset_count
                FROM instruments
                """
            ).fetchone()
        return {"dataset_count": int(row["dataset_count"])}

    @app.get("/api/data-sync/jobs")
    def list_data_sync_jobs() -> list[dict[str, Any]]:
        return _jsonable(MarketDataService(_store(app)).list_sync_jobs())

    @app.get("/api/data-sync/bar-jobs")
    def list_bar_sync_jobs() -> list[dict[str, Any]]:
        return _jsonable(BarSyncJobService(_store(app)).list_jobs())

    @app.post("/api/data-sync/bar-jobs/{job_id}/retry", status_code=201)
    def retry_bar_sync_job(
        job_id: str,
        payload: BarSyncRetryCreate,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        try:
            job = BarSyncJobService(_store(app)).create_retry_job(
                job_id,
                batch_size=payload.batch_size,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="bar sync job not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        background_tasks.add_task(_run_bar_sync_job, app, job.id, job.market)
        return _jsonable(job)

    @app.get("/api/instruments")
    def list_instruments(market: Market | None = None) -> list[dict[str, Any]]:
        filters = []
        params: list[str] = []
        if market is not None:
            filters.append("i.market = ?")
            params.append(market.value)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with _store(app).connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    i.symbol,
                    i.market,
                    i.name,
                    i.name_zh,
                    i.exchange,
                    i.currency,
                    i.sector,
                    i.index_membership,
                    i.tradable,
                    i.lot_size,
                    COALESCE(b.bar_count, 0) AS bar_count,
                    b.first_session,
                    b.latest_session
                FROM instruments i
                LEFT JOIN (
                    SELECT
                        symbol,
                        market,
                        COUNT(*) AS bar_count,
                        MIN(session) AS first_session,
                        MAX(session) AS latest_session
                    FROM market_bars
                    GROUP BY symbol, market
                ) b ON b.symbol = i.symbol AND b.market = i.market
                {where_clause}
                ORDER BY i.market ASC, i.symbol ASC
                """,
                tuple(params),
            ).fetchall()
        return [
            {
                "symbol": row["symbol"],
                "market": row["market"],
                "name": row["name"],
                "name_zh": row["name_zh"],
                "exchange": row["exchange"],
                "currency": row["currency"],
                "sector": row["sector"],
                "index_membership": row["index_membership"],
                "tradable": bool(row["tradable"]),
                "lot_size": int(row["lot_size"]),
                "bar_count": int(row["bar_count"]),
                "first_session": row["first_session"],
                "latest_session": row["latest_session"],
            }
            for row in rows
        ]

    @app.post("/api/data-sync/{market}", status_code=201)
    def start_data_sync(market: Market) -> dict[str, Any]:
        if market not in {Market.US, Market.CN}:
            raise HTTPException(status_code=400, detail=f"{market.value} sync is not supported yet")
        try:
            provider = _provider_factory(app)(market)
            instruments = provider.sync_instruments(_index_id(market))
            if not instruments:
                raise RuntimeError(f"{market.value} provider returned no instruments")
            InstrumentMaster(_store(app)).upsert_many(
                [_instrument_record(item) for item in instruments]
            )
            symbols = [item.symbol for item in instruments if item.tradable]
            job = MarketDataService(_store(app)).sync_bars(
                provider,
                symbols,
                market,
                date.today() - timedelta(days=365 * 5),
                date.today(),
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _jsonable(job)

    @app.post("/api/data-sync/{market}/instruments", status_code=201)
    def sync_instruments_only(market: Market) -> dict[str, Any]:
        if market not in {Market.US, Market.CN}:
            raise HTTPException(status_code=400, detail=f"{market.value} sync is not supported yet")
        try:
            provider = _provider_factory(app)(market)
            instruments = provider.sync_instruments(_index_id(market))
            if not instruments:
                raise RuntimeError(f"{market.value} provider returned no instruments")
            InstrumentMaster(_store(app)).upsert_many(
                [_instrument_record(item) for item in instruments]
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "market": market.value,
            "provider": provider.name,
            "instrument_count": len(instruments),
        }

    @app.post("/api/data-sync/{market}/bars/jobs", status_code=201)
    def create_bar_sync_job(
        market: Market,
        payload: BarSyncJobCreate,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        if market not in {Market.US, Market.CN}:
            raise HTTPException(status_code=400, detail=f"{market.value} sync is not supported yet")
        try:
            store = _store(app)
            master = InstrumentMaster(store)
            existing = master.list_by_market(market)
            
            # 如果股票池尚未初始化，或者目前还是少于 1000 只股票的标普500旧池，自动自动热升级为全市场
            if len(existing) < 1000:
                provider = _provider_factory(app)(market)
                instruments = provider.sync_instruments(_index_id(market))
                if instruments:
                    master.upsert_many([_instrument_record(item) for item in instruments])

            job = BarSyncJobService(store).create_job(
                market,
                mode=payload.mode,
                batch_size=payload.batch_size,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        background_tasks.add_task(_run_bar_sync_job, app, job.id, market)
        return _jsonable(job)

    @app.post("/api/signals/scans", status_code=201)
    def create_signal_scan(payload: SignalScanCreate) -> dict[str, Any]:
        store = _store(app)
        market_data = MarketDataService(store)
        universe: dict[Market, list[str]] = {}
        bars = []
        coverage: dict[Market, float] = {}
        for market in payload.markets:
            with store.connection() as conn:
                symbol_rows = conn.execute(
                    """
                    SELECT DISTINCT symbol
                    FROM market_bars
                    WHERE market = ?
                    ORDER BY symbol ASC
                    """,
                    (market.value,),
                ).fetchall()
            symbols = [row["symbol"] for row in symbol_rows]
            universe[market] = symbols
            coverage[market] = _latest_sync_coverage(store, market, has_cached_bars=bool(symbols))
            if symbols:
                bars.extend(market_data.list_bars(market, symbols, date(1900, 1, 1), date.today()))

        scan = SignalScanner(store).run_scan(
            strategy_template=payload.strategy_template,
            parameters=payload.parameters,
            market_scope=payload.markets,
            universe=universe,
            bars=bars,
            coverage=coverage,
            current_positions={},
        )
        if scan.status == "failed":
            raise HTTPException(status_code=400, detail=scan.error_message)
        return _jsonable(scan)

    @app.get("/api/signals/scans")
    def list_signal_scans() -> list[dict[str, Any]]:
        return _jsonable(SignalScanner(_store(app)).list_scans())

    @app.get("/api/signals/scans/{scan_id}")
    def get_signal_scan(scan_id: str) -> dict[str, Any]:
        for scan in SignalScanner(_store(app)).list_scans():
            if scan.id == scan_id:
                return _jsonable(scan)
        raise HTTPException(status_code=404, detail="scan not found")

    @app.get("/api/signals/scans/{scan_id}/results")
    def list_signal_results(scan_id: str) -> list[dict[str, Any]]:
        return _jsonable(SignalScanner(_store(app)).list_results(scan_id))

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

    @app.get("/api/schedules")
    def list_schedules() -> list[dict[str, Any]]:
        return _jsonable(SchedulerService(_store(app)).list_configs())

    @app.patch("/api/schedules/{market}")
    def update_schedule(market: Market, payload: ScheduleUpdate) -> dict[str, Any]:
        return _jsonable(SchedulerService(_store(app)).set_enabled(market, payload.enabled))

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


def _provider_factory(app: FastAPI) -> ProviderFactory:
    return app.state.provider_factory


def _default_provider_factory(market: Market) -> MarketDataProvider:
    if market is Market.US:
        provider_name = os.environ.get("EVOQUANT_US_PROVIDER", "").strip().lower()
        if provider_name == "tiingo" or os.environ.get("TIINGO_API_KEY"):
            from evoquant.providers.tiingo import TiingoProvider

            return TiingoProvider()
        from evoquant.providers.yahoo import YahooFinanceProvider

        return YahooFinanceProvider()
    if market is Market.CN:
        from evoquant.providers.baostock import BaostockProvider

        return BaostockProvider()
    raise RuntimeError(f"{market.value} sync is not supported yet")


def _index_id(market: Market) -> str:
    return "ALL"
    raise RuntimeError(f"{market.value} sync is not supported yet")


def _latest_sync_coverage(store: SQLiteStore, market: Market, *, has_cached_bars: bool) -> float:
    if not has_cached_bars:
        return 0.0
    with store.connection() as conn:
        # 查询 instruments 中 tradable 的总股票数
        total_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM instruments WHERE market = ? AND tradable = 1",
            (market.value,)
        ).fetchone()
        total_inst = total_row["cnt"] if total_row else 0
        if total_inst == 0:
            return 0.0
            
        # 查询 market_bars 中有数据的独特股票数
        active_row = conn.execute(
            "SELECT COUNT(DISTINCT symbol) AS cnt FROM market_bars WHERE market = ?",
            (market.value,)
        ).fetchone()
        active_bars = active_row["cnt"] if active_row else 0
        
        real_coverage = round(active_bars / total_inst, 4)
        return real_coverage


def _run_bar_sync_job(app: FastAPI, job_id: str, market: Market) -> None:
    provider = _provider_factory(app)(market)
    BarSyncJobService(_store(app)).run_job(job_id, provider)


def _register_auto_scheduler(app: FastAPI) -> None:
    @app.on_event("startup")
    def start_auto_scheduler() -> None:
        stop_event = app.state.auto_scheduler_stop
        thread = threading.Thread(
            target=_auto_scheduler_loop,
            args=(app, stop_event),
            name="evoquant-auto-bar-sync",
            daemon=True,
        )
        thread.start()
        app.state.auto_scheduler_thread = thread

    @app.on_event("shutdown")
    def stop_auto_scheduler() -> None:
        app.state.auto_scheduler_stop.set()


def _auto_scheduler_loop(app: FastAPI, stop_event: threading.Event) -> None:
    while not stop_event.wait(60):
        try:
            AutoBarSyncService(_store(app), _provider_factory(app)).run_due_once()
        except Exception:
            LOGGER.exception("auto bar sync scheduler tick failed")


def _instrument_record(item: ProviderInstrument) -> InstrumentRecord:
    return InstrumentRecord(
        symbol=item.symbol,
        market=item.market,
        name=item.name,
        name_zh=item.name_zh,
        exchange=item.exchange,
        currency=item.currency,
        sector=item.sector,
        index_membership=item.index_membership,
        tradable=item.tradable,
        lot_size=item.lot_size,
    )


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


app = create_app(enable_auto_scheduler=True)
