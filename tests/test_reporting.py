from __future__ import annotations

from decimal import Decimal
from unittest import TestCase

from stock_quantification.reporting import (
    build_beta_extremes,
    build_candidate_buckets,
    build_markdown_report,
    build_ranked_candidates,
    build_recommended_stocks,
)


class ReportingTests(TestCase):
    def test_build_rankings_and_buckets(self) -> None:
        rankings = [
            {"instrument_id": "US.AAPL", "score": Decimal("0.8"), "sector": "Technology", "target_weight": Decimal("0.2"), "selected": True},
            {"instrument_id": "US.JNJ", "score": Decimal("0.6"), "sector": "Health Care", "target_weight": Decimal("0.1"), "selected": False},
            {"instrument_id": "US.XOM", "score": Decimal("0.4"), "sector": "Energy", "target_weight": Decimal("0.0"), "selected": False},
        ]
        beta_map = {
            "US.AAPL": {"beta": "1.30", "correlation": "0.7", "sample_size": "20"},
            "US.JNJ": {"beta": "0.75", "correlation": "0.5", "sample_size": "20"},
            "US.XOM": {"beta": "1.05", "correlation": "0.4", "sample_size": "20"},
        }
        names = {"US.AAPL": "Apple", "US.JNJ": "Johnson & Johnson", "US.XOM": "Exxon Mobil"}
        ranked = build_ranked_candidates(rankings, beta_map, instrument_names=names, limit=3)
        buckets = build_candidate_buckets(rankings, beta_map, instrument_names=names, top_n=2)
        extremes = build_beta_extremes(beta_map, instrument_names=names, limit=1)
        signals = [
            {"instrument_id": "US.AAPL", "name": "Apple", "score": "0.8", "reason": "alpha(momentum)", "beta": beta_map["US.AAPL"]},
            {"instrument_id": "US.JNJ", "name": "Johnson & Johnson", "score": "0.6", "reason": "alpha(defensive)", "beta": beta_map["US.JNJ"]},
        ]
        trade_suggestions = [
            {"instrument_id": "US.AAPL", "qty": 10},
            {"instrument_id": "US.JNJ", "qty": 5},
        ]
        execution_fills = [
            {"instrument_id": "US.AAPL", "estimated_price": "210.50"},
            {"instrument_id": "US.JNJ", "estimated_price": "155.20"},
        ]
        recommended = build_recommended_stocks(signals, ranked, trade_suggestions, execution_fills)
        markdown = build_markdown_report("US", "2026-04-02", "demo", "FULL", recommended, ranked, buckets, extremes)

        self.assertEqual(ranked[0]["instrument_id"], "US.AAPL")
        self.assertEqual(ranked[0]["name"], "Apple")
        self.assertEqual(recommended[0]["buy_price"], "210.50")
        self.assertEqual(buckets["defensive_alpha"][0]["instrument_id"], "US.JNJ")
        self.assertEqual(buckets["aggressive_alpha"][0]["instrument_id"], "US.AAPL")
        self.assertEqual(extremes["highest_beta"][0]["instrument_id"], "US.AAPL")
        self.assertIn("buy_price=210.50", markdown)
