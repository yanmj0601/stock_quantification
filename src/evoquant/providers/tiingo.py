from __future__ import annotations

import os
from datetime import date
from typing import Any

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument
from evoquant.providers.yahoo import YahooFinanceProvider


class TiingoProvider:
    name = "tiingo"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("TIINGO_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("TIINGO_API_KEY is required for Tiingo market data")

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        return YahooFinanceProvider().sync_instruments(index_id)

    def sync_bars(
        self,
        symbols: list[str],
        market: Market,
        start: date,
        end: date,
        timeframe: str = "1d",
    ) -> list[ProviderBar]:
        if market is not Market.US:
            raise ValueError("TiingoProvider only supports US market bars")
        if timeframe != "1d":
            raise ValueError("TiingoProvider only supports daily bars in v2")
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests is required for Tiingo bar sync") from exc

        bars: list[ProviderBar] = []
        for symbol in symbols:
            response = requests.get(
                f"https://api.tiingo.com/tiingo/daily/{symbol.lower()}/prices",
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json",
                },
                params={
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "resampleFreq": "daily",
                },
                timeout=20,
            )
            response.raise_for_status()
            for row in response.json():
                bar = _row_to_bar(symbol, row)
                if bar is not None:
                    bars.append(bar)
        return bars


def _row_to_bar(symbol: str, row: dict[str, Any]) -> ProviderBar | None:
    try:
        session = date.fromisoformat(str(row["date"])[:10])
        open_price = _float(row.get("adjOpen", row.get("open")))
        high = _float(row.get("adjHigh", row.get("high")))
        low = _float(row.get("adjLow", row.get("low")))
        close = _float(row.get("adjClose", row.get("close")))
        volume = _float(row.get("adjVolume", row.get("volume")))
    except (KeyError, TypeError, ValueError):
        return None
    return ProviderBar(
        symbol=symbol,
        market=Market.US,
        session=session,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=close * volume,
        adjusted=True,
        suspended=False,
        limit_up=False,
        limit_down=False,
        source=TiingoProvider.name,
    )


def _float(value: Any) -> float:
    if value is None:
        raise ValueError("missing numeric value")
    return float(value)
