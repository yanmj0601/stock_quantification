from __future__ import annotations

from decimal import Decimal
from unittest import TestCase

from stock_quantification.models import Market
from stock_quantification.strategy_catalog import strategy_presets_for_market


class StrategyCatalogTests(TestCase):
    def test_cn_strategy_catalog_contains_mainstream_long_only_presets(self) -> None:
        presets = strategy_presets_for_market(Market.CN)
        preset_ids = {preset.preset_id for preset in presets}
        self.assertIn("cn_baseline", preset_ids)
        self.assertIn("cn_momentum_core", preset_ids)
        self.assertIn("cn_low_vol_defensive", preset_ids)
        self.assertEqual(len(presets), 5)

    def test_us_strategy_catalog_weights_cover_known_factors(self) -> None:
        presets = strategy_presets_for_market(Market.US)
        preset = next(item for item in presets if item.preset_id == "us_quality_focus")
        self.assertEqual(preset.alpha_weights["profitability"], Decimal("0.32"))
        self.assertEqual(preset.alpha_weights["quality"], Decimal("0.24"))
