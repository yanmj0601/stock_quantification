from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from evoquant.domain import Market
from evoquant.providers.base import MarketDataProvider
from evoquant.services.bar_sync import BarSyncJob, BarSyncJobService
from evoquant.services.instruments import InstrumentMaster
from evoquant.services.market_data import MarketDataService
from evoquant.services.scheduler import SchedulerService
from evoquant.storage import SQLiteStore


class AutoBarSyncService:
    def __init__(
        self,
        store: SQLiteStore,
        provider_factory: Callable[[Market], MarketDataProvider],
    ):
        self.store = store
        self.provider_factory = provider_factory

    def run_due_once(self, *, now: datetime | None = None) -> list[BarSyncJob]:
        now = now or datetime.now(tz=ZoneInfo("UTC"))
        created: list[BarSyncJob] = []
        for config in SchedulerService(self.store).list_configs():
            if not config.enabled:
                continue
            local_now = now.astimezone(ZoneInfo(config.timezone))
            if local_now.strftime("%H:%M") < config.run_time:
                continue
            if self._already_ran(config.market, local_now.date().isoformat()):
                continue
            symbols = [
                item.symbol
                for item in InstrumentMaster(self.store).list_by_market(config.market)
                if item.tradable
            ]
            if not symbols or MarketDataService(self.store).latest_session(config.market, symbols) is None:
                continue
            service = BarSyncJobService(self.store)
            job = service.create_job(
                config.market,
                mode="incremental",
                batch_size=25,
                scheduled_for=local_now.date().isoformat(),
            )
            completed = service.run_job(
                job.id,
                self.provider_factory(config.market),
                today=local_now.date(),
            )
            created.append(completed)
            if completed.status in ("success", "partial"):
                try:
                    self.run_auto_trading(config.market, local_now.date())
                except Exception:
                    import logging
                    logging.getLogger("evoquant").exception(
                        f"Auto trading failed for market {config.market.value}"
                    )
        return created

    def run_auto_trading(self, market: Market, today: date) -> None:
        from datetime import date
        from evoquant.services.signals import SignalScanner
        from evoquant.services.drafts import PaperOrderDraftService
        from evoquant.domain import SignalSide, OrderDraftStatus
        from evoquant.api import _latest_sync_coverage

        # 1. Fetch all active paper accounts
        with self.store.connection() as conn:
            account_rows = conn.execute("SELECT id, name, cash, nav FROM paper_accounts").fetchall()
        
        if not account_rows:
            return

        # 2. Get all tradable instruments for this market
        symbols = [
            item.symbol
            for item in InstrumentMaster(self.store).list_by_market(market)
            if item.tradable
        ]
        if not symbols:
            return

        # 3. Load bars for signals (optimized date range)
        lookback_long = 120
        limit = lookback_long + 30
        with self.store.connection() as conn:
            session_rows = conn.execute(
                "SELECT DISTINCT session FROM market_bars WHERE market = ? ORDER BY session DESC LIMIT ?",
                (market.value, limit),
            ).fetchall()
        if session_rows:
            sessions = sorted([row["session"] for row in session_rows])
            start_date = date.fromisoformat(sessions[0])
        else:
            start_date = date(1900, 1, 1)

        bars = MarketDataService(self.store).list_bars(market, symbols, start_date, today)
        coverage_val = _latest_sync_coverage(self.store, market, has_cached_bars=bool(bars))

        # 4. Run automated trading for each account
        draft_service = PaperOrderDraftService(self.store)
        scanner = SignalScanner(self.store)

        for act_row in account_rows:
            account_id = act_row["id"]
            account_nav = float(act_row["nav"])

            # Get current positions
            with self.store.connection() as conn:
                positions = conn.execute(
                    "SELECT symbol, quantity, average_cost FROM paper_positions WHERE account_id = ?",
                    (account_id,),
                ).fetchall()
            pos_map = {pos["symbol"]: float(pos["quantity"]) for pos in positions}

            # Run signal scan
            scan = scanner.run_scan(
                strategy_template="cross_sectional_momentum",
                parameters={
                    "lookback_long": 120,
                    "lookback_short": 20,
                    "top_n": 20,
                    "hold_rank": 50,
                    "max_weight": 0.08,
                    "min_amount": 10000000,
                    "max_volatility": 0.45,
                    "max_drawdown": 0.35,
                },
                market_scope=[market],
                universe={market: symbols},
                bars=bars,
                coverage={market: coverage_val},
                current_positions=pos_map,
            )

            if scan.status != "success":
                continue

            # Fetch signal results
            results = scanner.list_results(scan.id)

            for result in results:
                # We only trade BUY and SELL signals
                if result.signal not in ("buy", "sell"):
                    continue

                # Calculate current weight
                pos = next((p for p in positions if p["symbol"] == result.symbol), None)
                current_weight = (float(pos["quantity"]) * result.close) / account_nav if pos else 0.0

                # Create paper order draft
                draft = draft_service.create_draft(
                    scan_id=scan.id,
                    account_id=account_id,
                    strategy_id="cross_sectional_momentum",
                    symbol=result.symbol,
                    market=market,
                    side=SignalSide(result.signal),
                    target_weight=result.target_weight,
                    current_weight=current_weight,
                    reference_price=result.close,
                    reason=result.reason,
                    risk_flags=result.risk_flags,
                    trade_session=today,
                )

                # Auto-approve and auto-submit if DRAFT status
                if draft.status is OrderDraftStatus.DRAFT:
                    approved = draft_service.approve(draft.id)
                    draft_service.submit(approved.id)

    def _already_ran(self, market: Market, local_date: str) -> bool:
        with self.store.connection() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM bar_sync_jobs
                WHERE market = ?
                  AND mode = 'incremental'
                  AND scheduled_for = ?
                LIMIT 1
                """,
                (market.value, local_date),
            ).fetchone()
        return row is not None
