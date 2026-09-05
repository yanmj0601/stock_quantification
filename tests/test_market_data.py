from datetime import date

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument
from evoquant.services.market_data import MarketDataService
from evoquant.storage import PostgreSQLStore


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        bars: list[ProviderBar],
        instruments: list[ProviderInstrument] | None = None,
    ):
        self.bars = bars
        self.instruments = instruments or []
        self.calls = []

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        return self.instruments

    def sync_bars(self, symbols, market, start, end, timeframe="1d"):
        self.calls.append((tuple(symbols), market, start, end, timeframe))
        return [
            bar
            for bar in self.bars
            if bar.symbol in symbols and bar.market is market and start <= bar.session <= end
        ]


def _bar(symbol: str, session: date, close: float = 10.0) -> ProviderBar:
    return ProviderBar(
        symbol=symbol,
        market=Market.US,
        session=session,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1000,
        amount=close * 1000,
        adjusted=True,
        suspended=False,
        limit_up=False,
        limit_down=False,
        source="fake",
    )


def test_sync_bars_records_coverage_and_persists_bars(tmp_path):
    service = MarketDataService(PostgreSQLStore())
    provider = FakeProvider([_bar("AAPL", date(2026, 1, 2))])

    job = service.sync_bars(
        provider,
        ["AAPL", "MSFT"],
        Market.US,
        date(2026, 1, 1),
        date(2026, 1, 5),
    )
    bars = service.list_bars(Market.US, ["AAPL"], date(2026, 1, 1), date(2026, 1, 5))

    assert job.total_symbols == 2
    assert job.success_symbols == 1
    assert job.failed_symbols == 1
    assert job.coverage == 0.5
    assert bars[0].symbol == "AAPL"
    assert bars[0].close == 10.0


def test_list_sync_jobs_exposes_timing_and_operator_message(tmp_path):
    service = MarketDataService(PostgreSQLStore())
    provider = FakeProvider([_bar("AAPL", date(2026, 1, 2))])

    created = service.sync_bars(
        provider,
        ["AAPL", "MSFT"],
        Market.US,
        date(2026, 1, 1),
        date(2026, 1, 5),
    )
    listed = service.list_sync_jobs()[0]

    assert listed.id == created.id
    assert listed.started_at
    assert listed.finished_at
    assert listed.message == "1/2 symbols synced; failures: MSFT"


def test_incremental_sync_starts_after_latest_cached_date(tmp_path):
    service = MarketDataService(PostgreSQLStore())
    initial_provider = FakeProvider([_bar("AAPL", date(2026, 1, 2))])
    update_provider = FakeProvider([_bar("AAPL", date(2026, 1, 3), close=11.0)])

    service.sync_bars(
        initial_provider,
        ["AAPL"],
        Market.US,
        date(2026, 1, 1),
        date(2026, 1, 2),
    )
    service.incremental_sync(update_provider, ["AAPL"], Market.US, end=date(2026, 1, 3))

    assert update_provider.calls[0][2] == date(2026, 1, 3)
    bars = service.list_bars(Market.US, ["AAPL"], date(2026, 1, 1), date(2026, 1, 3))
    assert [bar.close for bar in bars] == [10.0, 11.0]
