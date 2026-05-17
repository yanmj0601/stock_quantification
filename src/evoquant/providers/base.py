from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from evoquant.domain import Market


@dataclass(frozen=True)
class ProviderInstrument:
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


@dataclass(frozen=True)
class ProviderBar:
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


class MarketDataProvider(Protocol):
    name: str

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        raise NotImplementedError

    def sync_bars(
        self,
        symbols: list[str],
        market: Market,
        start: date,
        end: date,
        timeframe: str = "1d",
    ) -> list[ProviderBar]:
        raise NotImplementedError
