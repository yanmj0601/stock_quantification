from __future__ import annotations

from datetime import date

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument


class AkshareProvider:
    name = "akshare"

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        raise NotImplementedError("CSI 300 instrument sync is implemented in Task 3")

    def sync_bars(
        self,
        symbols: list[str],
        market: Market,
        start: date,
        end: date,
        timeframe: str = "1d",
    ) -> list[ProviderBar]:
        raise NotImplementedError("AKShare bar sync is implemented in Task 3")
