from __future__ import annotations

import os
import time
from datetime import date
from typing import Any, Callable

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument
from evoquant.providers.yahoo import YahooFinanceProvider


class TiingoProvider:
    name = "tiingo"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        request_delay_seconds: float | None = None,
        retry_backoff_seconds: float | None = None,
        max_retries: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key or os.environ.get("TIINGO_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("TIINGO_API_KEY is required for Tiingo market data")
        self.request_delay_seconds = _float_env(
            "TIINGO_REQUEST_DELAY_SECONDS",
            request_delay_seconds,
            default=0.0,
        )
        self.retry_backoff_seconds = _float_env(
            "TIINGO_RETRY_BACKOFF_SECONDS",
            retry_backoff_seconds,
            default=5.0,
        )
        self.max_retries = _int_env("TIINGO_MAX_RETRIES", max_retries, default=2)
        self.sleep = sleep

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
            rows = self._request_symbol_prices(
                requests,
                symbol,
                start,
                end,
            )
            for row in rows:
                bar = _row_to_bar(symbol, row)
                if bar is not None:
                    bars.append(bar)
            if self.request_delay_seconds > 0:
                self.sleep(self.request_delay_seconds)
        return bars

    def _request_symbol_prices(self, requests, symbol: str, start: date, end: date):
        for attempt in range(self.max_retries + 1):
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
            if getattr(response, "status_code", None) == 429 and attempt < self.max_retries:
                self.sleep(_retry_after_seconds(response, self.retry_backoff_seconds))
                continue
            response.raise_for_status()
            return response.json()
        return []


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


def _float_env(name: str, value: float | None, *, default: float) -> float:
    if value is not None:
        return float(value)
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _int_env(name: str, value: int | None, *, default: int) -> int:
    if value is not None:
        return int(value)
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _retry_after_seconds(response, default: float) -> float:
    retry_after = getattr(response, "headers", {}).get("Retry-After")
    try:
        return float(retry_after)
    except (TypeError, ValueError):
        return default
