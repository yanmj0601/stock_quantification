from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from stock_quantification.backtest import build_forward_return_report, serialize_backtest_report
from stock_quantification.models import AssetType, Bar, Instrument, Market


class BacktestTests(TestCase):
    @patch("stock_quantification.backtest.fetch_us_benchmark_history")
    @patch("stock_quantification.backtest.fetch_us_daily_history")
    def test_build_forward_return_report(self, mock_fetch_history, mock_fetch_benchmark) -> None:
        mock_fetch_history.side_effect = [
            (
                Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
                [
                    Bar("US.AAPL", datetime(2026, 3, 12, 16, 0, 0), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), 100, Decimal("1000")),
                    Bar("US.AAPL", datetime(2026, 3, 13, 16, 0, 0), Decimal("100"), Decimal("102"), Decimal("99"), Decimal("100"), 100, Decimal("1000")),
                    Bar("US.AAPL", datetime(2026, 3, 20, 16, 0, 0), Decimal("109"), Decimal("111"), Decimal("108"), Decimal("110"), 100, Decimal("1000")),
                ],
            ),
            (
                Instrument("US.MSFT", Market.US, "MSFT", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
                [
                    Bar("US.MSFT", datetime(2026, 3, 12, 16, 0, 0), Decimal("200"), Decimal("201"), Decimal("199"), Decimal("200"), 100, Decimal("1000")),
                    Bar("US.MSFT", datetime(2026, 3, 13, 16, 0, 0), Decimal("200"), Decimal("202"), Decimal("199"), Decimal("200"), 100, Decimal("1000")),
                    Bar("US.MSFT", datetime(2026, 3, 20, 16, 0, 0), Decimal("190"), Decimal("191"), Decimal("189"), Decimal("190"), 100, Decimal("1000")),
                ],
            ),
        ]
        mock_fetch_benchmark.return_value = (
            Instrument("US.SPY", Market.US, "SPY", AssetType.ETF, "USD", "NYSE"),
            [
                Bar("US.SPY", datetime(2026, 3, 12, 16, 0, 0), Decimal("300"), Decimal("301"), Decimal("299"), Decimal("300"), 100, Decimal("1000")),
                Bar("US.SPY", datetime(2026, 3, 13, 16, 0, 0), Decimal("300"), Decimal("302"), Decimal("299"), Decimal("300"), 100, Decimal("1000")),
                Bar("US.SPY", datetime(2026, 3, 20, 16, 0, 0), Decimal("306"), Decimal("307"), Decimal("305"), Decimal("306"), 100, Decimal("1000")),
            ],
        )

        report = build_forward_return_report(
            Market.US,
            datetime(2026, 3, 13).date(),
            recommended_stocks=[
                {"instrument_id": "US.AAPL", "name": "Apple", "sector": "Technology", "score": "1.0", "target_weight": "0.2", "qty": 10, "buy_price": "100", "reason": "alpha(momentum)"},
                {"instrument_id": "US.MSFT", "name": "Microsoft", "sector": "Technology", "score": "0.5", "target_weight": "0.1", "qty": 5, "buy_price": "200", "reason": "alpha(quality)"},
            ],
            ranked_candidates=[
                {"instrument_id": "US.AAPL", "score": "1.0"},
                {"instrument_id": "US.MSFT", "score": "0.5"},
            ],
            holding_sessions=1,
        )

        serialized = serialize_backtest_report(report)
        self.assertEqual(serialized["summary"]["selection_date"], "2026-03-13")
        self.assertEqual(serialized["summary"]["exit_date"], "2026-03-20")
        self.assertEqual(serialized["summary"]["selected_count"], 2)
        self.assertEqual(serialized["summary"]["equal_weight_return"], "0.0250")
        self.assertEqual(serialized["summary"]["benchmark_return"], "0.0200")
        self.assertEqual(serialized["rows"][0]["instrument_id"], "US.AAPL")
        self.assertEqual(serialized["rows"][0]["forward_return"], "0.1000")
