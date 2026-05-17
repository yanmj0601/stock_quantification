from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from evoquant.domain import Market, new_id, utc_now
from evoquant.services.market_data import MarketBar
from evoquant.services.strategies import CrossSectionalMomentumStrategy
from evoquant.storage import SQLiteStore, dumps, loads


@dataclass(frozen=True)
class SignalScan:
    id: str
    strategy_template: str
    parameters: Mapping[str, object]
    market_scope: tuple[Market, ...]
    as_of_date: str
    coverage: Mapping[str, float]
    status: str
    error_message: str
    created_at: str


@dataclass(frozen=True)
class SignalResult:
    scan_id: str
    symbol: str
    market: Market
    name: str
    name_zh: str
    close: float
    signal: str
    score: float
    target_weight: float
    reason: str
    risk_flags: tuple[str, ...]
    as_of_date: str
    rank: int


class SignalScanner:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def run_scan(
        self,
        *,
        strategy_template: str,
        parameters: Mapping[str, object],
        market_scope: list[Market],
        universe: Mapping[Market, list[str]],
        bars: list[MarketBar],
        coverage: Mapping[Market, float],
        current_positions: Mapping[str, float],
    ) -> SignalScan:
        scan_id = new_id("scan")
        created_at = utc_now().isoformat()
        as_of_date = _latest_session(bars)
        coverage_payload = {market.value: float(coverage.get(market, 0.0)) for market in market_scope}
        low_coverage = [
            market.value for market in market_scope if float(coverage.get(market, 0.0)) < 0.70
        ]
        if low_coverage:
            scan = SignalScan(
                id=scan_id,
                strategy_template=strategy_template,
                parameters=dict(parameters),
                market_scope=tuple(market_scope),
                as_of_date=as_of_date,
                coverage=coverage_payload,
                status="failed",
                error_message=f"coverage below 70%: {', '.join(low_coverage)}",
                created_at=created_at,
            )
            self._save_scan(scan)
            self._append_event(scan.id, "signals.scan_failed", {"error": scan.error_message})
            return scan

        if strategy_template != "cross_sectional_momentum":
            raise ValueError(f"unsupported strategy template: {strategy_template}")

        strategy = CrossSectionalMomentumStrategy(parameters)
        results: list[SignalResult] = []
        for market in market_scope:
            market_signals = strategy.generate(
                market,
                universe.get(market, []),
                bars,
                current_positions=current_positions,
            )
            for rank, signal in enumerate(
                sorted(market_signals, key=lambda item: item.score, reverse=True), start=1
            ):
                latest_close = _latest_close(signal.symbol, signal.market, bars)
                results.append(
                    SignalResult(
                        scan_id=scan_id,
                        symbol=signal.symbol,
                        market=signal.market,
                        name=signal.symbol,
                        name_zh=signal.symbol,
                        close=latest_close,
                        signal=signal.signal.value,
                        score=signal.score,
                        target_weight=signal.target_weight,
                        reason=signal.reason,
                        risk_flags=signal.risk_flags,
                        as_of_date=signal.as_of_date,
                        rank=rank,
                    )
                )

        scan = SignalScan(
            id=scan_id,
            strategy_template=strategy_template,
            parameters=dict(parameters),
            market_scope=tuple(market_scope),
            as_of_date=as_of_date,
            coverage=coverage_payload,
            status="success",
            error_message="",
            created_at=created_at,
        )
        self._save_scan(scan)
        self._save_results(results)
        self._append_event(scan.id, "signals.scan_completed", {"result_count": len(results)})
        return scan

    def latest_scan(self) -> SignalScan | None:
        with self.store.connection() as conn:
            row = conn.execute(
                """
                SELECT id, strategy_template, parameters, market_scope, as_of_date,
                       coverage, status, error_message, created_at
                FROM signal_scans
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
        return self._scan_from_row(row) if row else None

    def list_scans(self) -> list[SignalScan]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, strategy_template, parameters, market_scope, as_of_date,
                       coverage, status, error_message, created_at
                FROM signal_scans
                ORDER BY created_at DESC, rowid DESC
                """
            ).fetchall()
        return [self._scan_from_row(row) for row in rows]

    def list_results(self, scan_id: str) -> list[SignalResult]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT scan_id, symbol, market, name, name_zh, close, signal,
                       score, target_weight, reason, risk_flags, as_of_date, rank
                FROM signal_results
                WHERE scan_id = ?
                ORDER BY market ASC, rank ASC
                """,
                (scan_id,),
            ).fetchall()
        return [
            SignalResult(
                scan_id=row["scan_id"],
                symbol=row["symbol"],
                market=Market(row["market"]),
                name=row["name"],
                name_zh=row["name_zh"],
                close=float(row["close"]),
                signal=row["signal"],
                score=float(row["score"]),
                target_weight=float(row["target_weight"]),
                reason=row["reason"],
                risk_flags=tuple(loads(row["risk_flags"])),
                as_of_date=row["as_of_date"],
                rank=int(row["rank"]),
            )
            for row in rows
        ]

    def _save_scan(self, scan: SignalScan) -> None:
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO signal_scans (
                    id, strategy_template, parameters, market_scope, as_of_date,
                    coverage, status, error_message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan.id,
                    scan.strategy_template,
                    dumps(scan.parameters),
                    dumps([market.value for market in scan.market_scope]),
                    scan.as_of_date,
                    dumps(scan.coverage),
                    scan.status,
                    scan.error_message,
                    scan.created_at,
                ),
            )

    def _save_results(self, results: list[SignalResult]) -> None:
        with self.store.connection() as conn:
            conn.executemany(
                """
                INSERT INTO signal_results (
                    scan_id, symbol, market, name, name_zh, close, signal,
                    score, target_weight, reason, risk_flags, as_of_date, rank
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.scan_id,
                        result.symbol,
                        result.market.value,
                        result.name,
                        result.name_zh,
                        result.close,
                        result.signal,
                        result.score,
                        result.target_weight,
                        result.reason,
                        dumps(list(result.risk_flags)),
                        result.as_of_date,
                        result.rank,
                    )
                    for result in results
                ],
            )

    def _append_event(self, entity_id: str, event_type: str, payload: dict) -> None:
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (id, entity_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id("evt"), entity_id, event_type, dumps(payload), utc_now().isoformat()),
            )

    def _scan_from_row(self, row) -> SignalScan:
        return SignalScan(
            id=row["id"],
            strategy_template=row["strategy_template"],
            parameters=loads(row["parameters"]),
            market_scope=tuple(Market(value) for value in loads(row["market_scope"])),
            as_of_date=row["as_of_date"],
            coverage=loads(row["coverage"]),
            status=row["status"],
            error_message=row["error_message"],
            created_at=row["created_at"],
        )


def _latest_session(bars: list[MarketBar]) -> str:
    if not bars:
        return ""
    return max(bar.session for bar in bars).isoformat()


def _latest_close(symbol: str, market: Market, bars: list[MarketBar]) -> float:
    symbol_bars = [bar for bar in bars if bar.symbol == symbol and bar.market is market]
    if not symbol_bars:
        return 0.0
    return sorted(symbol_bars, key=lambda bar: bar.session)[-1].close
