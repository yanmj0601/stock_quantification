from __future__ import annotations

from dataclasses import dataclass

from evoquant.domain import Market, utc_now
from evoquant.storage import PostgreSQLStore


@dataclass(frozen=True)
class InstrumentRecord:
    symbol: str
    market: Market
    name: str
    name_zh: str
    exchange: str
    currency: str
    sector: str
    index_membership: str
    tradable: bool
    lot_size: int


class InstrumentMaster:
    def __init__(self, store: PostgreSQLStore):
        self.store = store

    def upsert_many(self, instruments: list[InstrumentRecord]) -> None:
        now = utc_now().isoformat()
        with self.store.connection() as conn:
            conn.executemany(
                """
                INSERT INTO instruments (
                    symbol, market, name, name_zh, exchange, currency, sector,
                    index_membership, tradable, lot_size, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market) DO UPDATE SET
                    name = excluded.name,
                    name_zh = excluded.name_zh,
                    exchange = excluded.exchange,
                    currency = excluded.currency,
                    sector = excluded.sector,
                    index_membership = excluded.index_membership,
                    tradable = excluded.tradable,
                    lot_size = excluded.lot_size,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        item.symbol,
                        item.market.value,
                        item.name,
                        item.name_zh,
                        item.exchange,
                        item.currency,
                        item.sector,
                        item.index_membership,
                        1 if item.tradable else 0,
                        item.lot_size,
                        now,
                    )
                    for item in instruments
                ],
            )

    def list_by_market(self, market: Market) -> list[InstrumentRecord]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, market, name, name_zh, exchange, currency, sector,
                       index_membership, tradable, lot_size
                FROM instruments
                WHERE market = ?
                ORDER BY symbol ASC
                """,
                (market.value,),
            ).fetchall()
        return [
            InstrumentRecord(
                symbol=row["symbol"],
                market=Market(row["market"]),
                name=row["name"],
                name_zh=row["name_zh"],
                exchange=row["exchange"],
                currency=row["currency"],
                sector=row["sector"],
                index_membership=row["index_membership"],
                tradable=bool(row["tradable"]),
                lot_size=int(row["lot_size"]),
            )
            for row in rows
        ]
