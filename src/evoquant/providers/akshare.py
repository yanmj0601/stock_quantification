from __future__ import annotations

from datetime import date

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument


class AkshareProvider:
    name = "akshare"

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        if index_id != "CSI300":
            raise ValueError("AkshareProvider only supports CSI300 instruments")
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("akshare is required for CSI 300 instrument sync") from exc
        if not hasattr(ak, "index_stock_cons_csindex"):
            raise RuntimeError("akshare.index_stock_cons_csindex is required")

        frame = ak.index_stock_cons_csindex(symbol="000300")
        instruments: list[ProviderInstrument] = []
        for row in frame.to_dict("records"):
            symbol = str(row.get("成分券代码") or row.get("品种代码") or row.get("code"))
            name = str(row.get("成分券名称") or row.get("品种名称") or row.get("name") or symbol)
            exchange = str(row.get("交易所") or "")
            instruments.append(
                ProviderInstrument(
                    symbol=symbol,
                    market=Market.CN,
                    name=name,
                    name_zh=name,
                    exchange=exchange,
                    currency="CNY",
                    sector=str(row.get("行业") or ""),
                    index_membership="CSI300",
                    tradable=True,
                    lot_size=100,
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
        if market is not Market.CN:
            raise ValueError("AkshareProvider only supports CN market bars")
        if timeframe != "1d":
            raise ValueError("AkshareProvider only supports daily bars in v2")
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("akshare is required for A-share bar sync") from exc

        bars: list[ProviderBar] = []
        start_date = start.strftime("%Y%m%d")
        end_date = end.strftime("%Y%m%d")
        for symbol in symbols:
            frame = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            for row in frame.to_dict("records"):
                session = date.fromisoformat(str(row["日期"]))
                close = float(row["收盘"])
                volume = float(row.get("成交量", 0))
                amount = float(row.get("成交额", close * volume))
                bars.append(
                    ProviderBar(
                        symbol=symbol,
                        market=Market.CN,
                        session=session,
                        open=float(row["开盘"]),
                        high=float(row["最高"]),
                        low=float(row["最低"]),
                        close=close,
                        volume=volume,
                        amount=amount,
                        adjusted=True,
                        suspended=False,
                        limit_up=bool(row.get("涨停", False)),
                        limit_down=bool(row.get("跌停", False)),
                        source=self.name,
                    )
                )
        return bars
