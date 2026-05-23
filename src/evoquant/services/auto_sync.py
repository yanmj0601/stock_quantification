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
        return created

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
