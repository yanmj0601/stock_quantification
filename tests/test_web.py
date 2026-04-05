from __future__ import annotations

from unittest.mock import patch
from unittest import TestCase

from stock_quantification.web import DashboardApp


class WebTests(TestCase):
    def setUp(self) -> None:
        self.app = DashboardApp()

    def test_home_page_renders_dashboard(self) -> None:
        response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("双市场量化控制台", body)
        self.assertIn("最近结果", body)
        self.assertIn("主流因子组合回测", body)

    def test_chat_echo_and_path_safety(self) -> None:
        response = self.app.handle_chat({"message": ["你好，给我看今天的回测结果"]})
        self.assertEqual(response.status, 303)
        self.assertEqual(len(self.app.state.chat_messages), 2)
        self.assertIsNone(self.app._safe_artifact_path("../README.md"))

    @patch.object(DashboardApp, "_run_factor_backtest")
    def test_factor_backtest_updates_state_and_redirects(self, mock_run_factor_backtest) -> None:
        mock_run_factor_backtest.return_value = {
            "summary": {
                "market": "CN",
                "selected_factors": ["rel_ret_20", "rel_ret_60"],
                "average_return": "0.0123",
                "average_excess_return": "0.0088",
                "average_win_rate": "0.5500",
                "observations": 12,
                "best_trade_date": "2026-03-11",
            },
            "artifacts": {"json": "/tmp/cn_factor.json", "markdown": "/tmp/cn_factor.md"},
        }
        response = self.app.handle_factor_backtest(
            {
                "factor_market": ["CN"],
                "factor": ["rel_ret_20", "rel_ret_60"],
                "factor_start_date": ["2026-01-02"],
                "factor_end_date": ["2026-03-31"],
                "factor_holding_sessions": ["5"],
                "factor_detail_limit": ["8"],
                "factor_history_limit": ["60"],
                "factor_top_n": ["4"],
            }
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(self.app.state.last_factor_backtest_result["summary"]["market"], "CN")
