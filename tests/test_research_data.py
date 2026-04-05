from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest import TestCase

from stock_quantification.engine import InMemoryMarketDataProvider
from stock_quantification.models import AssetType, Instrument, Market
from stock_quantification.research_data import (
    BenchmarkConstituent,
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

    def test_build_default_bundle_uses_equal_weight_benchmark(self) -> None:
        instruments = [
            Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ", attributes={"profitability": "0.7"}),
            Instrument("US.MSFT", Market.US, "MSFT", AssetType.COMMON_STOCK, "USD", "NASDAQ", attributes={"profitability": "0.8"}),
        ]
        provider = InMemoryMarketDataProvider(instruments, {"US.AAPL": [], "US.MSFT": []})
        bundle = build_default_bundle(provider, Market.US, "SPX", date(2026, 4, 3))
        weights = bundle.benchmark_weights(Market.US, date(2026, 4, 3))
        self.assertEqual(weights["US.AAPL"], Decimal("0.5"))
        self.assertEqual(weights["US.MSFT"], Decimal("0.5"))
