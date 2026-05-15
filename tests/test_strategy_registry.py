from __future__ import annotations

import tempfile
from decimal import Decimal
from unittest import TestCase

from stock_quantification.models import Market
from stock_quantification.strategy_registry import (
    StrategyRegistryStore,
    build_candidate_record_from_factor_backtest,
)
from tests.sqlite_seed_helpers import seed_strategy_registry_sqlite


class StrategyRegistryStoreTests(TestCase):
    def test_build_candidate_record_from_factor_backtest_reconstructs_executable_preset(self) -> None:
        payload = {
            "summary": {
                "artifact_type": "factor_backtest",
                "subject_id": "cn_strategy_lab:2026-01-02:2026-03-31:abcd1234",
                "subject_name": "CN 因子实验 / 20日相对强度、60日相对强度",
                "market": "CN",
                "top_n": 6,
                "selected_factor_rows": [
                    {
                        "factor_name": "rel_ret_20",
                        "effective_weight": "0.2200",
                    },
                    {
                        "factor_name": "rel_ret_60",
                        "effective_weight": "0.3300",
                    },
                ],
                "decision": "REVIEW",
                "total_return": "0.1234",
                "rolling_excess_return": "0.0567",
                "sharpe_ratio": "1.23",
            }
        }

        candidate = build_candidate_record_from_factor_backtest(
            payload,
            artifact_path="2026-03-31/cn_factor_backtest_abcd1234.json",
        )

        self.assertEqual(candidate["market"], "CN")
        self.assertEqual(candidate["preset_id"], "cn_candidate_abcd1234")
        self.assertEqual(candidate["display_name"], "CN 因子实验 / 20日相对强度、60日相对强度")
        self.assertEqual(candidate["top_n"], 6)
        self.assertEqual(candidate["policy_overrides"], {})
        self.assertEqual(candidate["alpha_weights"]["rel_ret_20"], "0.2200")
        self.assertEqual(candidate["source_artifact_path"], "2026-03-31/cn_factor_backtest_abcd1234.json")

    def test_promote_candidate_persists_and_lookup_round_trips(self) -> None:
        payload = {
            "summary": {
                "artifact_type": "factor_backtest",
                "subject_id": "us_strategy_lab:2026-01-02:2026-03-31:ffff2222",
                "subject_name": "US 因子实验 / 质量精选",
                "market": "US",
                "top_n": 5,
                "selected_factor_rows": [
                    {"factor_name": "profitability", "effective_weight": "0.3200"},
                    {"factor_name": "quality", "effective_weight": "0.2400"},
                    {"factor_name": "drawdown", "effective_weight": "-0.1800"},
                ],
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            store = StrategyRegistryStore(tmpdir)
            promoted = store.promote_factor_backtest_candidate(
                payload,
                artifact_path="2026-03-31/us_factor_backtest_ffff2222.json",
            )

            listed = store.list_market_records(Market.US)
            preset = store.lookup_strategy(Market.US, promoted["preset_id"])

            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["preset_id"], promoted["preset_id"])
            self.assertEqual(preset.preset_id, "us_candidate_ffff2222")
            self.assertEqual(preset.market, Market.US)
            self.assertEqual(preset.top_n, 5)
            self.assertEqual(preset.policy_overrides, {})
            self.assertEqual(preset.alpha_weights["profitability"], Decimal("0.3200"))

    def test_strategy_registry_reads_sqlite_records_without_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_strategy_registry_sqlite(
                tmpdir,
                {
                    "preset_id": "us_sqlite_candidate",
                    "market": "US",
                    "display_name": "US SQLite Candidate",
                    "family": "实验候选",
                    "description": "Loaded from SQLite runtime state.",
                    "top_n": 7,
                    "alpha_weights": {
                        "profitability": "0.3200",
                        "quality": "0.2100",
                    },
                    "policy_overrides": {"volatility": "-0.0800"},
                    "source_artifact_path": "2026-05-15/us_sqlite_candidate.json",
                    "source_subject_id": "sqlite:us:candidate",
                    "source_subject_name": "US SQLite Candidate",
                    "decision": "REVIEW",
                    "created_at": "2026-05-15T09:30:00",
                },
            )

            records = StrategyRegistryStore(tmpdir).list_market_records(Market.US)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["preset_id"], "us_sqlite_candidate")
            self.assertEqual(records[0]["display_name"], "US SQLite Candidate")
