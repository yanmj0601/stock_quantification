from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from evoquant.domain import Market, new_id, utc_now
from evoquant.providers.base import MarketDataProvider, ProviderBar
from evoquant.storage import PostgreSQLStore, dumps, loads


@dataclass(frozen=True)
class MarketBar:
    symbol: str
    market: Market
    session: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    adjusted: bool
    suspended: bool
    limit_up: bool
    limit_down: bool
    source: str


@dataclass(frozen=True)
class SyncJob:
    id: str
    market: Market
    provider: str
    status: str
    started_at: str
    finished_at: str
    total_symbols: int
    success_symbols: int
    failed_symbols: int
    coverage: float
    failures: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class QualitySummary:
    sync_job_id: str
    market: Market
    missing_bars: int
    duplicate_bars: int
    price_anomalies: int
    suspended_count: int
    limit_up_count: int
    limit_down_count: int


def _provider_to_market_bar(bar: ProviderBar) -> MarketBar:
    return MarketBar(
        symbol=bar.symbol,
        market=bar.market,
        session=bar.session,
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
        volume=float(bar.volume),
        amount=float(bar.amount),
        adjusted=bool(bar.adjusted),
        suspended=bool(bar.suspended),
        limit_up=bool(bar.limit_up),
        limit_down=bool(bar.limit_down),
        source=bar.source,
    )


def _bar_from_row(row) -> MarketBar:
    return MarketBar(
        symbol=row["symbol"],
        market=Market(row["market"]),
        session=date.fromisoformat(row["session"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        amount=float(row["amount"]),
        adjusted=bool(row["adjusted"]),
        suspended=bool(row["suspended"]),
        limit_up=bool(row["limit_up"]),
        limit_down=bool(row["limit_down"]),
        source=row["source"],
    )


def _is_price_anomaly(bar: MarketBar) -> bool:
    return (
        bar.open <= 0
        or bar.high <= 0
        or bar.low <= 0
        or bar.close <= 0
        or bar.volume < 0
        or bar.amount < 0
        or bar.low > bar.high
        or bar.open < bar.low
        or bar.open > bar.high
        or bar.close < bar.low
        or bar.close > bar.high
    )


class MarketDataService:
    def __init__(self, store: PostgreSQLStore):
        self.store = store

    def sync_bars(
        self,
        provider: MarketDataProvider,
        symbols: list[str],
        market: Market,
        start: date,
        end: date,
        timeframe: str = "1d",
    ) -> SyncJob:
        requested = list(dict.fromkeys(symbols))
        started_at = utc_now().isoformat()
        provider_bars = provider.sync_bars(requested, market, start, end, timeframe)
        bars = [_provider_to_market_bar(bar) for bar in provider_bars]
        returned_symbols = {bar.symbol for bar in bars}
        failures = tuple(symbol for symbol in requested if symbol not in returned_symbols)
        total_symbols = len(requested)
        success_symbols = len(returned_symbols)
        failed_symbols = len(failures)
        coverage = round(success_symbols / total_symbols, 4) if total_symbols else 0.0
        status = "success" if failed_symbols == 0 else "partial"
        now = utc_now().isoformat()
        job = SyncJob(
            id=new_id("sync"),
            market=market,
            provider=provider.name,
            status=status,
            started_at=started_at,
            finished_at=now,
            total_symbols=total_symbols,
            success_symbols=success_symbols,
            failed_symbols=failed_symbols,
            coverage=coverage,
            failures=failures,
            message=_sync_message(success_symbols, total_symbols, failures),
        )

        with self.store.connection() as conn:
            conn.executemany(
                """
                INSERT INTO market_bars (
                    symbol, market, session, open, high, low, close, volume,
                    amount, adjusted, suspended, limit_up, limit_down, source, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, session) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    adjusted = excluded.adjusted,
                    suspended = excluded.suspended,
                    limit_up = excluded.limit_up,
                    limit_down = excluded.limit_down,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        bar.symbol,
                        bar.market.value,
                        bar.session.isoformat(),
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        bar.amount,
                        1 if bar.adjusted else 0,
                        1 if bar.suspended else 0,
                        1 if bar.limit_up else 0,
                        1 if bar.limit_down else 0,
                        bar.source,
                        now,
                    )
                    for bar in bars
                ],
            )
            conn.execute(
                """
                INSERT INTO market_sync_jobs (
                    id, market, provider, status, started_at, finished_at,
                    total_symbols, success_symbols, failed_symbols, coverage, failures
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.market.value,
                    job.provider,
                    job.status,
                    started_at,
                    now,
                    job.total_symbols,
                    job.success_symbols,
                    job.failed_symbols,
                    job.coverage,
                    dumps(list(job.failures)),
                ),
            )
        self.quality_report(job.id, market, start, end)
        return job

    def incremental_sync(
        self,
        provider: MarketDataProvider,
        symbols: list[str],
        market: Market,
        end: date,
        timeframe: str = "1d",
    ) -> SyncJob:
        latest = self.latest_session(market, symbols)
        start = latest + timedelta(days=1) if latest else end - timedelta(days=365 * 5)
        return self.sync_bars(provider, symbols, market, start, end, timeframe)

    def latest_session(self, market: Market, symbols: list[str]) -> date | None:
        if not symbols:
            return None
        chunk_size = 500
        latest_dates = []
        with self.store.connection() as conn:
            for k in range(0, len(symbols), chunk_size):
                chunk = symbols[k : k + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                row = conn.execute(
                    f"""
                    SELECT MAX(session) AS latest_session
                    FROM market_bars
                    WHERE market = ? AND symbol IN ({placeholders})
                    """,
                    (market.value, *chunk),
                ).fetchone()
                if row and row["latest_session"]:
                    latest_dates.append(date.fromisoformat(row["latest_session"]))
        return max(latest_dates) if latest_dates else None

    def list_bars(
        self, market: Market, symbols: list[str], start: date, end: date
    ) -> list[MarketBar]:
        if not symbols:
            return []
        chunk_size = 500
        rows = []
        with self.store.connection() as conn:
            for k in range(0, len(symbols), chunk_size):
                chunk = symbols[k : k + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                chunk_rows = conn.execute(
                    f"""
                    SELECT symbol, market, session, open, high, low, close, volume,
                           amount, adjusted, suspended, limit_up, limit_down, source
                    FROM market_bars
                    WHERE market = ?
                      AND symbol IN ({placeholders})
                      AND session >= ?
                      AND session <= ?
                    ORDER BY symbol ASC, session ASC
                    """,
                    (market.value, *chunk, start.isoformat(), end.isoformat()),
                ).fetchall()
                rows.extend(chunk_rows)
        return [_bar_from_row(row) for row in rows]

    def quality_report(
        self, sync_job_id: str, market: Market, start: date, end: date
    ) -> QualitySummary:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, market, session, open, high, low, close, volume,
                       amount, adjusted, suspended, limit_up, limit_down, source
                FROM market_bars
                WHERE market = ? AND session >= ? AND session <= ?
                """,
                (market.value, start.isoformat(), end.isoformat()),
            ).fetchall()
        bars = [_bar_from_row(row) for row in rows]
        summary = QualitySummary(
            sync_job_id=sync_job_id,
            market=market,
            missing_bars=0,
            duplicate_bars=0,
            price_anomalies=sum(1 for bar in bars if _is_price_anomaly(bar)),
            suspended_count=sum(1 for bar in bars if bar.suspended),
            limit_up_count=sum(1 for bar in bars if bar.limit_up),
            limit_down_count=sum(1 for bar in bars if bar.limit_down),
        )
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO market_quality_reports (
                    id, sync_job_id, market, missing_bars, duplicate_bars,
                    price_anomalies, suspended_count, limit_up_count,
                    limit_down_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("qr"),
                    summary.sync_job_id,
                    summary.market.value,
                    summary.missing_bars,
                    summary.duplicate_bars,
                    summary.price_anomalies,
                    summary.suspended_count,
                    summary.limit_up_count,
                    summary.limit_down_count,
                    utc_now().isoformat(),
                ),
            )
        return summary

    def list_sync_jobs(self) -> list[SyncJob]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, market, provider, status, total_symbols, success_symbols,
                       failed_symbols, coverage, failures, started_at, finished_at
                FROM market_sync_jobs
                ORDER BY started_at DESC, rowid DESC
                """
            ).fetchall()
        return [
            SyncJob(
                id=row["id"],
                market=Market(row["market"]),
                provider=row["provider"],
                status=row["status"],
                started_at=row["started_at"],
                finished_at=row["finished_at"] or "",
                total_symbols=int(row["total_symbols"]),
                success_symbols=int(row["success_symbols"]),
                failed_symbols=int(row["failed_symbols"]),
                coverage=float(row["coverage"]),
                failures=tuple(loads(row["failures"])),
                message=_sync_message(
                    int(row["success_symbols"]),
                    int(row["total_symbols"]),
                    tuple(loads(row["failures"])),
                ),
            )
            for row in rows
        ]


def _sync_message(success_symbols: int, total_symbols: int, failures: tuple[str, ...]) -> str:
    base = f"{success_symbols}/{total_symbols} symbols synced"
    if not failures:
        return base
    preview = ", ".join(failures[:5])
    suffix = "..." if len(failures) > 5 else ""
    return f"{base}; failures: {preview}{suffix}"
