from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from stock_quantification import StrategyStateStore
from stock_quantification.artifacts import write_json_artifact
from stock_quantification.models import Market


class StrategyStateStoreTests(TestCase):
    def test_default_state_is_stable_and_market_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StrategyStateStore(tmpdir)

            state = store.load_state()
            cn_state = store.load_market_state(Market.CN)
            us_state = store.load_market_state(Market.US)

            self.assertEqual(state["markets"]["CN"], cn_state)
            self.assertEqual(state["markets"]["US"], us_state)
            self.assertEqual(cn_state, {"champion_preset_id": None, "challenger_preset_id": None, "current_execution_preset_id": None})
            self.assertEqual(us_state, {"champion_preset_id": None, "challenger_preset_id": None, "current_execution_preset_id": None})

    def test_constructor_requires_explicit_base_dir(self) -> None:
        with self.assertRaises(TypeError):
            StrategyStateStore()

    def test_set_market_state_persists_and_keeps_markets_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StrategyStateStore(tmpdir)

            store.set_market_state(
                Market.CN,
                champion_preset_id="cn_baseline",
                challenger_preset_id="cn_momentum_core",
                current_execution_preset_id="cn_quality_momentum",
            )

            cn_state = store.load_market_state(Market.CN)
            us_state = store.load_market_state(Market.US)

            self.assertEqual(
                cn_state,
                {
                    "champion_preset_id": "cn_baseline",
                    "challenger_preset_id": "cn_momentum_core",
                    "current_execution_preset_id": "cn_quality_momentum",
                },
            )
            self.assertEqual(
                us_state,
                {"champion_preset_id": None, "challenger_preset_id": None, "current_execution_preset_id": None},
            )

            self.assertTrue(Path(tmpdir, "web", "strategy_state.json").exists())

    def test_set_market_state_requires_explicit_full_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StrategyStateStore(tmpdir)

            with self.assertRaises(TypeError):
                store.set_market_state(Market.CN, champion_preset_id="cn_baseline")

    def test_set_current_execution_preset_promotes_current_preserves_other_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StrategyStateStore(tmpdir)
            store.set_market_state(
                Market.US,
                champion_preset_id="us_baseline",
                challenger_preset_id="us_quality_focus",
                current_execution_preset_id="us_quality_focus",
            )

            updated_state = store.set_current_execution_preset(Market.US, "us_momentum_plus")

            self.assertEqual(
                updated_state["markets"]["US"],
                {
                    "champion_preset_id": "us_baseline",
                    "challenger_preset_id": "us_quality_focus",
                    "current_execution_preset_id": "us_momentum_plus",
                },
            )

    def test_set_current_execution_preset_fills_missing_champion_from_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StrategyStateStore(tmpdir)

            updated_state = store.set_current_execution_preset(Market.CN, "cn_quality_momentum")

            self.assertEqual(
                updated_state["markets"]["CN"],
                {
                    "champion_preset_id": "cn_quality_momentum",
                    "challenger_preset_id": None,
                    "current_execution_preset_id": "cn_quality_momentum",
                },
            )

    def test_state_round_trips_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first_store = StrategyStateStore(tmpdir)
            first_store.set_market_state(
                Market.US,
                champion_preset_id="us_baseline",
                challenger_preset_id="us_quality_focus",
                current_execution_preset_id="us_low_vol_defensive",
            )

            second_store = StrategyStateStore(tmpdir)

            self.assertEqual(
                second_store.load_market_state(Market.US),
                {
                    "champion_preset_id": "us_baseline",
                    "challenger_preset_id": "us_quality_focus",
                    "current_execution_preset_id": "us_low_vol_defensive",
                },
            )
            self.assertEqual(
                second_store.load_market_state(Market.CN),
                {"champion_preset_id": None, "challenger_preset_id": None, "current_execution_preset_id": None},
            )

    def test_load_state_preserves_unknown_market_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_json_artifact(
                tmpdir,
                "web/strategy_state.json",
                {
                    "markets": {
                        "CN": {
                            "champion_preset_id": "cn_baseline",
                            "challenger_preset_id": None,
                            "current_execution_preset_id": "cn_quality_momentum",
                        },
                        "HK": {"champion_preset_id": "hk_core", "extra": "keep-me"},
                    }
                },
            )

            store = StrategyStateStore(tmpdir)
            state = store.load_state()

            self.assertEqual(state["markets"]["CN"]["champion_preset_id"], "cn_baseline")
            self.assertIn("HK", state["markets"])
            self.assertEqual(state["markets"]["HK"], {"champion_preset_id": "hk_core", "extra": "keep-me"})

    def test_load_state_propagates_unexpected_storage_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StrategyStateStore(tmpdir)

            with patch("stock_quantification.strategy_state.read_json_artifact", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    store.load_state()
