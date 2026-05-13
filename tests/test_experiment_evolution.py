from __future__ import annotations

from unittest import TestCase

from stock_quantification.experiment_evolution import (
    derive_next_factor_backtest_payload,
    describe_factor_backtest_stop_reason,
)


class ExperimentEvolutionTests(TestCase):
    def test_derive_next_payload_returns_none_when_generation_budget_is_exhausted(self) -> None:
        result = {
            "summary": {"market": "CN", "selected_factors": ["trend"], "top_n": 10},
            "attribution": {"scorecard": {"decision": "REVIEW"}},
        }
        current_payload = {
            "market": "CN",
            "selected_factors": ["trend"],
            "start_date": "2025-05-13",
            "end_date": "2026-05-13",
            "holding_sessions": 5,
            "detail_limit": 50,
            "history_limit": 200,
            "top_n": 10,
            "initial_cash": "100000",
            "factor_tilts": {"trend": "1.0"},
            "auto_iterate": True,
            "generation": 3,
            "max_generations": 3,
            "lineage_id": "lineage-1",
        }

        proposal = derive_next_factor_backtest_payload(result=result, current_payload=current_payload, current_job_id="job-3")

        self.assertIsNone(proposal)
        self.assertEqual(
            describe_factor_backtest_stop_reason(result=result, current_payload=current_payload),
            "已达到最大代次 3。",
        )

    def test_derive_next_payload_rebalances_crowded_momentum_experiment(self) -> None:
        result = {
            "summary": {
                "market": "CN",
                "selected_factors": ["rel_ret_20", "rel_ret_60", "trend", "momentum_acceleration"],
                "top_n": 10,
                "max_drawdown": "-0.1200",
                "risk_exit_count": 4,
                "trend_exit_count": 1,
                "average_excess_return": "-0.0100",
            },
            "attribution": {
                "scorecard": {"decision": "REVIEW"},
                "alpha_mix": [{"family": "momentum", "share_of_gross": "0.6800"}],
                "regime_summary": [
                    {"regime": "UP", "average_excess_period_return": "-0.0040"},
                    {"regime": "DOWN", "average_excess_period_return": "0.0020"},
                ],
            },
        }
        current_payload = {
            "market": "CN",
            "selected_factors": ["rel_ret_20", "rel_ret_60", "trend", "momentum_acceleration"],
            "start_date": "2025-05-13",
            "end_date": "2026-05-13",
            "holding_sessions": 5,
            "detail_limit": 50,
            "history_limit": 200,
            "top_n": 10,
            "initial_cash": "100000",
            "factor_tilts": {
                "rel_ret_20": "1.0",
                "rel_ret_60": "1.0",
                "trend": "1.0",
                "momentum_acceleration": "1.0",
                "drawdown": "0.6",
                "volatility_contraction": "0.3",
            },
            "auto_iterate": True,
            "generation": 1,
            "max_generations": 3,
            "lineage_id": "lineage-1",
        }

        proposal = derive_next_factor_backtest_payload(
            result=result,
            current_payload=current_payload,
            current_job_id="job-1",
            lineage_summary={"generations": [], "stagnation_count": 0},
        )

        self.assertIsNotNone(proposal)
        assert proposal is not None
        next_payload = proposal["payload"]
        self.assertEqual(next_payload["generation"], 2)
        self.assertEqual(next_payload["parent_job_id"], "job-1")
        self.assertEqual(next_payload["lineage_id"], "lineage-1")
        self.assertEqual(next_payload["mutation_template"], "breakout_rotation")
        self.assertIn("breakout_strength", next_payload["selected_factors"])
        self.assertIn("price_volume_confirmation", next_payload["selected_factors"])
        self.assertLess(float(next_payload["factor_tilts"]["rel_ret_20"]), 1.0)
        self.assertGreater(float(next_payload["factor_tilts"]["breakout_strength"]), 1.0)
        self.assertEqual(float(next_payload["factor_tilts"]["drawdown"]), 0.6)
        self.assertIn("上涨环境", proposal["mutation_reason"])

    def test_describe_stop_reason_uses_drop_decision(self) -> None:
        result = {
            "summary": {"market": "CN"},
            "attribution": {"scorecard": {"decision": "DROP"}},
        }
        current_payload = {"auto_iterate": True, "generation": 1, "max_generations": 4}

        reason = describe_factor_backtest_stop_reason(result=result, current_payload=current_payload)

        self.assertEqual(reason, "本轮结论为 DROP，停止继续派生。")

    def test_derive_next_payload_switches_template_after_stagnation(self) -> None:
        result = {
            "summary": {
                "market": "CN",
                "selected_factors": ["rel_ret_20", "rel_ret_60", "trend", "momentum_acceleration"],
                "top_n": 8,
                "max_drawdown": "-0.1100",
                "rolling_excess_return": "-0.0900",
            },
            "attribution": {
                "scorecard": {"decision": "REVIEW", "score": "2.7100"},
                "alpha_mix": [{"family": "momentum", "share_of_gross": "0.6100"}],
                "regime_summary": [
                    {"regime": "UP", "average_excess_period_return": "-0.0040"},
                ],
            },
            "rolling_backtest": {"summary": {"risk_exit_count": 18}},
        }
        current_payload = {
            "market": "CN",
            "selected_factors": ["rel_ret_20", "rel_ret_60", "trend", "momentum_acceleration"],
            "start_date": "2025-05-14",
            "end_date": "2026-05-14",
            "holding_sessions": 5,
            "detail_limit": 50,
            "history_limit": 200,
            "top_n": 8,
            "initial_cash": "100000",
            "factor_tilts": {
                "rel_ret_20": "0.8",
                "rel_ret_60": "0.8",
                "trend": "0.8",
                "momentum_acceleration": "0.8",
                "breakout_strength": "1.2",
                "price_volume_confirmation": "1.2",
                "pullback_resilience": "1.2",
            },
            "auto_iterate": True,
            "generation": 2,
            "max_generations": 4,
            "lineage_id": "lineage-2",
            "mutation_template": "breakout_rotation",
        }

        proposal = derive_next_factor_backtest_payload(
            result=result,
            current_payload=current_payload,
            current_job_id="job-2",
            lineage_summary={
                "last_mutation_template": "breakout_rotation",
                "stagnation_count": 1,
                "generations": [
                    {
                        "generation": 1,
                        "score": "2.7600",
                        "excess_return": "-0.0850",
                        "max_drawdown": "0.1050",
                        "up_excess": "-0.0030",
                    }
                ],
            },
        )

        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal["payload"]["mutation_template"], "defensive_balance")
        self.assertGreaterEqual(float(proposal["payload"]["factor_tilts"]["drawdown"]), 0.3)
        self.assertEqual(proposal["stagnation_count"], 2)
        self.assertEqual(proposal["comparison"]["is_stagnating"], True)
        self.assertIn("切换到", proposal["mutation_reason"])
