from __future__ import annotations

from datetime import date

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument


class YahooFinanceProvider:
    name = "yfinance"

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        if index_id != "SP500":
            raise ValueError("YahooFinanceProvider only supports SP500 instruments")
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("pandas is required for S&P 500 instrument sync") from exc

        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
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
            threads=False,
        )
        bars: list[ProviderBar] = []
        if frame.empty:
            return bars

        for symbol in symbols:
            symbol_frame = _symbol_frame(frame, symbol)
            for index, row in symbol_frame.iterrows():
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
