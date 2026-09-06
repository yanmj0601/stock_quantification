from __future__ import annotations

from datetime import date, timedelta
import pandas as pd
from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument

# 猴子补丁：兼容老旧 Baostock 库在 Pandas 2.x 中调用已废弃的 DataFrame.append 方法
if not hasattr(pd.DataFrame, "append"):
    def _patch_append(self, other, ignore_index=False):
        return pd.concat([self, other], ignore_index=ignore_index)
    pd.DataFrame.append = _patch_append


def _is_cn_stock(exchange: str, symbol: str) -> bool:
    if len(symbol) != 6:
        return False
    if exchange == "SH":
        # 60xxxx (主板), 688xxx (科创板)；排除外币计价的 B 股。
        return symbol.startswith(("60", "688"))
    elif exchange == "SZ":
        # 000–003 (主板/中小板), 300/301 (创业板)；排除 B 股。
        return symbol.startswith(("000", "001", "002", "003", "300", "301"))
    return False


class BaostockProvider:
    name = "baostock"

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        if index_id not in ("CSI300", "ALL"):
            raise ValueError("BaostockProvider only supports CSI300 or ALL instruments")
        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"Baostock login failed: {lg.error_msg}")
        try:
            instruments: list[ProviderInstrument] = []
            if index_id == "CSI300":
                rs = bs.query_hs300_stocks()
                if rs.error_code != "0":
                    raise RuntimeError(f"Baostock query_hs300_stocks failed: {rs.error_msg}")
                rows = rs.get_data().to_dict("records")
            else:
                # 动态向前回溯寻找最近有数据的有效交易日（最深回溯7天）
                target_day = date.today()
                rows = []
                for _ in range(7):
                    rs = bs.query_all_stock(day=target_day.strftime("%Y-%m-%d"))
                    if rs.error_code == "0":
                        df = rs.get_data()
                        if not df.empty:
                            rows = df.to_dict("records")
                            break
                    target_day -= timedelta(days=1)
                if not rows:
                    raise RuntimeError("Failed to query all stocks from Baostock (empty dataset)")

            for row in rows:
                code = row["code"]
                name = row.get("code_name", "") or row.get("code", "")
                code_parts = code.split(".")
                symbol = code_parts[1]
                exchange = code_parts[0].upper()

                # 如果是全量同步模式，则需利用规则筛选出个股，过滤指数和债券
                if index_id == "ALL" and not _is_cn_stock(exchange, symbol):
                    continue

                instruments.append(
                    ProviderInstrument(
                        symbol=symbol,
                        market=Market.CN,
                        name=name,
                        name_zh=name,
                        exchange=exchange,
                        currency="CNY",
                        sector="",
                        index_membership=index_id,
                        tradable=True,
                        lot_size=100,
                    )
                )
            return instruments
        finally:
            bs.logout()

    def sync_bars(
        self,
        symbols: list[str],
        market: Market,
        start: date,
        end: date,
        timeframe: str = "1d",
    ) -> list[ProviderBar]:
        if market is not Market.CN:
            raise ValueError("BaostockProvider only supports CN market bars")
        if timeframe != "1d":
            raise ValueError("BaostockProvider only supports daily bars")

        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"Baostock login failed: {lg.error_msg}")

        bars: list[ProviderBar] = []
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
        try:
            for symbol in symbols:
                if symbol.startswith("6") or symbol.startswith("9"):
                    bs_code = f"sh.{symbol}"
                else:
                    bs_code = f"sz.{symbol}"

                rs = bs.query_history_k_data_plus(
                    code=bs_code,
                    fields="date,open,high,low,close,volume,amount",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="2",
                )
                if rs.error_code != "0":
                    continue

                for row in rs.get_data().to_dict("records"):
                    if not row.get("close"):
                        continue
                    session = date.fromisoformat(row["date"])
                    close = float(row["close"])
                    volume = float(row.get("volume") or 0)
                    amount = float(row.get("amount") or (close * volume))
                    bars.append(
                        ProviderBar(
                            symbol=symbol,
                            market=Market.CN,
                            session=session,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=close,
                            volume=volume,
                            amount=amount,
                            adjusted=True,
                            suspended=False,
                            limit_up=False,
                            limit_down=False,
                            source=self.name,
                        )
                    )
            return bars
        finally:
            bs.logout()
