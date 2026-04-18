from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from unittest import TestCase
from dataclasses import replace

from stock_quantification.engine import InMemoryMarketDataProvider
from stock_quantification.models import AssetType, Bar, Instrument, Market
from stock_quantification.pipeline import (
    ResearchPipeline,
    FeatureConfig,
    build_us_quality_momentum_blueprint,
)


def _build_bars(instrument_id: str, start_price: Decimal, start_dt: datetime, days: int, step: Decimal, turnover: Decimal):
    bars = []
    price = start_price
    for index in range(days):
        current_dt = start_dt + timedelta(days=index)
        bars.append(
            Bar(
                instrument_id=instrument_id,
                timestamp=current_dt,
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price + step,
                volume=1000000,
                turnover=turnover,
            )
        )
        price += step
    return bars


class SectorNeutralizationTests(TestCase):
    def setUp(self) -> None:
        self.as_of = datetime(2026, 4, 3, 15, 0, 0)
        start_dt = self.as_of - timedelta(days=69)
        
        # Sector A: High profitability (0.8, 0.9)
        # Sector B: Low profitability (0.1, 0.2)
        instruments = [
            Instrument("A1", Market.US, "A1", AssetType.COMMON_STOCK, "USD", "NASDAQ",
                       attributes={"listed_days": 2000, "sector": "SectorA", "profitability": "0.8"}),
            Instrument("A2", Market.US, "A2", AssetType.COMMON_STOCK, "USD", "NASDAQ",
                       attributes={"listed_days": 2000, "sector": "SectorA", "profitability": "0.9"}),
            Instrument("B1", Market.US, "B1", AssetType.COMMON_STOCK, "USD", "NYSE",
                       attributes={"listed_days": 2000, "sector": "SectorB", "profitability": "0.1"}),
            Instrument("B2", Market.US, "B2", AssetType.COMMON_STOCK, "USD", "NYSE",
                       attributes={"listed_days": 2000, "sector": "SectorB", "profitability": "0.2"}),
        ]
        
        bars = {
            "A1": _build_bars("A1", Decimal("100"), start_dt, 70, Decimal("0.1"), Decimal("1000000000")),
            "A2": _build_bars("A2", Decimal("100"), start_dt, 70, Decimal("0.1"), Decimal("1000000000")),
            "B1": _build_bars("B1", Decimal("100"), start_dt, 70, Decimal("0.1"), Decimal("1000000000")),
            "B2": _build_bars("B2", Decimal("100"), start_dt, 70, Decimal("0.1"), Decimal("1000000000")),
        }
        self.data_provider = InMemoryMarketDataProvider(instruments, bars)

    def test_global_standardization_has_sector_bias(self) -> None:
        # Without sector neutralization
        blueprint = build_us_quality_momentum_blueprint(
            allowed_instrument_ids=("A1", "A2", "B1", "B2"),
        )
        blueprint = replace(blueprint, feature_config=replace(blueprint.feature_config, neutralize_by_sector=False))
        
        result = ResearchPipeline(self.data_provider).run(blueprint, self.as_of)
        
        features = {f.instrument_id: f.standardized["profitability"] for f in result.features}
        
        # In global standardization, Sector A (high raw) should have positive Z-scores, 
        # Sector B (low raw) should have negative Z-scores.
        self.assertGreater(features["A1"], 0)
        self.assertGreater(features["A2"], 0)
        self.assertLess(features["B1"], 0)
        self.assertLess(features["B2"], 0)

    def test_sector_neutralization_removes_sector_bias(self) -> None:
        # With sector neutralization
        blueprint = build_us_quality_momentum_blueprint(
            allowed_instrument_ids=("A1", "A2", "B1", "B2"),
        )
        blueprint = replace(blueprint, feature_config=replace(blueprint.feature_config, neutralize_by_sector=True))
        
        result = ResearchPipeline(self.data_provider).run(blueprint, self.as_of)
        
        features = {f.instrument_id: f.standardized["profitability"] for f in result.features}
        
        # After sector neutralization:
        # A1 (0.8) vs A2 (0.9) -> A1 should be -1.0, A2 should be 1.0 (mean 0.85, std 0.05 approx)
        # B1 (0.1) vs B2 (0.2) -> B1 should be -1.0, B2 should be 1.0 (mean 0.15, std 0.05 approx)
        
        self.assertAlmostEqual(float(features["A1"]), -1.0, places=2)
        self.assertAlmostEqual(float(features["A2"]), 1.0, places=2)
        self.assertAlmostEqual(float(features["B1"]), -1.0, places=2)
        self.assertAlmostEqual(float(features["B2"]), 1.0, places=2)
        
        # The key point: Sector B's B2 (low raw) now has the SAME Z-score as Sector A's A2 (high raw)
        self.assertEqual(features["A2"], features["B2"])
