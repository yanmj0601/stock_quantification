from __future__ import annotations

from dataclasses import dataclass

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
        payload_instruments = [
            instrument.__dict__ | {"market": instrument.market.value} for instrument in instruments
        ]
        payload_bars = [
            bar.__dict__ | {"market": bar.market.value, "session": bar.session.isoformat()} for bar in bars
        ]
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
            row = conn.execute("SELECT bars FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if row is None:
            raise KeyError(dataset_id)

        bars = loads(row["bars"])
        keys = [(bar["symbol"], bar["market"], bar["session"]) for bar in bars]
        duplicate_bars = len(keys) - len(set(keys))
        price_anomalies = sum(
            1
            for bar in bars
            if bar["low"] > bar["high"]
            or bar["open"] <= 0
            or bar["close"] <= 0
            or bar["volume"] < 0
        )
        return QualityReport(
            dataset_id,
            missing_bars=0,
            duplicate_bars=duplicate_bars,
            price_anomalies=price_anomalies,
        )
