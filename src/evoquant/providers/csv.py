from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


class CsvMarketDataProvider:
    name = "csv"

    def __init__(self, instruments_path: str | Path, bars_path: str | Path):
        self.instruments_path = Path(instruments_path)
        self.bars_path = Path(bars_path)

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        with self.instruments_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return [
            ProviderInstrument(
                symbol=row["symbol"],
                market=Market(row["market"]),
                name=row["name"],
                name_zh=row["name_zh"],
                exchange=row["exchange"],
                currency=row["currency"],
                sector=row["sector"],
                index_membership=row["index_membership"],
                tradable=_parse_bool(row["tradable"]),
                lot_size=int(row["lot_size"]),
            )
            for row in rows
            if row["index_membership"] == index_id
        ]

    def sync_bars(
        self,
        symbols: list[str],
        market: Market,
        start: date,
        end: date,
        timeframe: str = "1d",
    ) -> list[ProviderBar]:
        if timeframe != "1d":
            raise ValueError("CsvMarketDataProvider only supports daily bars")
        symbol_set = set(symbols)
        with self.bars_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        bars: list[ProviderBar] = []
        for row in rows:
            session = date.fromisoformat(row["date"])
            row_market = Market(row["market"])
            if row["symbol"] not in symbol_set or row_market is not market:
                continue
            if session < start or session > end:
                continue
            bars.append(
                ProviderBar(
                    symbol=row["symbol"],
                    market=row_market,
                    session=session,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    amount=float(row["amount"]),
                    adjusted=_parse_bool(row["adjusted"]),
                    suspended=_parse_bool(row["suspended"]),
                    limit_up=_parse_bool(row["limit_up"]),
                    limit_down=_parse_bool(row["limit_down"]),
                    source=self.name,
                )
            )
        return sorted(bars, key=lambda bar: (bar.symbol, bar.market.value, bar.session))
