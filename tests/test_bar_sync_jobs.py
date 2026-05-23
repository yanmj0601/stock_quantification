from datetime import date

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar
from evoquant.services.bar_sync import BarSyncJobService
from evoquant.services.instruments import InstrumentMaster, InstrumentRecord
from evoquant.services.market_data import MarketDataService
from evoquant.storage import SQLiteStore


class RecordingProvider:
    name = "fake"

    def __init__(self):
        self.calls = []

    def sync_instruments(self, index_id: str):
        return []

    def sync_bars(self, symbols, market, start, end, timeframe="1d"):
        self.calls.append((tuple(symbols), market, start, end, timeframe))
        bars = []
        for symbol in symbols:
            bars.append(
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
            )
        return bars


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


def test_initial_bar_sync_job_runs_in_batches_and_persists_progress(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    InstrumentMaster(store).upsert_many([_instrument("AAA"), _instrument("BBB"), _instrument("CCC")])
    provider = RecordingProvider()
    service = BarSyncJobService(store)

    job = service.create_job(Market.US, mode="initial", batch_size=2)
    completed = service.run_job(job.id, provider, today=date(2026, 1, 10))

    assert [call[0] for call in provider.calls] == [("AAA", "BBB"), ("CCC",)]
    assert provider.calls[0][2] == date(2021, 1, 11)
    assert completed.status == "success"
    assert completed.completed_symbols == 3
    assert completed.success_symbols == 3
    assert completed.progress == 1.0
    assert len(MarketDataService(store).list_bars(Market.US, ["AAA", "BBB", "CCC"], date(2026, 1, 1), date(2026, 1, 10))) == 3


def test_incremental_bar_sync_job_starts_after_latest_cached_session(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    InstrumentMaster(store).upsert_many([_instrument("AAA")])
    provider = RecordingProvider()
    market_data = MarketDataService(store)
    market_data.sync_bars(provider, ["AAA"], Market.US, date(2026, 1, 1), date(2026, 1, 2))
    provider.calls.clear()

    job = BarSyncJobService(store).create_job(Market.US, mode="incremental", batch_size=10)
    BarSyncJobService(store).run_job(job.id, provider, today=date(2026, 1, 5))

    assert provider.calls[0][2] == date(2026, 1, 3)
    assert provider.calls[0][3] == date(2026, 1, 5)
