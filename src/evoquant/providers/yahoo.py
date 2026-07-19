from __future__ import annotations

import math
from datetime import date
from io import StringIO

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument


class YahooFinanceProvider:
    name = "yfinance"

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        if index_id not in {"SP500", "ALL"}:
            raise ValueError("YahooFinanceProvider supports SP500 or ALL instruments")
        try:
            import pandas as pd
            import requests
        except ImportError as exc:
            raise RuntimeError("pandas and requests are required for Yahoo instrument sync") from exc

        if index_id == "ALL":
            try:
                response = requests.get(
                    "https://www.sec.gov/files/company_tickers.json",
                    headers={"User-Agent": "EvoQuant Research Team admin@evoquant.com"},
                    timeout=20,
                )
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                raise RuntimeError(f"SEC US instrument sync failed: {exc}") from exc
            
            instruments: list[ProviderInstrument] = []
            for item in data.values():
                symbol = str(item["ticker"]).strip().upper()
                if symbol.isalpha() and len(symbol) <= 4:
                    instruments.append(
                        ProviderInstrument(
                            symbol=symbol,
                            market=Market.US,
                            name=str(item["title"]),
                            name_zh=symbol,
                            exchange="US",
                            currency="USD",
                            sector="General",
                            index_membership="ALL",
                            tradable=True,
                            lot_size=1,
                        )
                    )
            return instruments

        try:
            response = requests.get(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                headers={"User-Agent": "EvoQuant research data sync/0.1"},
                timeout=20,
            )
            response.raise_for_status()
            tables = pd.read_html(StringIO(response.text))
        except Exception as exc:
            raise RuntimeError(f"S&P 500 instrument sync failed: {exc}") from exc
        frame = tables[0]
        instruments: list[ProviderInstrument] = []
        for row in frame.to_dict("records"):
            symbol = str(row["Symbol"]).replace(".", "-")
            instruments.append(
                ProviderInstrument(
                    symbol=symbol,
                    market=Market.US,
                    name=str(row["Security"]),
                    name_zh=symbol,
                    exchange=str(row.get("Exchange", "")),
                    currency="USD",
                    sector=str(row.get("GICS Sector", "")),
                    index_membership="SP500",
                    tradable=True,
                    lot_size=1,
                )
            )
        return instruments

    def sync_bars(
        self,
        symbols: list[str],
        market: Market,
        start: date,
        end: date,
        timeframe: str = "1d",
    ) -> list[ProviderBar]:
        if market is not Market.US:
            raise ValueError("YahooFinanceProvider only supports US market bars")
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is required for Yahoo bar sync") from exc

        if not symbols:
            return []

        frame = yf.download(
            tickers=" ".join(symbols),
            start=start.isoformat(),
            end=end.isoformat(),
            interval=timeframe,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
            timeout=8,
        )
        bars: list[ProviderBar] = []
        if frame.empty:
            return bars

        for symbol in symbols:
            symbol_frame = _symbol_frame(frame, symbol)
            for index, row in symbol_frame.iterrows():
                if _has_missing_price_row(row):
                    continue
                session = index.date()
                close = float(row.get("Adj Close", row["Close"]))
                volume = float(row["Volume"])
                bars.append(
                    ProviderBar(
                        symbol=symbol,
                        market=Market.US,
                        session=session,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=close,
                        volume=volume,
                        amount=close * volume,
                        adjusted="Adj Close" in row,
                        suspended=False,
                        limit_up=False,
                        limit_down=False,
                        source=self.name,
                    )
                )
        return bars


def _symbol_frame(frame, symbol: str):
    if hasattr(frame.columns, "nlevels") and frame.columns.nlevels > 1:
        if symbol not in frame.columns.get_level_values(0):
            return frame.iloc[0:0]
        return frame[symbol]
    return frame


def _has_missing_price_row(row) -> bool:
    for field in ("Open", "High", "Low", "Close", "Volume"):
        value = row.get(field)
        if value is None:
            return True
        try:
            if math.isnan(float(value)):
                return True
        except (TypeError, ValueError):
            return True
    adjusted_close = row.get("Adj Close")
    if adjusted_close is not None:
        try:
            return math.isnan(float(adjusted_close))
        except (TypeError, ValueError):
            return True
    return False
