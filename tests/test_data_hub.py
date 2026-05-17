from datetime import date

import pytest

from evoquant.domain import Bar, Instrument, Market
from evoquant.services.data_hub import DataHub
from evoquant.storage import SQLiteStore


def test_data_hub_registers_dataset_and_reports_quality(tmp_path):
    hub = DataHub(SQLiteStore(tmp_path / "state.db"))
    instrument = Instrument("AAPL", Market.US, "equity", "USD", "NASDAQ", 1, True)
    bars = [
        Bar("AAPL", Market.US, date(2026, 1, 2), 100, 105, 99, 104, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 5), 104, 106, 103, 105, 1200, True, "fixture"),
    ]

    dataset = hub.register_dataset("us_fixture_daily", [instrument], bars)
    report = hub.check_quality(dataset.id)

    assert dataset.id.startswith("ds_")
    assert report.missing_bars == 0
    assert report.duplicate_bars == 0
    assert report.price_anomalies == 0


def test_data_hub_quality_counts_duplicate_bars(tmp_path):
    hub = DataHub(SQLiteStore(tmp_path / "state.db"))
    instrument = Instrument("AAPL", Market.US, "equity", "USD", "NASDAQ", 1, True)
    bars = [
        Bar("AAPL", Market.US, date(2026, 1, 2), 100, 105, 99, 104, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 2), 101, 106, 100, 105, 1000, True, "fixture"),
    ]

    dataset = hub.register_dataset("us_fixture_daily", [instrument], bars)
    report = hub.check_quality(dataset.id)

    assert report.duplicate_bars == 1


def test_data_hub_quality_counts_missing_bars_relative_to_market_sessions(tmp_path):
    hub = DataHub(SQLiteStore(tmp_path / "state.db"))
    aapl = Instrument("AAPL", Market.US, "equity", "USD", "NASDAQ", 1, True)
    msft = Instrument("MSFT", Market.US, "equity", "USD", "NASDAQ", 1, True)
    bars = [
        Bar("AAPL", Market.US, date(2026, 1, 2), 100, 105, 99, 104, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 5), 104, 106, 103, 105, 1200, True, "fixture"),
        Bar("MSFT", Market.US, date(2026, 1, 2), 200, 205, 199, 204, 1000, True, "fixture"),
    ]

    dataset = hub.register_dataset("us_fixture_daily", [aapl, msft], bars)
    report = hub.check_quality(dataset.id)

    assert report.missing_bars == 1


def test_data_hub_quality_counts_price_anomalies(tmp_path):
    hub = DataHub(SQLiteStore(tmp_path / "state.db"))
    instrument = Instrument("AAPL", Market.US, "equity", "USD", "NASDAQ", 1, True)
    bars = [
        Bar("AAPL", Market.US, date(2026, 1, 2), 100, 99, 105, 104, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 5), 0, 106, 103, 105, 1200, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 6), 104, 106, 103, 0, 1200, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 7), 104, 106, 103, 105, -1, True, "fixture"),
    ]

    dataset = hub.register_dataset("us_fixture_daily", [instrument], bars)
    report = hub.check_quality(dataset.id)

    assert report.price_anomalies == 4


def test_data_hub_quality_counts_expanded_ohlc_anomalies_once_per_bar(tmp_path):
    hub = DataHub(SQLiteStore(tmp_path / "state.db"))
    instrument = Instrument("AAPL", Market.US, "equity", "USD", "NASDAQ", 1, True)
    bars = [
        Bar("AAPL", Market.US, date(2026, 1, 2), 100, 105, 99, 104, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 5), 100, 0, 99, 104, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 6), 100, 105, 0, 104, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 7), 98, 105, 99, 104, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 8), 100, 105, 99, 106, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 9), -1, 0, 99, 106, -1, True, "fixture"),
    ]

    dataset = hub.register_dataset("us_fixture_daily", [instrument], bars)
    report = hub.check_quality(dataset.id)

    assert report.price_anomalies == 5


def test_data_hub_quality_raises_for_unknown_dataset(tmp_path):
    hub = DataHub(SQLiteStore(tmp_path / "state.db"))

    with pytest.raises(KeyError):
        hub.check_quality("ds_missing")
