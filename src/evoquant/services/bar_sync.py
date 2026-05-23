from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from evoquant.domain import Market, new_id, utc_now
from evoquant.providers.base import MarketDataProvider
from evoquant.services.instruments import InstrumentMaster
from evoquant.services.market_data import MarketDataService
from evoquant.storage import SQLiteStore, dumps, loads


@dataclass(frozen=True)
class BarSyncJob:
    id: str
    market: Market
    mode: str
    status: str
    batch_size: int
    total_symbols: int
    completed_symbols: int
    success_symbols: int
    failed_symbols: int
    progress: float
    failures: tuple[str, ...]
    scheduled_for: str
    started_at: str
    finished_at: str
    created_at: str
    updated_at: str


class BarSyncJobService:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def create_job(
        self,
        market: Market,
        *,
        mode: str,
        batch_size: int = 25,
        scheduled_for: str = "",
    ) -> BarSyncJob:
        if mode not in {"initial", "incremental", "manual"}:
            raise ValueError(f"unsupported bar sync mode: {mode}")
        symbols = self._symbols(market)
        if not symbols:
            raise ValueError(f"no instruments loaded for {market.value}")
        now = utc_now().isoformat()
        job = BarSyncJob(
            id=new_id("barjob"),
            market=market,
            mode=mode,
            status="queued",
            batch_size=max(1, int(batch_size)),
            total_symbols=len(symbols),
            completed_symbols=0,
            success_symbols=0,
            failed_symbols=0,
            progress=0.0,
            failures=(),
            scheduled_for=scheduled_for,
            started_at="",
            finished_at="",
            created_at=now,
            updated_at=now,
        )
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO bar_sync_jobs (
                    id, market, mode, status, batch_size, total_symbols,
                    completed_symbols, success_symbols, failed_symbols, progress,
                    failures, scheduled_for, started_at, finished_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.market.value,
                    job.mode,
                    job.status,
                    job.batch_size,
                    job.total_symbols,
                    job.completed_symbols,
                    job.success_symbols,
                    job.failed_symbols,
                    job.progress,
                    dumps(list(job.failures)),
                    job.scheduled_for,
                    None,
                    None,
                    job.created_at,
                    job.updated_at,
                ),
            )
        return job

    def run_job(
        self,
        job_id: str,
        provider: MarketDataProvider,
        *,
        today: date | None = None,
    ) -> BarSyncJob:
        today = today or date.today()
        job = self.get_job(job_id)
        symbols = self._symbols(job.market)
        self._mark_running(job.id)
        completed = 0
        success = 0
        failures: list[str] = []
        market_data = MarketDataService(self.store)
        for batch in _chunks(symbols, job.batch_size):
            try:
                if job.mode == "incremental":
                    sync = market_data.incremental_sync(provider, batch, job.market, end=today)
                else:
                    sync = market_data.sync_bars(
                        provider,
                        batch,
                        job.market,
                        today - timedelta(days=365 * 5),
                        today,
                    )
                success += sync.success_symbols
                failures.extend(sync.failures)
            except Exception as exc:
                failures.extend(f"{symbol}: {exc}" for symbol in batch)
            completed += len(batch)
            self._update_progress(job.id, completed, success, failures, finished=False)
        return self._update_progress(job.id, completed, success, failures, finished=True)

    def list_jobs(self) -> list[BarSyncJob]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, market, mode, status, batch_size, total_symbols,
                       completed_symbols, success_symbols, failed_symbols, progress,
                       failures, scheduled_for, started_at, finished_at, created_at, updated_at
                FROM bar_sync_jobs
                ORDER BY created_at DESC, rowid DESC
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_job(self, job_id: str) -> BarSyncJob:
        with self.store.connection() as conn:
            row = conn.execute(
                """
                SELECT id, market, mode, status, batch_size, total_symbols,
                       completed_symbols, success_symbols, failed_symbols, progress,
                       failures, scheduled_for, started_at, finished_at, created_at, updated_at
                FROM bar_sync_jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._from_row(row)

    def _symbols(self, market: Market) -> list[str]:
        return [
            instrument.symbol
            for instrument in InstrumentMaster(self.store).list_by_market(market)
            if instrument.tradable
        ]

    def _mark_running(self, job_id: str) -> None:
        now = utc_now().isoformat()
        with self.store.connection() as conn:
            conn.execute(
                """
                UPDATE bar_sync_jobs
                SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (now, now, job_id),
            )

    def _update_progress(
        self,
        job_id: str,
        completed: int,
        success: int,
        failures: list[str],
        *,
        finished: bool,
    ) -> BarSyncJob:
        current = self.get_job(job_id)
        failed = len(failures)
        progress = round(completed / current.total_symbols, 4) if current.total_symbols else 0.0
        status = "running"
        finished_at = current.finished_at
        if finished:
            status = "success" if failed == 0 else "partial"
            finished_at = utc_now().isoformat()
        with self.store.connection() as conn:
            conn.execute(
                """
                UPDATE bar_sync_jobs
                SET status = ?, completed_symbols = ?, success_symbols = ?,
                    failed_symbols = ?, progress = ?, failures = ?,
                    finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    completed,
                    success,
                    failed,
                    progress,
                    dumps(failures),
                    finished_at or None,
                    utc_now().isoformat(),
                    job_id,
                ),
            )
        return self.get_job(job_id)

    def _from_row(self, row) -> BarSyncJob:
        return BarSyncJob(
            id=row["id"],
            market=Market(row["market"]),
            mode=row["mode"],
            status=row["status"],
            batch_size=int(row["batch_size"]),
            total_symbols=int(row["total_symbols"]),
            completed_symbols=int(row["completed_symbols"]),
            success_symbols=int(row["success_symbols"]),
            failed_symbols=int(row["failed_symbols"]),
            progress=float(row["progress"]),
            failures=tuple(loads(row["failures"])),
            scheduled_for=row["scheduled_for"],
            started_at=row["started_at"] or "",
            finished_at=row["finished_at"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _chunks(items: list[str], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]
