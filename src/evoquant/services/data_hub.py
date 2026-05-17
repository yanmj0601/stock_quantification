from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evoquant.domain import Bar, Instrument, new_id, utc_now
from evoquant.storage import SQLiteStore, dumps, loads


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    instrument_count: int
    bar_count: int


@dataclass(frozen=True)
class QualityReport:
    dataset_id: str
    missing_bars: int
    duplicate_bars: int
    price_anomalies: int


def _serialize_instrument(instrument: Instrument) -> dict[str, Any]:
    return {
        "symbol": instrument.symbol,
        "market": instrument.market.value,
        "asset_class": instrument.asset_class,
        "currency": instrument.currency,
        "exchange": instrument.exchange,
        "lot_size": instrument.lot_size,
        "tradable": instrument.tradable,
    }


def _serialize_bar(bar: Bar) -> dict[str, Any]:
    return {
        "symbol": bar.symbol,
        "market": bar.market.value,
        "session": bar.session.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "adjusted": bar.adjusted,
        "source": bar.source,
    }


def _is_price_anomaly(bar: dict[str, Any]) -> bool:
    low = bar["low"]
    high = bar["high"]
    open_ = bar["open"]
    close = bar["close"]
    volume = bar["volume"]
    return (
        open_ <= 0
        or high <= 0
        or low <= 0
        or close <= 0
        or volume < 0
        or low > high
        or open_ < low
        or open_ > high
        or close < low
        or close > high
    )


class DataHub:
    def __init__(self, store: SQLiteStore):
        self.store = store
        with self.store.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    instruments TEXT NOT NULL,
                    bars TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def register_dataset(self, name: str, instruments: list[Instrument], bars: list[Bar]) -> Dataset:
        dataset = Dataset(new_id("ds"), name, len(instruments), len(bars))
        payload_instruments = [_serialize_instrument(instrument) for instrument in instruments]
        payload_bars = [_serialize_bar(bar) for bar in bars]
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO datasets (id, name, instruments, bars, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    dataset.id,
                    dataset.name,
                    dumps(payload_instruments),
                    dumps(payload_bars),
                    utc_now().isoformat(),
                ),
            )
        return dataset

    def check_quality(self, dataset_id: str) -> QualityReport:
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT instruments, bars FROM datasets WHERE id = ?", (dataset_id,)
            ).fetchone()
        if row is None:
            raise KeyError(dataset_id)

        instruments = loads(row["instruments"])
        bars = loads(row["bars"])
        keys = [(bar["symbol"], bar["market"], bar["session"]) for bar in bars]
        duplicate_bars = len(keys) - len(set(keys))
        market_sessions = {}
        instrument_sessions = {}
        for bar in bars:
            market_sessions.setdefault(bar["market"], set()).add(bar["session"])
            instrument_key = (bar["symbol"], bar["market"])
            instrument_sessions.setdefault(instrument_key, set()).add(bar["session"])

        missing_bars = sum(
            len(
                market_sessions.get(instrument["market"], set())
                - instrument_sessions.get((instrument["symbol"], instrument["market"]), set())
            )
            for instrument in instruments
        )
        price_anomalies = sum(1 for bar in bars if _is_price_anomaly(bar))
        return QualityReport(
            dataset_id,
            missing_bars=missing_bars,
            duplicate_bars=duplicate_bars,
            price_anomalies=price_anomalies,
        )
