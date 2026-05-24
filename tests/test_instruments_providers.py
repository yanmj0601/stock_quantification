from datetime import date
import sys
from types import SimpleNamespace

import pytest

from evoquant.domain import Market
from evoquant.providers.csv import CsvMarketDataProvider
from evoquant.providers.tiingo import TiingoProvider
from evoquant.providers.yahoo import YahooFinanceProvider
from evoquant.services.instruments import InstrumentMaster, InstrumentRecord
from evoquant.storage import SQLiteStore


def test_instrument_master_upserts_and_prefers_chinese_name(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    master = InstrumentMaster(store)

    master.upsert_many(
        [
            InstrumentRecord(
                symbol="AAPL",
                market=Market.US,
                name="Apple Inc.",
                name_zh="苹果公司",
                exchange="NASDAQ",
                currency="USD",
                sector="Technology",
                index_membership="SP500",
                tradable=True,
                lot_size=1,
            )
        ]
    )

    listed = master.list_by_market(Market.US)

    assert len(listed) == 1
    assert listed[0].symbol == "AAPL"
    assert listed[0].name_zh == "苹果公司"


def test_csv_market_data_provider_reads_instruments_and_bars(tmp_path):
    instruments = tmp_path / "instruments.csv"
    bars = tmp_path / "bars.csv"
    instruments.write_text(
        "symbol,market,name,name_zh,exchange,currency,sector,index_membership,tradable,lot_size\n"
        "AAPL,US,Apple Inc.,苹果公司,NASDAQ,USD,Technology,SP500,true,1\n",
        encoding="utf-8",
    )
    bars.write_text(
        "symbol,market,date,open,high,low,close,volume,amount,adjusted,suspended,limit_up,limit_down\n"
        "AAPL,US,2026-01-02,100,105,99,104,1000000,104000000,true,false,false,false\n",
        encoding="utf-8",
    )

    provider = CsvMarketDataProvider(instruments_path=instruments, bars_path=bars)

    loaded_instruments = provider.sync_instruments("SP500")
    loaded_bars = provider.sync_bars(
        ["AAPL"], Market.US, date(2026, 1, 1), date(2026, 1, 31)
    )

    assert loaded_instruments[0].name_zh == "苹果公司"
    assert loaded_bars[0].close == 104.0
    assert loaded_bars[0].amount == 104000000.0


def test_tiingo_provider_reads_adjusted_daily_bars(monkeypatch):
    calls: list[dict] = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "date": "2026-01-02T00:00:00.000Z",
                    "open": 100,
                    "high": 105,
                    "low": 99,
                    "close": 104,
                    "volume": 1000,
                    "adjOpen": 50,
                    "adjHigh": 52.5,
                    "adjLow": 49.5,
                    "adjClose": 52,
                    "adjVolume": 2000,
                }
            ]

    def fake_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return Response()

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=fake_get))

    bars = TiingoProvider(api_key="secret").sync_bars(
        ["AAPL"], Market.US, date(2026, 1, 1), date(2026, 1, 31)
    )

    assert calls[0]["url"] == "https://api.tiingo.com/tiingo/daily/aapl/prices"
    assert calls[0]["headers"]["Authorization"] == "Token secret"
    assert calls[0]["params"] == {
        "startDate": "2026-01-01",
        "endDate": "2026-01-31",
        "resampleFreq": "daily",
    }
    assert calls[0]["timeout"] == 20
    assert len(bars) == 1
    assert bars[0].symbol == "AAPL"
    assert bars[0].close == 52.0
    assert bars[0].volume == 2000.0
    assert bars[0].amount == 104000.0
    assert bars[0].source == "tiingo"


def test_tiingo_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TIINGO_API_KEY"):
        TiingoProvider()


def test_yahoo_provider_handles_single_symbol_multiindex_download(monkeypatch):
    pd = pytest.importorskip("pandas")
    columns = pd.MultiIndex.from_product(
        [["AAPL"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]],
        names=["Ticker", "Price"],
    )
    frame = pd.DataFrame(
        [[100.0, 105.0, 99.0, 104.0, 103.5, 1000.0]],
        index=pd.to_datetime(["2026-01-02"]),
        columns=columns,
    )
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda **_kwargs: frame),
    )

    bars = YahooFinanceProvider().sync_bars(
        ["AAPL"], Market.US, date(2026, 1, 1), date(2026, 1, 31)
    )

    assert len(bars) == 1
    assert bars[0].symbol == "AAPL"
    assert bars[0].close == 103.5
    assert bars[0].amount == 103500.0


def test_yahoo_provider_skips_rows_with_missing_ohlcv(monkeypatch):
    pd = pytest.importorskip("pandas")
    columns = pd.MultiIndex.from_product(
        [["AAPL"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]],
        names=["Ticker", "Price"],
    )
    frame = pd.DataFrame(
        [
            [100.0, 105.0, 99.0, 104.0, 103.5, 1000.0],
            [None, 106.0, 101.0, 105.0, 104.5, 1100.0],
        ],
        index=pd.to_datetime(["2026-01-02", "2026-01-03"]),
        columns=columns,
    )
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda **_kwargs: frame),
    )

    bars = YahooFinanceProvider().sync_bars(
        ["AAPL"], Market.US, date(2026, 1, 1), date(2026, 1, 31)
    )

    assert len(bars) == 1
    assert bars[0].session == date(2026, 1, 2)


def test_yahoo_provider_fetches_sp500_html_with_http_client(monkeypatch):
    pd = pytest.importorskip("pandas")
    calls: list[dict] = []

    class Response:
        text = "<table></table>"

        def raise_for_status(self):
            return None

    def fake_get(url, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return Response()

    def fake_read_html(html):
        assert "List_of_S%26P_500_companies" not in str(html)
        return [
            pd.DataFrame(
                [
                    {
                        "Symbol": "BRK.B",
                        "Security": "Berkshire Hathaway",
                        "GICS Sector": "Financials",
                    }
                ]
            )
        ]

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=fake_get))
    monkeypatch.setattr(pd, "read_html", fake_read_html)

    instruments = YahooFinanceProvider().sync_instruments("SP500")

    assert calls
    assert "User-Agent" in calls[0]["headers"]
    assert instruments[0].symbol == "BRK-B"
    assert instruments[0].name == "Berkshire Hathaway"
