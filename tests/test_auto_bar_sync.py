from datetime import date, datetime
from zoneinfo import ZoneInfo

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar
from evoquant.services.auto_sync import AutoBarSyncService
from evoquant.services.instruments import InstrumentMaster, InstrumentRecord
from evoquant.services.market_data import MarketDataService
from evoquant.storage import PostgreSQLStore


class Provider:
    name = "fake"

    def sync_instruments(self, index_id: str):
        return []

    def sync_bars(self, symbols, market, start, end, timeframe="1d"):
        return [
            ProviderBar(
                symbol=symbol,
                market=market,
                session=end,
                open=10,
                high=11,
                low=9,
                close=10,
                volume=1000,
                amount=10000,
                adjusted=True,
                suspended=False,
                limit_up=False,
                limit_down=False,
                source="fake",
            )
            for symbol in symbols
        ]


def _instrument(symbol: str) -> InstrumentRecord:
    return InstrumentRecord(
        symbol=symbol,
        market=Market.US,
        name=symbol,
        name_zh=symbol,
        exchange="NYSE",
        currency="USD",
        sector="",
        index_membership="SP500",
        tradable=True,
        lot_size=1,
    )


def test_auto_sync_creates_incremental_job_after_market_close_once_per_day(tmp_path):
    store = PostgreSQLStore()
    InstrumentMaster(store).upsert_many([_instrument("AAA")])
    MarketDataService(store).sync_bars(Provider(), ["AAA"], Market.US, date(2026, 1, 1), date(2026, 1, 2))
    service = AutoBarSyncService(store, provider_factory=lambda market: Provider())

    created = service.run_due_once(
        now=datetime(2026, 1, 5, 17, 0, tzinfo=ZoneInfo("America/New_York"))
    )
    duplicate = service.run_due_once(
        now=datetime(2026, 1, 5, 17, 30, tzinfo=ZoneInfo("America/New_York"))
    )

    assert len(created) == 1
    assert created[0].mode == "incremental"
    assert created[0].status == "success"
    assert duplicate == []


def test_auto_sync_skips_market_without_initial_bars(tmp_path):
    store = PostgreSQLStore()
    InstrumentMaster(store).upsert_many([_instrument("AAA")])
    service = AutoBarSyncService(store, provider_factory=lambda market: Provider())

    created = service.run_due_once(
        now=datetime(2026, 1, 5, 17, 0, tzinfo=ZoneInfo("America/New_York"))
    )

    assert created == []
