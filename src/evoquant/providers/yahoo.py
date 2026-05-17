from __future__ import annotations

from datetime import date

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument


class YahooFinanceProvider:
    name = "yfinance"

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        raise NotImplementedError("S&P 500 instrument sync is implemented in Task 3")

    def sync_bars(
        self,
        symbols: list[str],
        market: Market,
        start: date,
        end: date,
        timeframe: str = "1d",
    ) -> list[ProviderBar]:
        raise NotImplementedError("Yahoo bar sync is implemented in Task 3")
