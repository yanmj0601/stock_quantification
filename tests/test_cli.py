from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from stock_quantification.cli import run_market
from stock_quantification.models import ExecutionMode, Market, RuntimeMode


class CliTests(TestCase):
    @patch("stock_quantification.cli._build_orchestrator", side_effect=AssertionError("orchestrator shell should not be used"), create=True)
    @patch("stock_quantification.cli.run_strategy_cycle", side_effect=RuntimeError("thin execution helper invoked"))
    @patch("stock_quantification.cli._build_context", return_value=SimpleNamespace(as_of=datetime(2026, 5, 8, 15, 0, 0)))
    @patch("stock_quantification.cli._strategy_for_market", return_value=SimpleNamespace(strategy_id="cn_index_enhancement"))
    @patch(
        "stock_quantification.cli.build_market_snapshot",
        return_value=SimpleNamespace(
            as_of=datetime(2026, 5, 8, 15, 0, 0),
            benchmark_instrument_id=None,
            research_data_bundle=SimpleNamespace(),
            data_provider=object(),
            universe_provider=object(),
            calendar_provider=object(),
        ),
    )
    def test_run_market_uses_shared_thin_execution_helper(
        self,
        _mock_snapshot,
        _mock_strategy_for_market,
        _mock_build_context,
        mock_run_strategy_cycle,
        _mock_build_orchestrator,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "thin execution helper invoked"):
            run_market(
                market=Market.CN,
                symbols=[],
                execution_mode=ExecutionMode.ADVISORY,
                runtime_mode=RuntimeMode.PAPER,
                cash=Decimal("100000"),
                detail_limit=12,
                history_limit=60,
                beta_window=20,
                top_n=5,
            )

        mock_run_strategy_cycle.assert_called_once()
