from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest import TestCase

from stock_quantification.engine import InMemoryMarketDataProvider
from stock_quantification.models import AssetType, Bar, Instrument, Market
from stock_quantification.research_data import (
    BenchmarkConstituent,
    DataAvailability,
    FundamentalSnapshot,
    InMemoryBenchmarkProvider,
    InMemoryCorporateActionProvider,
    InMemoryFundamentalProvider,
    ResearchDataBundle,
    build_default_bundle,
)


class ResearchDataTests(TestCase):
    def test_fundamental_provider_returns_latest_snapshot(self) -> None:
        provider = InMemoryFundamentalProvider(
            [
                FundamentalSnapshot("US.AAPL", date(2026, 3, 31), {"profitability": Decimal("0.6")}),
                FundamentalSnapshot("US.AAPL", date(2026, 4, 2), {"profitability": Decimal("0.8")}),
            ]
        )
        snapshot = provider.get_snapshot("US.AAPL", date(2026, 4, 3))
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.metrics["profitability"], Decimal("0.8"))

    def test_benchmark_provider_normalizes_constituent_weights(self) -> None:
        provider = InMemoryBenchmarkProvider(
            [
                BenchmarkConstituent("SPX", "US.AAPL", Decimal("60"), date(2026, 4, 2)),
                BenchmarkConstituent("SPX", "US.MSFT", Decimal("40"), date(2026, 4, 2)),
            ]
        )
        weights = provider.get_weights("SPX", date(2026, 4, 3))
        self.assertEqual(weights["US.AAPL"], Decimal("0.6"))
        self.assertEqual(weights["US.MSFT"], Decimal("0.4"))

    def test_bundle_enriches_instruments_with_fundamentals(self) -> None:
        instrument = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        bundle = ResearchDataBundle(
            market_data_provider=InMemoryMarketDataProvider([instrument], {"US.AAPL": []}),
            fundamental_provider=InMemoryFundamentalProvider(
                [FundamentalSnapshot("US.AAPL", date(2026, 4, 2), {"quality": Decimal("0.9")})]
            ),
            benchmark_provider=InMemoryBenchmarkProvider([]),
            corporate_action_provider=InMemoryCorporateActionProvider([]),
        )
        enriched = bundle.enrich_instruments([instrument], date(2026, 4, 3))
        self.assertEqual(enriched[0].attributes["quality"], Decimal("0.9"))

    def test_build_default_bundle_uses_point_in_time_safe_metrics_and_marks_benchmark_unavailable(self) -> None:
        instrument = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        bars = [
            self._bar("US.AAPL", date(2026, 3, 10), "100", "1000"),
            self._bar("US.AAPL", date(2026, 3, 11), "102", "1000"),
            self._bar("US.AAPL", date(2026, 3, 12), "104", "1000"),
            self._bar("US.AAPL", date(2026, 3, 13), "106", "1000"),
            self._bar("US.AAPL", date(2026, 3, 16), "108", "1000"),
            self._bar("US.AAPL", date(2026, 3, 17), "110", "1000"),
            self._bar("US.AAPL", date(2026, 3, 18), "112", "1000"),
            self._bar("US.AAPL", date(2026, 3, 19), "114", "1000"),
            self._bar("US.AAPL", date(2026, 3, 20), "116", "1000"),
            self._bar("US.AAPL", date(2026, 3, 21), "118", "1000"),
            self._bar("US.AAPL", date(2026, 3, 24), "120", "1000"),
            self._bar("US.AAPL", date(2026, 3, 25), "122", "1000"),
            self._bar("US.AAPL", date(2026, 3, 26), "124", "1000"),
            self._bar("US.AAPL", date(2026, 3, 27), "126", "1000"),
            self._bar("US.AAPL", date(2026, 3, 28), "128", "1000"),
            self._bar("US.AAPL", date(2026, 3, 31), "130", "1000"),
            self._bar("US.AAPL", date(2026, 4, 1), "132", "1000"),
        ]
        provider = InMemoryMarketDataProvider([instrument], {"US.AAPL": bars})
        bundle = build_default_bundle(provider, Market.US, "SPX", date(2026, 4, 3))
        snapshot = bundle.fundamental_provider.get_snapshot("US.AAPL", date(2026, 4, 3))
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.metrics["latest_price"], Decimal("132"))
        self.assertIn("price_return_5", snapshot.metrics)
        self.assertNotIn("profitability", snapshot.metrics)
        self.assertNotIn("quality", snapshot.metrics)
        self.assertEqual(bundle.benchmark_status(Market.US, date(2026, 4, 3)), DataAvailability.UNAVAILABLE)
        self.assertEqual(bundle.benchmark_weights(Market.US, date(2026, 4, 3)), {})
        self.assertEqual(
            bundle.corporate_action_status("US.AAPL", date(2026, 4, 1), date(2026, 4, 3)),
            DataAvailability.UNAVAILABLE,
        )

    def _bar(self, instrument_id: str, day: date, close: str, turnover: str) -> Bar:
        close_value = Decimal(close)
        turnover_value = Decimal(turnover)
        return Bar(
            instrument_id=instrument_id,
            timestamp=datetime.combine(day, datetime.max.time()),
            open=close_value,
            close=close_value,
            high=close_value,
            low=close_value,
            volume=int(turnover),
            turnover=turnover_value,
            adjustment_flag="RAW",
        )
