from __future__ import annotations

from decimal import Decimal
from unittest import TestCase

from stock_quantification.models import Market
from stock_quantification.strategy_catalog import build_strategy_from_preset, lookup_strategy_preset, strategy_presets_for_market


class StrategyCatalogTests(TestCase):
    def test_cn_strategy_catalog_contains_mainstream_long_only_presets(self) -> None:
        presets = strategy_presets_for_market(Market.CN, include_registered=False)
        preset_ids = {preset.preset_id for preset in presets}
        self.assertIn("cn_baseline", preset_ids)
        self.assertIn("cn_momentum_core", preset_ids)
        self.assertIn("cn_low_vol_defensive", preset_ids)
        self.assertEqual(len(presets), 5)

    def test_us_strategy_catalog_weights_cover_known_factors(self) -> None:
        presets = strategy_presets_for_market(Market.US, include_registered=False)
        preset = next(item for item in presets if item.preset_id == "us_quality_focus")
        self.assertEqual(preset.alpha_weights["profitability"], Decimal("0.32"))
        self.assertEqual(preset.alpha_weights["quality"], Decimal("0.24"))

    def test_lookup_strategy_preset_resolves_cn_and_us(self) -> None:
        cn_preset = lookup_strategy_preset(Market.CN, "cn_quality_momentum")
        us_preset = lookup_strategy_preset(Market.US, "us_low_vol_defensive")

        self.assertEqual(cn_preset.preset_id, "cn_quality_momentum")
        self.assertEqual(us_preset.preset_id, "us_low_vol_defensive")

    def test_build_strategy_from_preset_uses_preset_id_as_strategy_id(self) -> None:
        preset = lookup_strategy_preset(Market.US, "us_quality_focus")

        strategy = build_strategy_from_preset(preset, benchmark_instrument_id=None, benchmark_weights={})

        self.assertEqual(strategy.strategy_id, "us_quality_focus")
