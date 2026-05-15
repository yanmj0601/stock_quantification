from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from unittest.mock import patch
from unittest import TestCase

from stock_quantification.artifacts import write_json_artifact
from stock_quantification.strategy_registry import StrategyRegistryStore
from stock_quantification import web as web_module
from stock_quantification.web import DashboardApp, DEFAULT_PROJECT_CONFIG
from tests.sqlite_seed_helpers import seed_result_index_sqlite


class WebTests(TestCase):
    def test_parse_form_body_supports_urlencoded_payloads(self) -> None:
        payload = b"market=US&view=run&subview=create"
        parsed = web_module.parse_form_body("application/x-www-form-urlencoded", payload)
        self.assertEqual(parsed["market"], ["US"])
        self.assertEqual(parsed["view"], ["run"])

    def test_parse_form_body_supports_multipart_payloads(self) -> None:
        boundary = "----CodexBoundary123"
        payload = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="market"\r\n\r\n'
            "US\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="view"\r\n\r\n'
            "run\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        parsed = web_module.parse_form_body(f"multipart/form-data; boundary={boundary}", payload)
        self.assertEqual(parsed["market"], ["US"])
        self.assertEqual(parsed["view"], ["run"])

    def setUp(self) -> None:
        self.app = DashboardApp()
        self.ops_store = Mock()
        self.ops_store.begin_job.return_value = {"accepted": True, "job": {"job_id": "job-1", "kind": "test"}}
        self.ops_store.claim_next_queued_job.return_value = None
        self.ops_store.finish_job.return_value = {}
        self.ops_store.append_event.return_value = {}
        self.ops_store.heartbeat.return_value = {}
        self.ops_store.list_events.return_value = []
        self.ops_store.list_run_history.return_value = []
        self.ops_store.load_state.return_value = {"active_job": None, "job_history": [], "audit_events": [], "heartbeats": {}}
        self.ops_store.sqlite = Mock()
        self.ops_store.sqlite.get_job.return_value = None
        self.ops_store.sqlite.get_kv.return_value = None
        self.ops_store.sqlite.delete_kv.return_value = None
        self.ops_store.sqlite.set_kv.return_value = None
        self.app._ops_store = Mock(return_value=self.ops_store)

    def test_instrument_display_label_prefers_code_and_name(self) -> None:
        self.assertEqual(
            self.app._instrument_display_label("CN.600487", "亨通光电"),
            "CN.600487 · 亨通光电",
        )
        self.assertEqual(
            self.app._instrument_display_label("US.AAPL", "US.AAPL"),
            "US.AAPL",
        )

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_renders_sidebar_navigation(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("模拟盘", body)
        self.assertIn("策略实验", body)
        self.assertIn("策略任务", body)
        self.assertIn("结果中心", body)
        self.assertNotIn("Overview / 总览", body)
        self.assertNotIn("Config / 项目配置", body)
        self.assertNotIn("Logs / 任务日志", body)
        self.assertIn("primary-nav", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_exposes_report_first_shell_hooks_on_default_paper_view(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('class="dashboard-app"', body)
        self.assertIn('<main class="app-shell app-shell--paper-first">', body)
        self.assertIn('<aside class="side-nav">', body)
        self.assertIn('<section class="page-shell">', body)
        self.assertIn('<header class="page-header">', body)
        self.assertIn("primary-nav", body)
        self.assertIn("section-tabs", body)
        self.assertIn("导航", body)
        self.assertIn("page-shell__body", body)
        self.assertNotIn('class="app-shell shell"', body)
        self.assertNotIn('class="side-nav workspace__nav"', body)
        self.assertNotIn('class="page-shell workspace__content"', body)
        self.assertNotIn('class="summary-strip panel', body)

    @patch.object(DashboardApp, "_recent_indexed_results", return_value=[
        {
            "result_id": "strategy_suite:US:2026-03-31",
            "artifact_kind": "strategy_suite",
            "market": "US",
            "summary": {"subject_name": "美股基线质量动量", "decision": "KEEP", "score": "1.2345", "return": "0.1200"},
            "artifacts": {"json": "2026-03-31/us_strategy_suite.json"},
        }
    ])
    def test_home_page_supports_results_view(self, _mock_recent_results) -> None:
        response = self.app.render_home({"view": ["results"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="champions"', body)
        self.assertIn("Champion / 冠军", body)
        self.assertIn("/?view=results&subview=champions&artifact=2026-03-31/us_strategy_suite.json", body)
        self.assertNotIn("双市场量化项目工作台", body)

    def test_home_page_supports_results_champions_subview(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-03-31",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {
                                "subject_id": "us_baseline",
                                "subject_name": "美股冠军策略",
                                "decision": "KEEP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-03-31/us_baseline.json"},
                        },
                        {
                            "result_id": "strategy_suite:US:2026-04-01",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-01",
                            "summary": {
                                "subject_id": "us_quality_focus",
                                "subject_name": "美股挑战者策略",
                                "decision": "REVIEW",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-01/us_quality_focus.json"},
                        },
                        {
                            "result_id": "strategy_suite:US:2026-04-02",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-02",
                            "summary": {
                                "subject_id": "us_dropout",
                                "subject_name": "美股淘汰策略",
                                "decision": "DROP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-02/us_dropout.json"},
                        },
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "web/strategy_state.json",
                {
                    "markets": {
                        "US": {
                            "champion_preset_id": "us_baseline",
                            "challenger_preset_id": "us_quality_focus",
                            "current_execution_preset_id": "us_quality_focus",
                        }
                    }
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["results"], "subview": ["champions"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="champions"', body)
        self.assertIn("Champion / 冠军", body)
        self.assertIn("美股冠军策略", body)
        self.assertNotIn("美股挑战者策略", body)
        self.assertNotIn("美股淘汰策略", body)

    def test_home_page_supports_results_challengers_subview(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-03-31",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {
                                "subject_id": "us_baseline",
                                "subject_name": "美股冠军策略",
                                "decision": "KEEP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-03-31/us_baseline.json"},
                        },
                        {
                            "result_id": "strategy_suite:US:2026-04-01",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-01",
                            "summary": {
                                "subject_id": "us_quality_focus",
                                "subject_name": "美股挑战者策略",
                                "decision": "REVIEW",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-01/us_quality_focus.json"},
                        },
                        {
                            "result_id": "strategy_suite:US:2026-04-02",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-02",
                            "summary": {
                                "subject_id": "us_dropout",
                                "subject_name": "美股淘汰策略",
                                "decision": "DROP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-02/us_dropout.json"},
                        },
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "web/strategy_state.json",
                {
                    "markets": {
                        "US": {
                            "champion_preset_id": "us_baseline",
                            "challenger_preset_id": "us_quality_focus",
                            "current_execution_preset_id": "us_baseline",
                        }
                    }
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["results"], "subview": ["challengers"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="challengers"', body)
        self.assertIn("Challenger / 挑战者", body)
        self.assertIn("美股挑战者策略", body)
        self.assertNotIn("美股冠军策略", body)
        self.assertNotIn("美股淘汰策略", body)

    def test_home_page_supports_results_drops_subview(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-03-31",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {
                                "subject_id": "us_baseline",
                                "subject_name": "美股冠军策略",
                                "decision": "KEEP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-03-31/us_baseline.json"},
                        },
                        {
                            "result_id": "strategy_suite:US:2026-04-01",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-01",
                            "summary": {
                                "subject_id": "us_quality_focus",
                                "subject_name": "美股挑战者策略",
                                "decision": "REVIEW",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-01/us_quality_focus.json"},
                        },
                        {
                            "result_id": "strategy_suite:US:2026-04-02",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-02",
                            "summary": {
                                "subject_id": "us_dropout",
                                "subject_name": "美股淘汰策略",
                                "decision": "DROP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-02/us_dropout.json"},
                        },
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["results"], "subview": ["drops"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="drops"', body)
        self.assertIn("Drop / 淘汰", body)
        self.assertIn("美股淘汰策略", body)
        self.assertNotIn("美股冠军策略", body)
        self.assertNotIn("美股挑战者策略", body)

    def test_home_page_supports_results_archive_subview(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-03-31",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {
                                "subject_id": "us_baseline",
                                "subject_name": "美股冠军策略",
                                "decision": "KEEP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-03-31/us_baseline.json"},
                        },
                        {
                            "result_id": "strategy_suite:US:2026-04-01",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-01",
                            "summary": {
                                "subject_id": "us_quality_focus",
                                "subject_name": "美股挑战者策略",
                                "decision": "REVIEW",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-01/us_quality_focus.json"},
                        },
                        {
                            "result_id": "strategy_suite:US:2026-04-02",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-02",
                            "summary": {
                                "subject_id": "us_dropout",
                                "subject_name": "美股淘汰策略",
                                "decision": "DROP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-02/us_dropout.json"},
                        },
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["results"], "subview": ["archive"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="archive"', body)
        self.assertIn("Archive / 归档", body)
        self.assertIn("美股冠军策略", body)
        self.assertIn("美股挑战者策略", body)
        self.assertIn("美股淘汰策略", body)
        self.assertNotIn("Research Results / 研究结果中心", body)
        self.assertNotIn("Runtime Results / 运行结果", body)

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_supports_paper_view(self, mock_ledger_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 0,
            "trade_count": 0,
            "filtered_trade_count": 0,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [{"instrument_id": "US.AAPL", "qty": "10", "avg_cost": "180"}],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [
                {
                    "instrument_id": "US.AAPL",
                    "name": "Apple Inc.",
                    "sector": "Tech",
                    "qty": "10",
                    "avg_cost": "180",
                    "current_price": "200",
                    "market_value": "2000",
                    "weight_pct": "20",
                    "unrealized_pnl": "200",
                }
            ],
            "filtered_trades": [
                {
                    "instrument_id": "US.AAPL",
                    "name": "Apple Inc.",
                    "estimated_price": "200",
                    "cash_delta": "-2000",
                }
            ],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        response = self.app.render_home({"view": ["paper"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertNotIn("<p class=\"eyebrow\">Project Overview</p>", body)
        self.assertNotIn("<h2>项目总览</h2>", body)
        self.assertIn("Current Strategy / 当前策略", body)
        self.assertIn("Execution Timeline / 执行时间线", body)
        self.assertIn("Account Conclusion / 账户结论", body)
        self.assertIn("Account Snapshot / 账户摘要", body)
        self.assertIn("Account Workspace / 账户工作区", body)
        self.assertIn('<select name="paper_account_id">', body)
        self.assertNotIn("Risk Alerts / 风险告警", body)
        self.assertNotIn("Current Positions / 当前持仓盈亏", body)
        self.assertNotIn("Recent Trades / 最近成交", body)

    @patch("stock_quantification.web.StrategyStateStore")
    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_paper_view_uses_main_holdings_and_trades_tabs(self, mock_ledger_cls, mock_strategy_state_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 0,
            "trade_count": 0,
            "filtered_trade_count": 0,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [{"instrument_id": "US.AAPL", "qty": "10", "avg_cost": "180"}],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [
                {
                    "instrument_id": "US.AAPL",
                    "name": "Apple Inc.",
                    "sector": "Tech",
                    "qty": "10",
                    "avg_cost": "180",
                    "current_price": "200",
                    "market_value": "2000",
                    "weight_pct": "20",
                    "unrealized_pnl": "200",
                }
            ],
            "filtered_trades": [
                {
                    "instrument_id": "US.AAPL",
                    "name": "Apple Inc.",
                    "estimated_price": "200",
                    "cash_delta": "-2000",
                }
            ],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        mock_strategy_state = mock_strategy_state_cls.return_value
        mock_strategy_state.load_market_state.return_value = {
            "champion_preset_id": "us_baseline",
            "challenger_preset_id": "us_quality_focus",
            "current_execution_preset_id": "us_quality_focus",
        }

        response = self.app.render_home({"view": ["paper"], "subview": ["main"]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Main / 主页面", body)
        self.assertIn('data-subview="main"', body)
        self.assertIn("Holdings / 持仓", body)
        self.assertIn("Trades / 交易", body)
        self.assertNotIn("Holdings Detail / 持仓详情", body)
        self.assertNotIn("Recent Trades / 最近成交", body)
        self.assertIn("Current Strategy / 当前策略", body)
        self.assertIn("美股质量精选", body)
        self.assertIn('form method="post" action="/strategy-state/current"', body)
        self.assertIn('>设为当前执行策略<', body)
        self.assertNotIn('aria-disabled="true"', body)

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_paper_view_keeps_account_context_sections(self, mock_ledger_cls) -> None:
        ledger = mock_ledger_cls.return_value
        overview = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 2,
            "trade_count": 5,
            "filtered_trade_count": 3,
            "latest_nav": "105000",
            "cumulative_return": "0.05",
            "positions": [],
            "nav_history": [
                {"trade_date": "2026-04-17", "nav": "101000"},
                {"trade_date": "2026-04-18", "nav": "105000"},
            ],
            "recent_trades": [{"trade_date": "2026-04-18", "side": "BUY", "instrument_id": "US.AAPL", "filled_qty": "10", "realized_price": "180", "cash_delta": "-1800"}],
            "today_summary": {"trade_date": "2026-04-18", "buy_count": "1", "sell_count": "0", "gross_buy_notional": "1800", "gross_sell_notional": "0", "net_cash_flow": "-1800"},
            "sector_exposure_rows": [{"sector": "Tech", "weight_pct": "50", "market_value": "50000"}],
            "risk_alerts": [{"level": "warn", "title": "集中度", "detail": "单一行业占比偏高"}],
            "position_rows": [{"instrument_id": "US.AAPL", "qty": "10", "current_price": "180", "unrealized_pnl": "100", "pnl_pct": "5"}],
            "filter_start_date": "2026-04-01",
            "filter_end_date": "2026-04-30",
        }
        ledger.latest_account_overview.return_value = overview
        ledger.account_overview.return_value = overview
        ledger.list_accounts.return_value = ["web-paper-us", "web-paper-cn"]

        response = self.app.render_home({"view": ["paper"], "paper_account_id": ["web-paper-us"]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Latest NAV / 最新净值", body)
        self.assertIn("Cumulative Return / 累计收益", body)
        self.assertIn("Estimated NAV / 估算净值", body)
        self.assertIn("Current Strategy / 当前策略", body)
        self.assertIn("Execution Timeline / 执行时间线", body)
        self.assertNotIn("Holdings Detail / 持仓详情", body)
        self.assertNotIn("Sector Exposure / 行业暴露", body)
        self.assertNotIn("Recent Trades / 最近成交", body)
        self.assertIn("Reset Account / 重置当前账户", body)
        self.assertIn('name="subview" value="main"', body)
        self.assertIn('name="paper_account_id" value="web-paper-us"', body)
        self.assertIn('name="paper_start_date" value="2026-04-01"', body)
        self.assertIn('name="paper_end_date" value="2026-04-30"', body)
        self.assertIn("Account Workspace / 账户工作区", body)
        self.assertIn('<select name="paper_account_id">', body)
        self.assertIn("web-paper-cn", body)
        self.assertIn("美股模拟盘", body)

    @patch("stock_quantification.web.StrategyStateStore")
    def test_handle_strategy_state_current_updates_state_and_redirects_to_paper_context(self, mock_strategy_state_cls) -> None:
        strategy_state = mock_strategy_state_cls.return_value
        strategy_state.load_market_state.return_value = {
            "champion_preset_id": "us_baseline",
            "challenger_preset_id": "us_quality_focus",
            "current_execution_preset_id": "us_quality_focus",
        }
        response = self.app.handle_strategy_state_current(
            {
                "view": ["paper"],
                "market": ["US"],
                "preset_id": ["us_momentum_core"],
                "paper_account_id": ["web-paper-us"],
                "paper_start_date": ["2026-04-01"],
                "paper_end_date": ["2026-04-30"],
                "subview": ["main"],
            }
        )

        self.assertEqual(response.status, 303)
        self.assertEqual(
            response.headers["Location"],
            "/?view=paper&paper_account_id=web-paper-us&paper_start_date=2026-04-01&paper_end_date=2026-04-30&subview=main",
        )
        strategy_state.set_current_execution_preset.assert_called_once_with("US", "us_momentum_core")
        self.assertIn("已设为当前执行策略", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "paper")

    @patch("stock_quantification.web.StrategyStateStore")
    def test_handle_strategy_state_current_redirects_with_flash_when_persistence_fails(self, mock_strategy_state_cls) -> None:
        strategy_state = mock_strategy_state_cls.return_value
        strategy_state.set_current_execution_preset.side_effect = OSError("disk full")

        response = self.app.handle_strategy_state_current(
            {
                "view": ["paper"],
                "market": ["US"],
                "preset_id": ["us_momentum_core"],
                "paper_account_id": ["web-paper-us"],
                "paper_start_date": ["2026-04-01"],
                "paper_end_date": ["2026-04-30"],
                "subview": ["main"],
            }
        )

        self.assertEqual(response.status, 303)
        self.assertEqual(
            response.headers["Location"],
            "/?view=paper&paper_account_id=web-paper-us&paper_start_date=2026-04-01&paper_end_date=2026-04-30&subview=main",
        )
        self.assertIn("设为当前执行策略失败", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "paper")

    def test_handle_strategy_candidate_promote_registers_candidate_and_updates_challenger(self) -> None:
        payload = {
            "summary": {
                "artifact_type": "factor_backtest",
                "subject_id": "cn_strategy_lab:2026-01-02:2026-03-31:abcd1234",
                "subject_name": "CN 因子实验 / 20日相对强度、60日相对强度",
                "market": "CN",
                "top_n": 6,
                "turnover_cap": "0.1800",
                "rebalance_buffer": "0.0500",
                "selected_factor_rows": [
                    {"factor_name": "rel_ret_20", "effective_weight": "0.2200"},
                    {"factor_name": "rel_ret_60", "effective_weight": "0.3300"},
                ],
                "decision": "REVIEW",
                "total_return": "0.1234",
                "rolling_excess_return": "0.0567",
                "sharpe_ratio": "1.23",
            }
        }
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(artifact_root, "2026-03-31/cn_factor_backtest_abcd1234.json", payload)
            write_json_artifact(
                artifact_root,
                "web/strategy_state.json",
                {
                    "markets": {
                        "CN": {
                            "champion_preset_id": "cn_baseline",
                            "challenger_preset_id": None,
                            "current_execution_preset_id": "cn_baseline",
                        }
                    }
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.handle_strategy_candidate_promote(
                    {
                        "view": ["optimize"],
                        "subview": ["detail"],
                        "artifact": ["2026-03-31/cn_factor_backtest_abcd1234.json"],
                    }
                )
                registry = StrategyRegistryStore(artifact_root)
                promoted = registry.lookup_strategy("CN", "cn_candidate_abcd1234")
                strategy_state = self.app._strategy_state_store().load_market_state("CN")
                result_index = web_module.read_json_artifact(artifact_root, "web/result_index.json")

        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=optimize&subview=detail&artifact=2026-03-31/cn_factor_backtest_abcd1234.json")
        self.assertEqual(promoted.preset_id, "cn_candidate_abcd1234")
        self.assertEqual(strategy_state["challenger_preset_id"], "cn_candidate_abcd1234")
        self.assertEqual(result_index["records"][0]["artifact_kind"], "candidate_strategy")
        self.assertEqual(result_index["records"][0]["summary"]["subject_id"], "cn_candidate_abcd1234")

    @patch("stock_quantification.web.StrategyStateStore")
    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_paper_view_falls_back_to_champion_when_current_execution_missing(self, mock_ledger_cls, mock_strategy_state_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 0,
            "trade_count": 0,
            "filtered_trade_count": 0,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        mock_strategy_state_cls.return_value.load_market_state.return_value = {
            "champion_preset_id": "us_baseline",
            "challenger_preset_id": "us_quality_focus",
            "current_execution_preset_id": None,
        }

        response = self.app.render_home({"view": ["paper"], "subview": ["main"]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Current Strategy / 当前策略", body)
        self.assertIn("Current Execution / 当前执行策略", body)
        self.assertIn("美股基线质量动量", body)
        self.assertNotIn('<span>Current Execution / 当前执行策略</span>\n          <strong>N/A</strong>', body)

    @patch("stock_quantification.web.StrategyStateStore")
    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_paper_view_uses_latest_paper_run_strategy_when_state_is_empty(self, mock_ledger_cls, mock_strategy_state_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 2,
            "trade_count": 5,
            "filtered_trade_count": 5,
            "latest_nav": "103000",
            "cumulative_return": "0.0300",
            "positions": [],
            "nav_history": [],
            "recent_trades": [{"strategy_id": "us_baseline"}],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        mock_strategy_state_cls.return_value.load_market_state.return_value = {
            "champion_preset_id": None,
            "challenger_preset_id": None,
            "current_execution_preset_id": None,
        }
        self.app._latest_paper_run_result = Mock(return_value={"paper_run_summary": {"strategy_id": "us_baseline", "account_id": "web-paper-us", "market": "US"}})

        response = self.app.render_home({"view": ["paper"], "subview": ["main"]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Current Execution / 当前执行策略", body)
        self.assertIn("美股基线质量动量", body)
        self.assertNotIn('<span>Current Execution / 当前执行策略</span>\n          <strong>N/A</strong>', body)

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_paper_view_renders_real_account_conclusion_instead_of_only_note(self, mock_ledger_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 2,
            "trade_count": 5,
            "filtered_trade_count": 5,
            "latest_nav": "105000",
            "cumulative_return": "0.0500",
            "positions": [],
            "nav_history": [],
            "recent_trades": [{"strategy_id": "us_baseline"}],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        self.app._latest_paper_run_result = Mock(return_value={"review": {"verdict": "PASS"}, "paper_run_summary": {"strategy_id": "us_baseline"}})

        response = self.app.render_home({"view": ["paper"], "subview": ["main"]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Account Conclusion / 账户结论", body)
        self.assertIn("账户增值中", body)
        self.assertIn("Conclusion Basis / 结论依据", body)
        self.assertIn("账户净值与持仓状态", body)

    @patch("stock_quantification.web.StrategyStateStore")
    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_paper_holdings_view_keeps_holdings_tables_only(self, mock_ledger_cls, mock_strategy_state_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 1,
            "trade_count": 2,
            "filtered_trade_count": 1,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [{"instrument_id": "US.AAPL", "qty": "10", "avg_cost": "180"}],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [
                {
                    "instrument_id": "US.AAPL",
                    "name": "Apple Inc.",
                    "sector": "Tech",
                    "qty": "10",
                    "avg_cost": "180",
                    "current_price": "200",
                    "market_value": "2000",
                    "weight_pct": "20",
                    "unrealized_pnl": "200",
                }
            ],
            "filtered_trades": [
                {
                    "instrument_id": "US.AAPL",
                    "name": "Apple Inc.",
                    "estimated_price": "200",
                    "cash_delta": "-2000",
                }
            ],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        mock_strategy_state_cls.return_value.load_market_state.return_value = {
            "champion_preset_id": "us_baseline",
            "challenger_preset_id": "us_quality_focus",
            "current_execution_preset_id": "us_quality_focus",
        }
        with patch.object(self.app, "_enrich_local_paper_overview", side_effect=lambda payload: payload):
            response = self.app.render_home({"view": ["paper"], "subview": ["holdings"]})
            body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="holdings"', body)
        self.assertIn("Holdings Detail / 持仓详情", body)
        self.assertIn("Sector Exposure / 行业暴露", body)
        self.assertIn("US.AAPL · Apple Inc.", body)
        self.assertNotIn("Account Conclusion / 账户结论", body)
        self.assertNotIn("Recent Trades / 最近成交", body)

    @patch("stock_quantification.web.StrategyStateStore")
    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_paper_trades_view_keeps_trade_history_only(self, mock_ledger_cls, mock_strategy_state_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 1,
            "trade_count": 2,
            "filtered_trade_count": 1,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [],
            "nav_history": [],
            "recent_trades": [
                {
                    "trade_date": "2026-04-18",
                    "side": "BUY",
                    "instrument_id": "US.AAPL",
                    "name": "Apple Inc.",
                    "filled_qty": "10",
                    "realized_price": "180",
                    "cash_delta": "-1800",
                }
            ],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        mock_strategy_state_cls.return_value.load_market_state.return_value = {
            "champion_preset_id": "us_baseline",
            "challenger_preset_id": "us_quality_focus",
            "current_execution_preset_id": "us_quality_focus",
        }

        response = self.app.render_home({"view": ["paper"], "subview": ["trades"]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="trades"', body)
        self.assertIn("Recent Trades / 最近成交", body)
        self.assertIn("US.AAPL · Apple Inc.", body)
        self.assertNotIn("Holdings Detail / 持仓详情", body)
        self.assertNotIn("Sector Exposure / 行业暴露", body)
        self.assertNotIn("Account Conclusion / 账户结论", body)

    def test_home_page_falls_back_to_paper_for_invalid_view(self) -> None:
        response = self.app.render_home({"view": ["not-a-real-view"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertIn('data-primary-view="paper"', body)
        self.assertIn("primary-nav__link--active", body)
        self.assertIn("section-tabs", body)
        self.assertNotIn("Morning Brief / 今日总览", body)

    # Legacy query aliases are kept only as compatibility shims for older URLs.
    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_legacy_overview_alias_falls_back_to_paper(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({"view": ["overview"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertIn('data-primary-view="paper"', body)
        self.assertNotIn("Morning Brief / 今日总览", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_legacy_workbench_alias_falls_back_to_paper(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({"view": ["workbench"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertIn('data-primary-view="paper"', body)
        self.assertIn("section-tabs", body)
        self.assertNotIn("Morning Brief / 今日总览", body)

    @patch("stock_quantification.web.StrategyStateStore")
    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_run_create_view_defaults_strategy_selectors_from_state(self, mock_ledger_cls, mock_strategy_state_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 0,
            "trade_count": 0,
            "filtered_trade_count": 0,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        mock_strategy_state = mock_strategy_state_cls.return_value
        mock_strategy_state.load_market_state.side_effect = lambda market: {
            "CN": {
                "champion_preset_id": "cn_baseline",
                "challenger_preset_id": "cn_quality_momentum",
                "current_execution_preset_id": "cn_quality_momentum",
            },
            "US": {
                "champion_preset_id": "us_baseline",
                "challenger_preset_id": "us_quality_focus",
                "current_execution_preset_id": "us_quality_focus",
            },
        }[market.value]

        response = self.app.render_home({"view": ["run"], "subview": ["create"]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Strategy Tasks / 策略任务", body)
        self.assertIn('value="cn_quality_momentum" selected', body)
        self.assertIn('value="us_quality_focus" selected', body)
        self.assertNotIn('id="run-create-progress"', body)
        self.assertIn('data-async-submit-feedback', body)
        self.assertIn('data-submit-label="提交策略任务"', body)
        self.assertIn('data-pending-label="策略任务提交中..."', body)
        self.assertIn("response.url === window.location.href", body)
        self.assertIn("现在提交的新任务会进入队列", body)
        self.assertIn('type="number" min="1" step="1" name="cash"', body)
        self.assertIn('type="date" name="as_of_date"', body)
        self.assertIn('<select id="run-broker-account-id" name="broker_account_id"', body)
        self.assertIn('data-market="US"', body)
        self.assertIn('data-market="CN"', body)
        self.assertNotIn("Current Defaults / 当前默认配置", body)
        self.assertNotIn("Recent Execution / 最近执行反馈", body)
        self.assertNotIn("workbench-grid", body)

    @patch("stock_quantification.web.StrategyStateStore")
    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_run_create_view_falls_back_to_market_default_preset(self, mock_ledger_cls, mock_strategy_state_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 0,
            "trade_count": 0,
            "filtered_trade_count": 0,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        mock_strategy_state = mock_strategy_state_cls.return_value
        mock_strategy_state.load_market_state.side_effect = lambda market: {
            "CN": {
                "champion_preset_id": "cn_baseline",
                "challenger_preset_id": "cn_quality_momentum",
                "current_execution_preset_id": None,
            },
            "US": {
                "champion_preset_id": "us_baseline",
                "challenger_preset_id": "us_quality_focus",
                "current_execution_preset_id": None,
            },
        }[market.value]

        response = self.app.render_home({"view": ["run"], "subview": ["create"]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn('value="cn_baseline" selected', body)
        self.assertIn('value="us_baseline" selected', body)

    def test_home_page_run_create_view_lists_promoted_candidates_as_executable_strategies(self) -> None:
        payload = {
            "summary": {
                "artifact_type": "factor_backtest",
                "subject_id": "us_strategy_lab:2026-01-02:2026-03-31:ffff2222",
                "subject_name": "US 因子实验 / 质量精选",
                "market": "US",
                "top_n": 5,
                "turnover_cap": "0.1000",
                "rebalance_buffer": "0.0800",
                "selected_factor_rows": [
                    {"factor_name": "profitability", "effective_weight": "0.3200"},
                    {"factor_name": "quality", "effective_weight": "0.2400"},
                ],
            }
        }
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            registry = StrategyRegistryStore(artifact_root)
            registry.promote_factor_backtest_candidate(payload, artifact_path="2026-03-31/us_factor_backtest_ffff2222.json")
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["run"], "subview": ["create"]})

        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("us_candidate_ffff2222", body)
        self.assertIn("实验候选", body)

    def test_home_page_run_create_view_renders_run_scoped_flash(self) -> None:
        self.app.state.push_flash("运行页消息", audience="run")
        response = self.app.render_home({"view": ["run"], "subview": ["create"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("运行页消息", body)
        self.assertNotIn('id="run-create-progress"', body)

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_run_history_view_lists_runs_most_recent_first(self, mock_ledger_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 0,
            "trade_count": 0,
            "filtered_trade_count": 0,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        self.app.state.last_run_results = [
            {
                "market": "US",
                "trade_date": "2026-04-18",
                "strategy_id": "us_baseline",
                "signals": [{"instrument_id": "US.AAPL", "score": "0.8", "reason": "older"}],
                "trade_suggestions": [{"instrument_id": "US.AAPL", "side": "BUY", "qty": 10, "rationale": "older"}],
                "review": {"verdict": "PASS", "comments": ["older"]},
                "paper_account": {"account_id": "web-paper-us", "latest_nav": "100000", "cash": "90000", "buying_power": "80000", "position_count": 1, "trade_count": 1},
                "paper_run_summary": {"account_id": "web-paper-us", "strategy_id": "us_baseline", "trade_count": 1, "position_count": 1, "cash": "90000", "buying_power": "80000"},
            },
            {
                "market": "US",
                "trade_date": "2026-04-19",
                "strategy_id": "us_quality_focus",
                "signals": [{"instrument_id": "US.MSFT", "score": "0.9", "reason": "newer"}],
                "trade_suggestions": [{"instrument_id": "US.MSFT", "side": "BUY", "qty": 5, "rationale": "newer"}],
                "review": {"verdict": "REVIEW", "comments": ["newer"]},
                "paper_account": {"account_id": "web-paper-us", "latest_nav": "101000", "cash": "91000", "buying_power": "81000", "position_count": 2, "trade_count": 2},
                "paper_run_summary": {"account_id": "web-paper-us", "strategy_id": "us_quality_focus", "trade_count": 2, "position_count": 2, "cash": "91000", "buying_power": "81000"},
            },
        ]

        response = self.app.render_home({"view": ["run"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        latest_run_ref = self.app._run_result_ref(self.app.state.last_run_results[-1])
        older_run_ref = self.app._run_result_ref(self.app.state.last_run_results[0])

        self.assertEqual(response.status, 200)
        self.assertIn("Run History / 运行历史", body)
        self.assertIn("timeline-stack", body)
        self.assertNotIn("card-grid", body)
        self.assertLess(body.index(f"run_ref={web_module.quote(latest_run_ref)}"), body.index(f"run_ref={web_module.quote(older_run_ref)}"))
        self.assertIn(f"run_ref={web_module.quote(latest_run_ref)}", body)
        self.assertIn("view=run&amp;subview=detail", body)
        self.assertNotIn('data-subview="detail"', body)

    def test_home_page_run_history_view_reads_persisted_history(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/run_history.json",
                {
                    "records": [
                        {
                            "market": "US",
                            "trade_date": "2026-04-19",
                            "strategy_id": "us_quality_focus",
                            "signals": [{"instrument_id": "US.MSFT", "score": "0.9", "reason": "persisted"}],
                            "trade_suggestions": [{"instrument_id": "US.MSFT", "side": "BUY", "qty": 5, "rationale": "persisted"}],
                            "review": {"verdict": "PASS", "comments": ["persisted"]},
                            "paper_account": {"account_id": "web-paper-us", "latest_nav": "101000", "cash": "95000", "buying_power": "94000", "position_count": 1, "trade_count": 1},
                            "paper_run_summary": {"account_id": "web-paper-us", "strategy_id": "us_quality_focus", "trade_count": 1, "position_count": 1, "cash": "95000", "buying_power": "94000"},
                            "run_instance_id": "persisted-run-1",
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    response = self.app.render_home({"view": ["run"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("us_quality_focus", body)
        self.assertIn("timeline-stack", body)
        self.assertIn("view=run&amp;subview=detail", body)

    def test_home_page_run_history_shows_recent_success_event_above_older_blocked_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                ops_store = web_module.ProjectOpsStore(artifact_root)
                with patch("stock_quantification.sqlite_state._utc_now", side_effect=["2026-05-05T09:00:00", "2026-05-05T09:05:00", "2026-05-05T09:05:01"]):
                    ops_store.append_event(
                        category="runtime",
                        action="strategy_run",
                        status="BLOCKED",
                        detail="策略运行被运行守护拦截",
                        metadata={"active_job": "factor_backtest"},
                    )
                    ops_store.append_event(
                        category="runtime",
                        action="strategy_run",
                        status="SUCCESS",
                        detail="运行 1 个市场，execution=ADVISORY，runtime=PAPER",
                        metadata={"account_id": "web-paper-us", "markets": "US"},
                    )
                    ops_store.append_run_history(
                        [
                            {
                                "market": "US",
                                "trade_date": "2026-04-19",
                                "strategy_id": "us_quality_focus",
                                "review": {"verdict": "PASS", "comments": ["persisted"]},
                                "paper_trade_records": [],
                                "run_instance_id": "recent-run-1",
                            }
                        ]
                    )
                with patch.object(self.app, "_ops_store", return_value=ops_store):
                    response = self.app.render_home({"view": ["run"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("us_quality_focus", body)
        self.assertIn("SUCCESS", body)
        self.assertIn("BLOCKED", body)
        self.assertLess(body.find("SUCCESS"), body.find("BLOCKED"))

    def test_home_page_run_history_prioritizes_run_results_above_runtime_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                ops_store = web_module.ProjectOpsStore(artifact_root)
                with patch("stock_quantification.sqlite_state._utc_now", side_effect=["2026-05-05T10:00:00", "2026-05-05T10:00:01"]):
                    ops_store.append_event(
                        category="runtime",
                        action="strategy_run",
                        status="SUCCESS",
                        detail="运行 1 个市场，execution=ADVISORY，runtime=PAPER",
                        metadata={"account_id": "web-paper-us", "markets": "US"},
                    )
                    ops_store.append_run_history(
                        [
                            {
                                "market": "US",
                                "trade_date": "2026-05-04",
                                "strategy_id": "us_quality_focus",
                                "review": {"verdict": "PASS", "comments": ["persisted"]},
                                "paper_trade_records": [],
                                "run_instance_id": "persisted-run-2",
                            }
                        ]
                    )
                with patch.object(self.app, "_ops_store", return_value=ops_store):
                    response = self.app.render_home({"view": ["run"], "subview": ["history"]})

        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("SUCCESS", body)
        self.assertIn("us_quality_focus", body)
        self.assertLess(body.find("us_quality_focus"), body.find("SUCCESS"))

    def test_home_page_run_history_surfaces_matching_run_detail_above_success_event(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                ops_store = web_module.ProjectOpsStore(artifact_root)
                run_result = {
                    "market": "US",
                    "trade_date": "2026-05-05",
                    "strategy_id": "us_quality_focus",
                    "review": {"verdict": "PASS", "comments": ["persisted"]},
                    "paper_trade_records": [],
                    "paper_run_summary": {
                        "account_id": "web-paper-us",
                        "strategy_id": "us_quality_focus",
                        "as_of": "2026-05-05T08:23:25",
                        "trade_count": 0,
                        "position_count": 0,
                    },
                    "run_instance_id": "recent-run-1",
                }
                with patch("stock_quantification.sqlite_state._utc_now", return_value="2026-05-05T08:23:25"):
                    ops_store.append_event(
                        category="runtime",
                        action="strategy_run",
                        status="SUCCESS",
                        detail="运行 1 个市场，execution=ADVISORY，runtime=PAPER",
                        metadata={"account_id": "web-paper-us", "markets": "US"},
                    )
                    ops_store.append_run_history([run_result])
                with patch.object(self.app, "_ops_store", return_value=ops_store):
                    response = self.app.render_home({"view": ["run"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        expected_run_ref = web_module.quote(self.app._run_result_ref(run_result))
        self.assertEqual(response.status, 200)
        self.assertIn("Run 1", body)
        self.assertIn(f"run_ref={expected_run_ref}", body)
        self.assertIn("Open Detail / 打开详情", body)
        self.assertLess(body.find("Run 1"), body.find("Run Event 2"))

    def test_home_page_run_history_view_shows_blocked_runtime_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/task_logs.json",
                {
                    "entries": [
                        {
                            "created_at": "2026-05-02T23:28:19",
                            "category": "runtime",
                            "action": "strategy_run",
                            "status": "BLOCKED",
                            "detail": "策略运行被运行守护拦截",
                            "metadata": {"markets": "CN,US"},
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    response = self.app.render_home({"view": ["run"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("BLOCKED", body)
        self.assertIn("策略运行被运行守护拦截", body)
        self.assertIn("timeline-stack", body)
        self.assertNotIn('data-subview="detail"', body)

    def test_home_page_run_history_view_keeps_duplicate_blocked_runtime_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/task_logs.json",
                {
                    "entries": [
                        {
                            "created_at": "2026-05-05T08:38:21",
                            "category": "runtime",
                            "action": "strategy_run",
                            "status": "STARTED",
                            "detail": "已提交 2 个市场的策略运行任务",
                            "metadata": {"markets": "CN,US"},
                        },
                        {
                            "created_at": "2026-05-05T08:38:25",
                            "category": "runtime",
                            "action": "strategy_run",
                            "status": "BLOCKED",
                            "detail": "策略运行被运行守护拦截",
                            "metadata": {"markets": "CN,US"},
                        },
                        {
                            "created_at": "2026-05-05T08:38:34",
                            "category": "runtime",
                            "action": "strategy_run",
                            "status": "BLOCKED",
                            "detail": "策略运行被运行守护拦截",
                            "metadata": {"markets": "CN,US"},
                        },
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    response = self.app.render_home({"view": ["run"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertEqual(body.count("策略运行被运行守护拦截"), 2)

    def test_home_page_run_history_view_shows_recent_queued_jobs(self) -> None:
        self.ops_store.load_state.return_value = {
            "active_job": None,
            "queued_jobs": [
                {
                    "job_id": "queue-1",
                    "kind": "strategy_run",
                    "status": "QUEUED",
                    "stage": "QUEUED",
                    "detail": "Task accepted and waiting in queue.",
                    "metadata": {"markets": ["US"]},
                    "created_at": "2026-05-05T10:00:00",
                }
            ],
            "job_history": [],
            "audit_events": [],
            "heartbeats": {},
        }
        response = self.app.render_home({"view": ["run"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("QUEUED", body)
        self.assertIn("Task accepted and waiting in queue.", body)
        self.assertIn("US", body)

    def test_run_form_renders_write_to_paper_impact_hint(self) -> None:
        response = self.app.render_home({"view": ["run"], "subview": ["create"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('id="run-impact-hint"', body)
        self.assertIn("本次仅生成策略结果，不会写入模拟盘。", body)
        self.assertIn('id="run-route-orders"', body)

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_run_detail_view_renders_selected_run(self, mock_ledger_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 0,
            "trade_count": 0,
            "filtered_trade_count": 0,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        self.app.state.last_run_results = [
            {
                "market": "US",
                "trade_date": "2026-04-18",
                "strategy_id": "us_baseline",
                "signals": [{"instrument_id": "US.AAPL", "name": "Apple", "score": "0.8", "reason": "signal-old"}],
                "trade_suggestions": [{"instrument_id": "US.AAPL", "name": "Apple", "side": "BUY", "qty": 10, "rationale": "suggestion-old"}],
                "review": {"verdict": "PASS", "comments": ["older"]},
                "paper_account": {"account_id": "web-paper-us", "latest_nav": "100000", "cash": "90000", "buying_power": "80000", "position_count": 1, "trade_count": 1},
                "paper_run_summary": {"account_id": "web-paper-us", "strategy_id": "us_baseline", "trade_count": 1, "position_count": 1, "cash": "90000", "buying_power": "80000"},
            },
            {
                "market": "US",
                "trade_date": "2026-04-19",
                "strategy_id": "us_quality_focus",
                "signals": [{"instrument_id": "US.MSFT", "name": "Microsoft", "score": "0.9", "reason": "signal-new"}],
                "trade_suggestions": [{"instrument_id": "US.MSFT", "name": "Microsoft", "side": "BUY", "qty": 5, "rationale": "suggestion-new"}],
                "review": {"verdict": "REVIEW", "comments": ["newer", "check risk"]},
                "paper_account": {"account_id": "web-paper-us", "latest_nav": "101000", "cash": "91000", "buying_power": "81000", "position_count": 2, "trade_count": 2},
                "paper_run_summary": {"account_id": "web-paper-us", "strategy_id": "us_quality_focus", "trade_count": 2, "position_count": 2, "cash": "91000", "buying_power": "81000"},
            },
        ]
        latest_run_ref = self.app._run_result_ref(self.app.state.last_run_results[-1])

        response = self.app.render_home({"view": ["run"], "subview": ["detail"], "run_ref": [latest_run_ref]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Run Detail / 运行详情", body)
        self.assertIn("Execution Snapshot / 执行摘要", body)
        self.assertIn("Task Review / 任务审核", body)
        self.assertIn("US.MSFT · Microsoft", body)
        self.assertIn("suggestion-new", body)
        self.assertIn("REVIEW", body)
        self.assertNotIn("Simulated Account Effect / 模拟盘影响", body)
        self.assertIn("101000", body)

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_home_page_run_detail_view_shows_empty_state_for_unknown_run_ref(self, mock_ledger_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.latest_account_overview.return_value = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "80000",
            "position_count": 0,
            "trade_count": 0,
            "filtered_trade_count": 0,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": None,
            "filter_end_date": None,
        }
        ledger.list_accounts.return_value = ["web-paper-us"]
        ledger.account_overview.return_value = ledger.latest_account_overview.return_value
        self.app.state.last_run_results = [
            {
                "market": "US",
                "trade_date": "2026-04-19",
                "strategy_id": "us_quality_focus",
                "signals": [{"instrument_id": "US.MSFT", "score": "0.9", "reason": "signal-new"}],
                "trade_suggestions": [{"instrument_id": "US.MSFT", "side": "BUY", "qty": 5, "rationale": "suggestion-new"}],
                "review": {"verdict": "REVIEW", "comments": ["newer"]},
                "paper_account": {"account_id": "web-paper-us", "latest_nav": "101000", "cash": "91000", "buying_power": "81000", "position_count": 2, "trade_count": 2},
                "paper_run_summary": {"account_id": "web-paper-us", "strategy_id": "us_quality_focus", "trade_count": 2, "position_count": 2, "cash": "91000", "buying_power": "81000"},
            }
        ]

        response = self.app.render_home({"view": ["run"], "subview": ["detail"], "run_ref": ["missing-run-ref"]})
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Run Detail / 运行详情", body)
        self.assertIn("先执行一次策略运行后", body)
        self.assertNotIn("US.MSFT", body)

    def test_run_result_ref_distinguishes_duplicate_market_strategy_runs(self) -> None:
        older_run = {
            "market": "US",
            "trade_date": "2026-04-19",
            "strategy_id": "us_quality_focus",
            "signals": [{"instrument_id": "US.MSFT", "score": "0.9", "reason": "signal-old"}],
            "trade_suggestions": [{"instrument_id": "US.MSFT", "side": "BUY", "qty": 5, "rationale": "suggestion-old"}],
            "review": {"verdict": "REVIEW", "comments": ["older"]},
        }
        newer_run = {
            "market": "US",
            "trade_date": "2026-04-19",
            "strategy_id": "us_quality_focus",
            "signals": [{"instrument_id": "US.NVDA", "score": "0.95", "reason": "signal-new"}],
            "trade_suggestions": [{"instrument_id": "US.NVDA", "side": "BUY", "qty": 8, "rationale": "suggestion-new"}],
            "review": {"verdict": "PASS", "comments": ["newer"]},
        }

        self.assertNotEqual(self.app._run_result_ref(older_run), self.app._run_result_ref(newer_run))

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_supports_paper_view_subview_tabs(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({"view": ["paper"], "subview": ["ledger"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("section-tabs", body)
        self.assertIn('data-subview="holdings"', body)
        self.assertIn("Holdings / 持仓", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_paper_subview_tabs_preserve_filters(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home(
            {
                "view": ["paper"],
                "subview": ["main"],
                "paper_account_id": ["web-paper-us"],
                "paper_start_date": ["2026-04-01"],
                "paper_end_date": ["2026-04-30"],
            }
        )
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("paper_account_id=web-paper-us", body)
        self.assertIn("paper_start_date=2026-04-01", body)
        self.assertIn("paper_end_date=2026-04-30", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_create_view_renders_experiment_forms_only(self, _mock_config, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({"view": ["optimize"], "subview": ["create"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Strategy Experiments / 策略实验", body)
        self.assertIn("Factor Backtest / 因子回测", body)
        self.assertIn('id="factor-backtest-form"', body)
        self.assertIn('data-subview="create"', body)
        self.assertIn("section-tabs", body)
        self.assertNotIn("Strategy Tasks / 策略任务", body)
        self.assertNotIn('data-async-job-form="strategy_run"', body)
        self.assertNotIn("Current Defaults / 当前默认配置", body)
        self.assertNotIn("Recent Execution / 最近执行反馈", body)
        self.assertNotIn("Current Strategy / 当前策略", body)
        self.assertNotIn("Detail / 详情", body)
        self.assertIn('type="date" name="factor_start_date"', body)
        self.assertIn('type="date" name="factor_end_date"', body)
        self.assertIn('type="number" min="1" max="10" step="1" name="factor_top_n"', body)
        self.assertIn('type="number" min="1" step="1" name="factor_initial_cash"', body)
        self.assertIn(f'value="{DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_start_date"]}"', body)
        self.assertIn(f'value="{DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_end_date"]}"', body)
        self.assertIn('value="10"', body)
        self.assertIn('value="50"', body)
        self.assertIn('value="200"', body)
        self.assertIn('name="factor_auto_iterate"', body)
        self.assertIn('name="factor_max_generations"', body)
        self.assertIn("均线多头排列", body)
        self.assertIn("突破强度", body)
        self.assertIn("量价确认", body)
        self.assertIn("回调韧性", body)
        self.assertNotIn('name="factor_turnover_cap"', body)
        self.assertNotIn('name="factor_rebalance_buffer"', body)

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_paper_workspace_uses_date_inputs_for_filters(self, mock_ledger_cls) -> None:
        ledger = mock_ledger_cls.return_value
        overview = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "100000",
            "buying_power": "100000",
            "position_count": 0,
            "trade_count": 0,
            "filtered_trade_count": 0,
            "latest_nav": "100000",
            "cumulative_return": "0",
            "positions": [],
            "nav_history": [],
            "recent_trades": [],
            "today_summary": {},
            "sector_exposure_rows": [],
            "risk_alerts": [],
            "position_rows": [],
            "filter_start_date": "2026-04-01",
            "filter_end_date": "2026-04-30",
        }
        ledger.account_overview.return_value = overview
        ledger.latest_account_overview.return_value = overview
        ledger.list_accounts.return_value = ["web-paper-cn", "web-paper-us"]
        response = self.app.render_home({"view": ["paper"], "subview": ["main"], "paper_account_id": ["web-paper-us"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('type="date" name="paper_start_date" value="2026-04-01"', body)
        self.assertIn('type="date" name="paper_end_date" value="2026-04-30"', body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_renders_timeline_cards_only(self, _mock_config) -> None:
        self.app.state.last_factor_backtest_result = {
            "summary": {
                "market": "US",
                "subject_name": "美股因子回测",
                "start_date": "2026-01-02",
                "end_date": "2026-03-31",
                "total_return": "0.0821",
                "rolling_excess_return": "0.0215",
                "sharpe_ratio": "1.2200",
                "max_drawdown": "-0.0540",
                "average_turnover": "0.1200",
                "fee_drag": "0.0030",
                "average_excess_return": "0.0060",
                "average_win_rate": "0.5800",
                "observations": 15,
                "selected_factor_rows": [{"label": "20日相对强度", "effective_weight": "0.2200", "tilt": "1.2", "base_weight": "0.1500"}],
            },
            "attribution": {"scorecard": {"decision": "KEEP", "score": "0.8800", "rationale": "net=0.08"}},
            "artifacts": {"json": "/tmp/us_factor.json", "markdown": "/tmp/us_factor.md"},
        }
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-04-19",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-19",
                            "summary": {
                                "subject_name": "美股策略套件",
                                "decision": "KEEP",
                                "score": "1.8200",
                                "return": "0.1210",
                            },
                            "artifacts": {"json": "2026-04-19/us_strategy_suite.json"},
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Optimization Timeline / 优化时间线", body)
        self.assertIn("timeline-stack", body)
        self.assertIn("美股因子回测", body)
        self.assertIn("美股策略套件", body)
        self.assertIn("Decision / 结论: KEEP | Score / 评分: 0.8800", body)
        self.assertIn("Return / 收益: 0.0821 | Market / 市场: US", body)
        self.assertIn("Excess / 超额: 0.0215", body)
        self.assertIn("Open Detail / 打开详情", body)
        self.assertNotIn('id="factor-backtest-form"', body)
        self.assertNotIn("Current Defaults / 当前默认配置", body)
        self.assertNotIn("Recent Execution / 最近执行反馈", body)
        self.assertNotIn("Detail / 详情", body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_filters_out_paper_runs_before_limit(self, _mock_config) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            records = []
            for index in range(20):
                records.append(
                    {
                        "result_id": f"local_paper_run:US:web-paper-us:2026-04-{index+1:02d}",
                        "artifact_kind": "local_paper_run",
                        "market": "US",
                        "sort_date": f"2026-04-{index+1:02d}",
                        "summary": {"subject_name": f"paper-{index}", "decision": "RECORDED"},
                        "artifacts": {"json": f"local_paper/web-paper-us/runs/{index}.json"},
                    }
                )
            records.append(
                {
                    "result_id": "strategy_suite:US:2026-04-19",
                    "artifact_kind": "strategy_suite",
                    "market": "US",
                    "sort_date": "2026-04-19T23:59:00",
                    "summary": {"subject_name": "美股策略套件", "decision": "KEEP", "score": "1.8200", "return": "0.1210"},
                    "artifacts": {"json": "2026-04-19/us_strategy_suite.json"},
                }
            )
            write_json_artifact(artifact_root, "web/result_index.json", {"records": records})
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("美股策略套件", body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_shows_blocked_factor_events(self, _mock_config) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/task_logs.json",
                {
                    "entries": [
                        {
                            "created_at": "2026-05-02T23:26:54",
                            "category": "research",
                            "action": "factor_backtest",
                            "status": "BLOCKED",
                            "detail": "因子回测被运行守护拦截",
                            "metadata": {"market": "CN"},
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("因子回测被运行守护拦截", body)
        self.assertIn("BLOCKED", body)
        self.assertIn("Score / 评分: 事件", body)
        self.assertIn("Return / 收益: 未生成 | Market / 市场: CN", body)
        self.assertNotIn("Open Artifact / 打开工件", body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_shows_recent_queued_experiment_jobs(self, _mock_config) -> None:
        self.ops_store.load_state.return_value = {
            "active_job": None,
            "queued_jobs": [
                {
                    "job_id": "factor-job-1",
                    "kind": "factor_backtest",
                    "status": "QUEUED",
                    "stage": "QUEUED",
                    "detail": "Task accepted and waiting in queue.",
                    "metadata": {"market": "US"},
                    "created_at": "2026-05-06T10:00:00",
                    "progress_pct": 15,
                }
            ],
            "job_history": [],
            "audit_events": [],
            "heartbeats": {},
        }
        response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("QUEUED", body)
        self.assertIn("Task accepted and waiting in queue.", body)
        self.assertIn("Market / 市场: US", body)
        self.assertIn("15%", body)
        self.assertIn("job-progress__bar", body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_prioritizes_success_event_above_older_indexed_results(self, _mock_config) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "factor_backtest:US:2026-03-31",
                            "artifact_kind": "factor_backtest",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {"subject_name": "旧实验", "decision": "KEEP", "score": "1.23", "return": "0.10"},
                            "artifacts": {"json": "2026-03-31/us_factor_backtest_old.json"},
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                ops_store = web_module.ProjectOpsStore(artifact_root)
                with patch("stock_quantification.sqlite_state._utc_now", return_value="2026-05-06T10:05:00"):
                    ops_store.append_event(
                        category="research",
                        action="factor_backtest",
                        status="SUCCESS",
                        detail="US 策略实验完成：20日相对强度、60日相对强度",
                        metadata={"job_id": "factor-job-2", "market": "US"},
                    )
                with patch.object(self.app, "_ops_store", return_value=ops_store):
                    response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("SUCCESS", body)
        self.assertIn("旧实验", body)
        self.assertLess(body.find("SUCCESS"), body.find("旧实验"))

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_links_success_event_to_matching_result(self, _mock_config) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "factor_backtest:CN:2026-05-06",
                            "artifact_kind": "factor_backtest",
                            "market": "CN",
                            "sort_date": "2026-05-06",
                            "summary": {
                                "subject_name": "CN 因子实验 / 20日相对强度、60日相对强度、趋势强度",
                                "decision": "REVIEW",
                                "score": "0.77",
                                "return": "0.24",
                                "excess_return": "0.05",
                            },
                            "artifacts": {"json": "2026-05-06/cn_factor_backtest_xxx.json"},
                        }
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "web/task_logs.json",
                {
                    "entries": [
                        {
                            "created_at": "2026-05-06T13:44:55",
                            "category": "research",
                            "action": "factor_backtest",
                            "status": "SUCCESS",
                            "detail": "CN 策略实验完成：20日相对强度、60日相对强度、趋势强度",
                            "metadata": {"market": "CN", "factors": "rel_ret_20,rel_ret_60,trend"},
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Open Detail / 打开详情", body)
        self.assertIn("Open Artifact / 打开工件", body)
        self.assertIn("Return / 收益: 0.24 | Market / 市场: CN", body)
        self.assertIn("Excess / 超额: 0.05", body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_links_success_event_to_next_day_result(self, _mock_config) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "factor_backtest:CN:2026-05-10",
                            "artifact_kind": "factor_backtest",
                            "market": "CN",
                            "sort_date": "2026-05-10",
                            "summary": {
                                "subject_name": "CN 因子实验 / 20日相对强度、60日相对强度、趋势强度、均线多头排列",
                                "decision": "REVIEW",
                                "score": "-0.77",
                                "return": "0.03",
                                "excess_return": "-0.22",
                            },
                            "artifacts": {"json": "2026-05-10/cn_factor_backtest_new.json"},
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                ops_store = web_module.ProjectOpsStore(artifact_root)
                with patch("stock_quantification.sqlite_state._utc_now", return_value="2026-05-09T18:26:01"):
                    ops_store.append_event(
                        category="research",
                        action="factor_backtest",
                        status="SUCCESS",
                        detail="CN 策略实验完成：20日相对强度、60日相对强度、趋势强度、均线多头排列",
                        metadata={"market": "CN", "factors": "rel_ret_20,rel_ret_60,trend,ma_trend_alignment"},
                    )
                with patch.object(self.app, "_ops_store", return_value=ops_store):
                    response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Open Detail / 打开详情", body)
        self.assertIn("Return / 收益: 0.03 | Market / 市场: CN", body)
        self.assertIn("Excess / 超额: -0.22", body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_shows_continue_button_for_failed_checkpointed_experiment(self, _mock_config) -> None:
        self.ops_store.list_events.return_value = [
            {
                "event_id": 101,
                "created_at": "2026-05-10T13:20:00",
                "category": "research",
                "action": "factor_backtest",
                "status": "FAILED",
                "detail": "因子回测失败：网络中断",
                "metadata": {"market": "US", "job_id": "factor-job-1"},
            }
        ]
        self.ops_store.sqlite.get_job.return_value = {
            "job_id": "factor-job-1",
            "kind": "factor_backtest",
            "status": "FAILED",
            "payload": {"checkpoint_key": "ckpt-us-1"},
            "metadata": {"market": "US"},
        }
        self.ops_store.sqlite.get_kv.return_value = {"processed_dates": 17}

        response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})

        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Continue / 继续", body)
        self.assertIn("/factor-backtest/continue", body)
        self.assertIn("从第 17 个样本后继续", body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_shows_eta_for_running_factor_backtest_job(self, _mock_config) -> None:
        self.ops_store.load_state.return_value = {
            "active_job": {
                "job_id": "factor-job-eta",
                "kind": "factor_backtest",
                "status": "RUNNING",
                "stage": "RUNNING_BACKTEST",
                "detail": "正在处理 2026-05-10 的因子样本 (20/100)。",
                "metadata": {
                    "current_trade_date": "2026-05-10",
                    "processed_dates": 20,
                    "total_dates": 100,
                    "elapsed_seconds": 60.0,
                },
                "created_at": "2026-05-10T13:30:00",
                "progress_pct": 26,
            },
            "queued_jobs": [],
            "job_history": [],
            "audit_events": [],
            "heartbeats": {},
        }

        response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})

        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("预计剩余", body)
        self.assertIn("26%", body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_shows_index_warning_when_index_is_invalid(self, _mock_config) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            (artifact_root / "web").mkdir(parents=True, exist_ok=True)
            (artifact_root / "web/result_index.json").write_text("{invalid", encoding="utf-8")
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Index Warning / 索引告警", body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_detail_view_renders_selected_result_and_strategy_candidates(self, _mock_config) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-04-19",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-19",
                            "summary": {
                                "subject_name": "美股策略套件",
                                "subject_id": "us_quality_focus",
                                "decision": "KEEP",
                                "score": "1.8200",
                                "return": "0.1210",
                            },
                            "artifacts": {"json": "2026-04-19/us_strategy_suite.json"},
                        }
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "2026-04-19/us_strategy_suite.json",
                {
                    "strategies": [
                        {
                            "preset_id": "us_quality_focus",
                            "display_name": "US Quality Focus",
                            "total_return": "0.1210",
                            "excess_return": "0.0320",
                            "max_drawdown": "-0.0410",
                            "scorecard": {
                                "decision": "KEEP",
                                "score": "1.8200",
                                "rationale": "quality edge",
                                "strengths": ["收益稳", "风险可控"],
                                "warnings": ["换手略高"],
                            },
                            "regime_summary": [
                                {"regime": "UP", "observations": 8, "average_period_return": "0.0050", "average_excess_period_return": "0.0020", "win_rate": "0.6250"}
                            ],
                            "alpha_mix": [
                                {"family": "momentum", "net_weight": "0.4200", "gross_weight": "0.4200", "share_of_gross": "0.5300"}
                            ],
                        }
                    ],
                    "recommended_presets": ["us_quality_focus", "us_baseline"],
                    "watchlist_presets": ["us_defensive", "us_low_volatility"],
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home(
                    {
                        "view": ["optimize"],
                        "subview": ["detail"],
                        "artifact": ["2026-04-19/us_strategy_suite.json"],
                    }
                )
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("US Quality Focus", body)
        self.assertIn("Strategy Experiments / 策略实验", body)
        self.assertIn("Champion Candidate", body)
        self.assertIn("Challenger Candidate", body)
        self.assertIn("当前详情不是可晋升实验，或已经是正式策略结果。", body)
        self.assertIn("recommended_presets", body)
        self.assertIn("watchlist_presets", body)
        self.assertNotIn("Factor Backtest / 因子回测", body)
        self.assertNotIn("Optimization Timeline / 优化时间线", body)
        self.assertNotIn('id="factor-backtest-form"', body)

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_detail_view_shows_empty_state_for_missing_artifact(self, _mock_config) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-04-19",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-19",
                            "summary": {"subject_name": "美股策略套件", "decision": "KEEP"},
                            "artifacts": {"json": "2026-04-19/us_strategy_suite.json"},
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home(
                    {
                        "view": ["optimize"],
                        "subview": ["detail"],
                        "artifact": ["2026-04-19/does-not-exist.json"],
                    }
                )
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Experiment Detail / 实验详情", body)
        self.assertIn("先运行一次实验或选择一个历史工件后", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_renders_paper_first_shell_without_legacy_overview_content(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertIn("Project Status", body)
        self.assertIn("primary-nav", body)
        self.assertIn("section-tabs", body)
        self.assertNotIn("Research Workbench / 研究工作台", body)
        self.assertNotIn("Morning Brief / 今日总览", body)
        self.assertNotIn('data-async-job-form="strategy_run"', body)
        self.assertNotIn('id="factor-backtest-form"', body)
        self.assertNotIn("和我交互", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_renders_indexed_research_results(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-03-31",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {
                                "subject_id": "us_baseline",
                                "subject_name": "美股基线质量动量",
                                "decision": "KEEP",
                                "score": "1.2345",
                                "return": "0.1200",
                            },
                            "artifacts": {"json": "2026-03-31/us_strategy_suite.json"},
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["results"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="champions"', body)
        self.assertIn("Champion / 冠军", body)
        self.assertIn("美股基线质量动量", body)
        self.assertIn("KEEP", body)
        self.assertIn("0.1200", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_separates_research_and_runtime_indexed_results(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-03-31",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {
                                "subject_name": "美股基线质量动量",
                                "decision": "KEEP",
                                "score": "1.2345",
                                "return": "0.1200",
                            },
                            "artifacts": {"json": "2026-03-31/us_strategy_suite.json"},
                        },
                        {
                            "result_id": "local_paper_run:US:web-paper-us:2026-04-18T10:00:00",
                            "artifact_kind": "local_paper_run",
                            "market": "US",
                            "sort_date": "2026-04-18T10:00:00",
                            "summary": {
                                "subject_name": "web-paper-us / us_quality_momentum",
                                "decision": "RECORDED",
                                "score": 2,
                                "return": "80000",
                            },
                            "artifacts": {"json": "local_paper/web-paper-us/runs/demo.json"},
                        },
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["results"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Champion / 冠军", body)
        self.assertIn("Challenger / 挑战者", body)
        self.assertIn("Drop / 淘汰", body)
        self.assertIn("Archive / 归档", body)
        self.assertNotIn("Research Results / 研究结果中心", body)
        self.assertNotIn("Runtime Results / 运行结果", body)

    def test_results_page_renders_archive_subview_and_legacy_artifact_detail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-03-31",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {
                                "subject_name": "美股基线质量动量",
                                "subject_id": "us_baseline",
                                "decision": "KEEP",
                                "score": "1.2345",
                                "return": "0.1200",
                                "result_type": "strategy_suite",
                                "rationale": "质量和动量信号同时稳定。",
                            },
                            "artifacts": {"json": "2026-03-31/us_strategy_suite.json"},
                        },
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "2026-03-31/us_strategy_suite.json",
                {
                    "summary": {
                        "market": "US",
                        "runtime_mode": "PAPER",
                        "total_return": "0.1200",
                        "final_nav": "100000",
                        "buy_fill_count": "3",
                        "sell_fill_count": "1",
                        "trade_count": "4",
                    },
                },
            )
            write_json_artifact(
                artifact_root,
                "web/strategy_state.json",
                {"markets": {"US": {"champion_preset_id": "us_baseline", "challenger_preset_id": None, "current_execution_preset_id": None}}},
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["results"], "subview": ["archive"], "artifact": ["2026-03-31/us_strategy_suite.json"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="archive"', body)
        self.assertIn("Archive / 归档", body)
        self.assertIn("美股基线质量动量", body)
        self.assertIn("Result Detail / 结果详情", body)
        self.assertIn("Mode / 模式", body)
        self.assertNotIn("Normalized Summary / 统一摘要", body)
        self.assertNotIn("Research Results / 研究结果中心", body)
        self.assertNotIn("Runtime Results / 运行结果", body)

    def test_results_page_archive_subview_shows_empty_detail_for_unknown_artifact(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-03-31",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {
                                "subject_name": "美股基线质量动量",
                                "subject_id": "us_baseline",
                                "decision": "KEEP",
                                "score": "1.2345",
                                "return": "0.1200",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-03-31/us_strategy_suite.json"},
                        },
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "2026-03-31/us_strategy_suite.json",
                {
                    "normalized_summary": {
                        "subject_name": "美股基线质量动量",
                        "decision": "KEEP",
                    }
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home(
                    {
                        "view": ["results"],
                        "subview": ["archive"],
                        "artifact": ["2026-03-31/missing.json"],
                    }
        )
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Result Detail / 结果详情", body)
        self.assertIn("当前没有选中的 Artifact 工件", body)
        self.assertNotIn("美股基线质量动量", body.split("Result Detail / 结果详情", 1)[-1])

    def test_results_page_archive_subview_preserves_artifact_links(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:US:2026-03-31",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-03-31",
                            "summary": {
                                "subject_name": "美股基线质量动量",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-03-31/us_strategy_suite.json"},
                        },
                        {
                            "result_id": "local_paper_run:US:web-paper-us:2026-04-18T10:00:00",
                            "artifact_kind": "local_paper_run",
                            "market": "US",
                            "sort_date": "2026-04-18T10:00:00",
                            "summary": {
                                "subject_name": "web-paper-us / us_quality_momentum",
                                "result_type": "local_paper_run",
                            },
                            "artifacts": {"json": "local_paper/web-paper-us/runs/demo.json"},
                        },
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "local_paper/web-paper-us/runs/demo.json",
                {
                    "normalized_summary": {
                        "subject_name": "web-paper-us / us_quality_momentum",
                        "decision": "RECORDED",
                        "rationale": "记录模拟盘执行结果。",
                    }
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home(
                    {
                        "view": ["results"],
                        "subview": ["archive"],
                    }
                )
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('data-subview="archive"', body)
        self.assertIn("/?view=results&subview=archive&artifact=local_paper/web-paper-us/runs/demo.json", body)
        self.assertIn("web-paper-us / us_quality_momentum", body)
        self.assertIn("美股基线质量动量", body)

    def test_result_center_works_when_result_index_is_backed_by_sqlite(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            seed_result_index_sqlite(
                artifact_root,
                [
                    {
                        "result_id": "strategy_suite:US:2026-04-19",
                        "artifact_kind": "strategy_suite",
                        "market": "US",
                        "sort_date": "2026-04-19",
                        "summary": {
                            "subject_name": "美股 SQLite 策略套件",
                            "decision": "KEEP",
                            "result_type": "strategy_suite",
                        },
                        "artifacts": {"json": "2026-04-19/us_sqlite_strategy_suite.json"},
                    }
                ],
            )
            write_json_artifact(
                artifact_root,
                "2026-04-19/us_sqlite_strategy_suite.json",
                {
                    "summary": {
                        "subject_name": "美股 SQLite 策略套件",
                        "decision": "KEEP",
                        "rationale": "artifact detail remains file-backed",
                    }
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home(
                    {
                        "view": ["results"],
                        "subview": ["archive"],
                        "artifact": ["2026-04-19/us_sqlite_strategy_suite.json"],
                    }
                )
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Archive / 总归档", body)
        self.assertIn("/?view=results&subview=archive&artifact=2026-04-19/us_sqlite_strategy_suite.json", body)
        self.assertNotIn("当前分组没有匹配结果", body)
        self.assertIn("/artifact-file?path=2026-04-19/us_sqlite_strategy_suite.json", body)

    def test_results_page_archive_subview_shows_late_record(self) -> None:
        records = []
        for month in range(5, 9):
            for day in range(1, 13):
                if len(records) >= 45:
                    break
                records.append(
                    {
                        "result_id": f"strategy_suite:US:2026-{month:02d}-{day:02d}",
                        "artifact_kind": "strategy_suite",
                        "market": "US",
                        "sort_date": f"2026-{month:02d}-{day:02d}",
                        "summary": {
                            "subject_name": f"baseline-{len(records) + 1}",
                            "result_type": "strategy_suite",
                        },
                        "artifacts": {"json": f"2026-{month:02d}-{day:02d}/baseline.json"},
                    }
                )
            if len(records) >= 45:
                break
        records.append(
            {
                "result_id": "local_paper_run:US:web-paper-us:2026-04-18T10:00:00",
                "artifact_kind": "local_paper_run",
                "market": "US",
                "sort_date": "2026-04-18T10:00:00",
                "summary": {
                    "subject_name": "late runtime hit",
                    "result_type": "local_paper_run",
                },
                "artifacts": {"json": "local_paper/web-paper-us/runs/late-hit.json"},
            }
        )
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(artifact_root, "web/result_index.json", {"records": records})
            write_json_artifact(
                artifact_root,
                "local_paper/web-paper-us/runs/late-hit.json",
                {"normalized_summary": {"subject_name": "late runtime hit", "decision": "RECORDED"}},
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home(
                    {
                        "view": ["results"],
                        "subview": ["archive"],
                    }
                )
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("late runtime hit", body)
        self.assertIn("baseline-45", body)

    def test_results_page_archive_subview_keeps_descending_sort_order(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "local_paper_run:US:web-paper-us:2026-04-18T10:00:00",
                            "artifact_kind": "local_paper_run",
                            "market": "US",
                            "sort_date": "2026-04-18T10:00:00",
                            "summary": {
                                "subject_name": "same day runtime",
                                "result_type": "local_paper_run",
                            },
                            "artifacts": {"json": "local_paper/web-paper-us/runs/same-day.json"},
                        },
                        {
                            "result_id": "local_paper_run:US:web-paper-us:2026-04-19T09:00:00",
                            "artifact_kind": "local_paper_run",
                            "market": "US",
                            "sort_date": "2026-04-19T09:00:00",
                            "summary": {
                                "subject_name": "next day runtime",
                                "result_type": "local_paper_run",
                            },
                            "artifacts": {"json": "local_paper/web-paper-us/runs/next-day.json"},
                        },
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "local_paper/web-paper-us/runs/same-day.json",
                {"normalized_summary": {"subject_name": "same day runtime", "decision": "RECORDED"}},
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home(
                    {
                        "view": ["results"],
                        "subview": ["archive"],
                    }
                )
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("same day runtime", body)
        self.assertIn("next day runtime", body)
        self.assertLess(body.index("next day runtime"), body.index("same day runtime"))

    def test_results_page_champions_subview_sorts_multi_market_rows_by_latest_result(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "strategy_suite:CN:2026-04-18",
                            "artifact_kind": "strategy_suite",
                            "market": "CN",
                            "sort_date": "2026-04-18",
                            "summary": {
                                "subject_id": "cn_baseline",
                                "subject_name": "A股冠军策略",
                                "decision": "KEEP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-18/cn_baseline.json"},
                        },
                        {
                            "result_id": "strategy_suite:US:2026-04-20",
                            "artifact_kind": "strategy_suite",
                            "market": "US",
                            "sort_date": "2026-04-20",
                            "summary": {
                                "subject_id": "us_baseline",
                                "subject_name": "美股冠军策略",
                                "decision": "KEEP",
                                "result_type": "strategy_suite",
                            },
                            "artifacts": {"json": "2026-04-20/us_baseline.json"},
                        },
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "web/strategy_state.json",
                {
                    "markets": {
                        "CN": {
                            "champion_preset_id": "cn_baseline",
                            "challenger_preset_id": None,
                            "current_execution_preset_id": None,
                        },
                        "US": {
                            "champion_preset_id": "us_baseline",
                            "challenger_preset_id": None,
                            "current_execution_preset_id": None,
                        },
                    }
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home({"view": ["results"], "subview": ["champions"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("A股冠军策略", body)
        self.assertIn("美股冠军策略", body)
        self.assertLess(body.index("美股冠军策略"), body.index("A股冠军策略"))

    def test_results_page_legacy_runtime_subview_alias_falls_back_to_archive(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "local_paper_run:US:web-paper-us:2026-04-18T10:00:00",
                            "artifact_kind": "local_paper_run",
                            "market": "US",
                            "sort_date": "2026-04-18T10:00:00",
                            "summary": {
                                "subject_name": "web-paper-us / us_quality_momentum",
                                "decision": "RECORDED",
                                "result_type": "local_paper_run",
                            },
                            "artifacts": {"json": "local_paper/web-paper-us/runs/demo.json"},
                        },
                    ]
                },
            )
            write_json_artifact(
                artifact_root,
                "local_paper/web-paper-us/runs/demo.json",
                {
                    "normalized_summary": {
                        "subject_name": "web-paper-us / us_quality_momentum",
                        "decision": "RECORDED",
                    }
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.render_home(
                    {
                        "view": ["results"],
                        "subview": ["runtime"],
                        "artifact": ["local_paper/web-paper-us/runs/demo.json"],
                    }
                )
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('<body class="dashboard-app" data-primary-view="results" data-subview="archive">', body)
        self.assertIn("Archive / 归档", body)
        self.assertIn("web-paper-us / us_quality_momentum", body)
        self.assertIn("Normalized Summary / 统一摘要", body)

    @patch.object(DashboardApp, "_load_factor_backtest_lineage_summary")
    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_renders_strategy_lab_result_sections(
        self,
        _mock_paper_panel,
        _mock_symbol_catalog,
        mock_load_lineage_summary,
    ) -> None:
        mock_load_lineage_summary.return_value = {
            "status": "STOPPED",
            "stop_reason": "已达到最大代次 3。",
            "last_decision": "KEEP",
            "last_job_id": "factor-job-3",
        }
        self.app.state.last_factor_backtest_result = {
            "summary": {
                "market": "US",
                "start_date": "2026-01-02",
                "end_date": "2026-03-31",
                "total_return": "0.0821",
                "rolling_excess_return": "0.0215",
                "benchmark_total_return": "0.0606",
                "sharpe_ratio": "1.2200",
                "max_drawdown": "-0.0540",
                "average_turnover": "0.1200",
                "fee_drag": "0.0030",
                "average_excess_return": "0.0060",
                "average_win_rate": "0.5800",
                "observations": 15,
                "auto_iterate": True,
                "generation": 3,
                "max_generations": 3,
                "lineage_id": "lineage-us-1",
                "mutation_reason": "上涨状态下跑输基准，转向突破确认与回调修复。",
                "selected_factor_rows": [{"label": "20日相对强度", "effective_weight": "0.2200", "tilt": "1.2", "base_weight": "0.1500"}],
            },
            "signal_validation": {"daily": [{"trade_date": "2026-03-12", "equal_weight_return": "0.0120", "excess_return": "0.0050", "win_rate": "0.6000"}]},
            "rolling_backtest": {
                "daily": [
                    {"trade_date": "2026-03-12", "end_of_day_nav": "100000", "benchmark_nav": "100000", "benchmark_period_return": "0.0000", "cumulative_benchmark_return": "0.0000"},
                    {"trade_date": "2026-03-13", "end_of_day_nav": "101200", "benchmark_nav": "100600", "period_return": "0.0120", "benchmark_period_return": "0.0060", "cumulative_portfolio_return": "0.0120", "cumulative_benchmark_return": "0.0060", "turnover": "0.0800", "total_fees": "12.5"},
                ],
                "summary": {
                    "final_nav": "108210.0000",
                    "benchmark_final_nav": "106060.0000",
                    "benchmark_total_return": "0.0606",
                    "excess_return": "0.0215",
                    "trend_exit_count": 2,
                    "rank_exit_count": 1,
                    "risk_exit_count": 1,
                    "other_exit_count": 0,
                },
                "exit_events": [
                    {
                        "trade_date": "2026-03-13",
                        "instrument_id": "US.AAPL",
                        "name": "Apple",
                        "reason_label": "趋势失效",
                        "detail": "trend=-0.3000，目标仓位降到 0。",
                    }
                ],
            },
            "attribution": {
                "alpha_mix": [{"family": "momentum", "net_weight": "0.4200", "gross_weight": "0.4200", "share_of_gross": "0.5300"}],
                "regime_summary": [{"regime": "UP", "observations": 8, "average_period_return": "0.0050", "average_excess_period_return": "0.0020", "win_rate": "0.6250"}],
                "scorecard": {"decision": "KEEP", "score": "0.8800", "rationale": "net=0.08", "strengths": ["净收益为正"], "warnings": ["换手略高"]},
                "iteration_notes": [{"level": "good", "title": "继续跟踪", "detail": "保持当前结构，下一轮微调动量强度。"}],
            },
            "artifacts": {"json": "/tmp/us_factor.json", "markdown": "/tmp/us_factor.md"},
        }
        response = self.app.render_home({"view": ["optimize"], "subview": ["detail"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Factor Setup / 因子配置", body)
        self.assertIn("Regime Attribution / 市场状态归因", body)
        self.assertIn("Alpha Mix / 因子家族暴露", body)
        self.assertIn("Exit Signals / 退出信号", body)
        self.assertIn("趋势失效", body)
        self.assertIn("Strategy NAV / 策略净值", body)
        self.assertIn("Benchmark NAV / 基准净值", body)
        self.assertIn("Benchmark Return / 基准收益", body)
        self.assertIn("Excess Return / 超额收益", body)
        self.assertIn("Next Iteration / 下一轮迭代建议", body)
        self.assertIn("Generation / 代次", body)
        self.assertIn("Evolution Status / 进化状态", body)
        self.assertIn("STOPPED", body)
        self.assertIn("已达到最大代次 3。", body)
        self.assertNotIn('id="factor-backtest-form"', body)

    def test_chat_echo_and_path_safety(self) -> None:
        response = self.app.handle_chat({"message": ["你好，给我看今天的回测结果"]})
        self.assertEqual(response.status, 303)
        self.assertEqual(len(self.app.state.chat_messages), 2)
        self.assertIsNone(self.app._safe_artifact_path("../README.md"))

    def test_render_flash_messages_consumes_messages_after_display(self) -> None:
        self.app.state.push_flash("第一条错误")
        self.app.state.push_flash("第二条错误")
        first_html = self.app._render_flash_messages()
        second_html = self.app._render_flash_messages()
        self.assertIn("第一条错误", first_html)
        self.assertIn("第二条错误", first_html)
        self.assertEqual(second_html, "")

    def test_scoped_flash_messages_only_render_on_target_page(self) -> None:
        self.app.state.push_flash("策略优化错误", audience="optimize")
        paper_html = self.app._render_flash_messages("paper")
        optimize_html = self.app._render_flash_messages("optimize")
        self.assertEqual(paper_html, "")
        self.assertIn("策略优化错误", optimize_html)
        self.assertEqual(self.app._render_flash_messages("optimize"), "")

    @patch.object(DashboardApp, "_run_factor_backtest")
    def test_factor_backtest_updates_state_and_redirects(self, mock_run_factor_backtest) -> None:
        mock_run_factor_backtest.return_value = {
            "summary": {
                "subject_id": "cn_strategy_lab:2026-01-02:2026-03-31:test",
                "subject_name": "CN 因子实验 / 20日相对强度、60日相对强度",
                "market": "CN",
                "start_date": "2026-01-02",
                "end_date": "2026-03-31",
                "selected_factors": ["rel_ret_20", "rel_ret_60"],
                "average_return": "0.0123",
                "average_excess_return": "0.0088",
                "average_win_rate": "0.5500",
                "observations": 12,
                "best_trade_date": "2026-03-11",
                "total_return": "0.0432",
                "rolling_excess_return": "0.0111",
                "max_drawdown": "-0.0220",
            },
            "attribution": {"scorecard": {"decision": "REVIEW", "score": "0.77", "rationale": "test rationale"}},
            "artifacts": {"json": "/tmp/cn_factor.json", "markdown": "/tmp/cn_factor.md"},
        }
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    with patch.object(self.app, "_ensure_job_worker_running"), patch.object(self.app._job_worker_wakeup_event, "set"):
                        response = self.app.handle_factor_backtest(
                            {
                                "view": ["optimize"],
                                "factor_market": ["CN"],
                                "factor": ["rel_ret_20", "rel_ret_60"],
                                "factor_start_date": ["2026-01-02"],
                                "factor_end_date": ["2026-03-31"],
                                "factor_holding_sessions": ["5"],
                                "factor_detail_limit": ["50"],
                                "factor_history_limit": ["200"],
                                "factor_top_n": ["10"],
                                "factor_initial_cash": ["100000"],
                                "factor_tilt_rel_ret_20": ["1.2"],
                                "factor_tilt_rel_ret_60": ["0.8"],
                            }
                        )
                        self.app._drain_job_queue_once()
                recorded_index = web_module.read_json_artifact(artifact_root, "web/result_index.json")
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=optimize&subview=create")
        self.assertEqual(self.app.state.last_factor_backtest_result["summary"]["market"], "CN")
        self.assertEqual(recorded_index["records"][0]["artifact_kind"], "factor_backtest")
        self.assertEqual(recorded_index["records"][0]["summary"]["subject_name"], "CN 因子实验 / 20日相对强度、60日相对强度")

    @patch.object(DashboardApp, "_run_factor_backtest")
    def test_factor_backtest_falls_back_to_hidden_factor_payload(self, mock_run_factor_backtest) -> None:
        mock_run_factor_backtest.return_value = {
            "summary": {"market": "CN", "selected_factors": ["rel_ret_20"], "total_return": "0.0100"},
            "attribution": {"scorecard": {"decision": "REVIEW"}},
            "artifacts": {"json": "/tmp/cn_factor.json", "markdown": "/tmp/cn_factor.md"},
        }
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    with patch.object(self.app, "_ensure_job_worker_running"), patch.object(self.app._job_worker_wakeup_event, "set"):
                        response = self.app.handle_factor_backtest(
                            {
                                "factor_market": ["CN"],
                                "factor_selection_payload": ["rel_ret_20,trend"],
                                "factor_start_date": ["2026-01-02"],
                                "factor_end_date": ["2026-03-31"],
                                "factor_holding_sessions": ["5"],
                                "factor_detail_limit": ["50"],
                                "factor_history_limit": ["200"],
                                "factor_top_n": ["10"],
                                "factor_initial_cash": ["100000"],
                            }
                        )
                        self.app._drain_job_queue_once()
        self.assertEqual(response.status, 303)
        args = mock_run_factor_backtest.call_args.kwargs
        self.assertEqual(args["selected_factors"], ["rel_ret_20", "trend"])

    @patch.object(DashboardApp, "_run_factor_backtest")
    def test_factor_backtest_falls_back_to_tilt_fields_when_selection_missing(self, mock_run_factor_backtest) -> None:
        mock_run_factor_backtest.return_value = {
            "summary": {"market": "CN", "selected_factors": ["rel_ret_20"], "total_return": "0.0100"},
            "attribution": {"scorecard": {"decision": "REVIEW"}},
            "artifacts": {"json": "/tmp/cn_factor.json", "markdown": "/tmp/cn_factor.md"},
        }
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    with patch.object(self.app, "_ensure_job_worker_running"), patch.object(self.app._job_worker_wakeup_event, "set"):
                        response = self.app.handle_factor_backtest(
                            {
                                "factor_market": ["CN"],
                                "factor_start_date": ["2026-01-02"],
                                "factor_end_date": ["2026-03-31"],
                                "factor_holding_sessions": ["5"],
                                "factor_detail_limit": ["50"],
                                "factor_history_limit": ["200"],
                                "factor_top_n": ["10"],
                                "factor_initial_cash": ["100000"],
                                "factor_tilt_rel_ret_20": ["1.0"],
                                "factor_tilt_rel_ret_60": ["1.0"],
                                "factor_tilt_trend": ["1.0"],
                                "factor_tilt_quality": ["1.0"],
                            }
                        )
                        self.app._drain_job_queue_once()
        self.assertEqual(response.status, 303)
        args = mock_run_factor_backtest.call_args.kwargs
        self.assertEqual(args["selected_factors"], ["rel_ret_20", "rel_ret_60", "trend"])

    @patch("stock_quantification.web.run_market")
    def test_local_paper_run_updates_dashboard_state(self, mock_run_market) -> None:
        mock_run_market.return_value = {
            "market": "US",
            "artifacts": {"json": "/tmp/us_run.json", "markdown": "/tmp/us_run.md"},
            "paper_account": {
                "account_id": "web-paper-us",
                "market": "US",
                "cash": "80000",
                "buying_power": "80000",
                "position_count": 1,
                "trade_count": 2,
                "filtered_trade_count": 1,
                "latest_nav": "100500.0000",
                "cumulative_return": "0.0050",
                "positions": [{"instrument_id": "US.AAPL", "qty": 10, "avg_cost": "200"}],
                "nav_history": [{"trade_date": "2026-04-05", "nav": "100000.0000"}, {"trade_date": "2026-04-06", "nav": "100500.0000"}],
                "recent_trades": [{"trade_date": "2026-04-06", "side": "BUY", "instrument_id": "US.AAPL", "filled_qty": 10, "estimated_price": "200", "cash_delta": "-2000"}],
            },
            "paper_trade_records": [{"instrument_id": "US.AAPL"}],
        }
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    with patch.object(self.app, "_ensure_job_worker_running"), patch.object(self.app._job_worker_wakeup_event, "set"):
                        response = self.app.handle_run(
                            {
                                "market": ["US"],
                                "runtime_mode": ["LIVE"],
                                "execution_mode": ["AUTO"],
                                "broker": ["LOCAL_PAPER"],
                                "route_orders": ["on"],
                                "broker_account_id": ["web-paper-us"],
                                "selected_strategy_us": ["us_quality_focus"],
                                "cash": ["100000"],
                                "top_n": ["2"],
                                "detail_limit": ["10"],
                                "history_limit": ["90"],
                                "beta_window": ["20"],
                                "forward_days": ["0"],
                                "symbols_us": ["AAPL"],
                            }
                        )
                        self.app._drain_job_queue_once()
        self.assertEqual(response.status, 303)
        self.assertEqual(mock_run_market.call_args.kwargs["selected_preset_id"], "us_quality_focus")
        self.assertEqual(self.app.state.last_local_paper_account["account_id"], "web-paper-us")

    @patch("stock_quantification.web.run_market")
    def test_strategy_run_appends_history_across_submissions(self, mock_run_market) -> None:
        mock_run_market.side_effect = [
            {
                "market": "US",
                "trade_date": "2026-04-18",
                "strategy_id": "us_baseline",
                "review": {"verdict": "PASS", "comments": ["older"]},
                "paper_trade_records": [],
            },
            {
                "market": "US",
                "trade_date": "2026-04-19",
                "strategy_id": "us_quality_focus",
                "review": {"verdict": "REVIEW", "comments": ["newer"]},
                "paper_trade_records": [],
            },
        ]

        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    with patch.object(self.app, "_ensure_job_worker_running"), patch.object(self.app._job_worker_wakeup_event, "set"):
                        first_response = self.app.handle_run(
                            {
                                "market": ["US"],
                                "runtime_mode": ["PAPER"],
                                "execution_mode": ["ADVISORY"],
                                "cash": ["100000"],
                                "top_n": ["2"],
                                "detail_limit": ["10"],
                                "history_limit": ["90"],
                                "beta_window": ["20"],
                                "forward_days": ["0"],
                                "selected_strategy_us": ["us_baseline"],
                            }
                        )
                        self.app._drain_job_queue_once()
                        second_response = self.app.handle_run(
                            {
                                "market": ["US"],
                                "runtime_mode": ["PAPER"],
                                "execution_mode": ["ADVISORY"],
                                "cash": ["100000"],
                                "top_n": ["2"],
                                "detail_limit": ["10"],
                                "history_limit": ["90"],
                                "beta_window": ["20"],
                                "forward_days": ["0"],
                                "selected_strategy_us": ["us_quality_focus"],
                            }
                        )
                        self.app._drain_job_queue_once()
                persisted_history = web_module.ProjectOpsStore(artifact_root).list_run_history(limit=10)

        self.assertEqual(first_response.status, 303)
        self.assertEqual(second_response.status, 303)
        self.assertEqual(len(self.app.state.last_run_results), 2)
        self.assertEqual(self.app.state.last_run_results[0]["strategy_id"], "us_baseline")
        self.assertEqual(self.app.state.last_run_results[1]["strategy_id"], "us_quality_focus")
        self.assertEqual(len(persisted_history), 2)

    @patch("stock_quantification.web.run_market")
    def test_strategy_run_assigns_unique_instance_ids_for_identical_submissions(self, mock_run_market) -> None:
        identical_result = {
            "market": "US",
            "trade_date": "2026-04-19",
            "strategy_id": "us_quality_focus",
            "signals": [{"instrument_id": "US.MSFT", "score": "0.9", "reason": "same"}],
            "trade_suggestions": [{"instrument_id": "US.MSFT", "side": "BUY", "qty": 5, "rationale": "same"}],
            "review": {"verdict": "REVIEW", "comments": ["same"]},
            "paper_trade_records": [],
        }
        mock_run_market.side_effect = [dict(identical_result), dict(identical_result)]

        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ops_store", return_value=web_module.ProjectOpsStore(artifact_root)):
                    with patch.object(self.app, "_ensure_job_worker_running"), patch.object(self.app._job_worker_wakeup_event, "set"):
                        self.app.handle_run(
                            {
                                "market": ["US"],
                                "runtime_mode": ["PAPER"],
                                "execution_mode": ["ADVISORY"],
                                "cash": ["100000"],
                                "top_n": ["2"],
                                "detail_limit": ["10"],
                                "history_limit": ["90"],
                                "beta_window": ["20"],
                                "forward_days": ["0"],
                                "selected_strategy_us": ["us_quality_focus"],
                            }
                        )
                        self.app._drain_job_queue_once()
                        self.app.handle_run(
                            {
                                "market": ["US"],
                                "runtime_mode": ["PAPER"],
                                "execution_mode": ["ADVISORY"],
                                "cash": ["100000"],
                                "top_n": ["2"],
                                "detail_limit": ["10"],
                                "history_limit": ["90"],
                                "beta_window": ["20"],
                                "forward_days": ["0"],
                                "selected_strategy_us": ["us_quality_focus"],
                            }
                        )
                        self.app._drain_job_queue_once()

        first_run, second_run = self.app.state.last_run_results
        self.assertNotEqual(first_run["run_instance_id"], second_run["run_instance_id"])
        self.assertNotEqual(self.app._run_result_ref(first_run), self.app._run_result_ref(second_run))

    @patch("stock_quantification.web.run_market")
    def test_run_paper_automation_cycle_executes_current_strategies_once_per_trade_date(self, mock_run_market) -> None:
        mock_run_market.side_effect = [
            {
                "market": "CN",
                "trade_date": "2026-05-04",
                "strategy_id": "cn_baseline",
                "paper_account": {"account_id": "web-paper-cn", "market": "CN"},
                "paper_trade_records": [{"instrument_id": "CN.600000"}],
            },
            {
                "market": "US",
                "trade_date": "2026-05-04",
                "strategy_id": "us_baseline",
                "paper_account": {"account_id": "web-paper-us", "market": "US"},
                "paper_trade_records": [{"instrument_id": "US.AAPL"}],
            },
        ]
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/strategy_state.json",
                {
                    "markets": {
                        "CN": {
                            "champion_preset_id": "cn_baseline",
                            "challenger_preset_id": None,
                            "current_execution_preset_id": "cn_baseline",
                        },
                        "US": {
                            "champion_preset_id": "us_baseline",
                            "challenger_preset_id": None,
                            "current_execution_preset_id": "us_baseline",
                        },
                    }
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_effective_trade_date_for_market", return_value=datetime.fromisoformat("2026-05-04T00:00:00").date()):
                    self.app._run_paper_automation_cycle(now=datetime.fromisoformat("2026-05-04T09:30:00"))
                    self.app._run_paper_automation_cycle(now=datetime.fromisoformat("2026-05-04T15:30:00"))
                    automation_state = web_module.read_json_artifact(artifact_root, "web/paper_automation_state.json")

        self.assertEqual(mock_run_market.call_count, 2)
        self.assertEqual(automation_state["accounts"]["web-paper-cn"]["last_trade_date"], "2026-05-04")
        self.assertEqual(automation_state["accounts"]["web-paper-us"]["last_trade_date"], "2026-05-04")

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_local_paper_reset_redirects_and_flashes(self, mock_ledger_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.reset_account.return_value = True
        response = self.app.handle_local_paper_reset(
            {
                "view": ["paper"],
                "subview": ["main"],
                "account_id": ["web-paper-us"],
                "paper_account_id": ["web-paper-us"],
                "paper_start_date": ["2026-04-01"],
                "paper_end_date": ["2026-04-30"],
            }
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=paper&subview=main&paper_account_id=web-paper-us&paper_start_date=2026-04-01&paper_end_date=2026-04-30")
        self.assertIn("已重置", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "paper")

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_local_paper_reset_missing_account_keeps_context(self, mock_ledger_cls) -> None:
        response = self.app.handle_local_paper_reset(
            {
                "view": ["paper"],
                "subview": ["main"],
                "account_id": [""],
                "paper_account_id": ["web-paper-us"],
                "paper_start_date": ["2026-04-01"],
                "paper_end_date": ["2026-04-30"],
            }
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=paper&subview=main&paper_account_id=web-paper-us&paper_start_date=2026-04-01&paper_end_date=2026-04-30")
        self.assertIn("缺少账户 ID", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "paper")

    def test_health_and_ready_endpoints_return_json(self) -> None:
        health = self.app.dispatch("GET", "/healthz", {}, {})
        ready = self.app.dispatch("GET", "/readyz", {}, {})
        self.assertEqual(health.status, 200)
        self.assertEqual(ready.status, 200)
        self.assertIn('"status"', health.body.decode("utf-8"))
        self.assertIn('"components"', ready.body.decode("utf-8"))

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_disables_cache(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({})
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}, {"symbol": "MSFT", "name": "Microsoft"}])
    def test_symbol_search_api_filters_matches(self, _mock_symbol_catalog) -> None:
        response = self.app.render_symbol_search_api({"market": ["US"], "q": ["app"], "limit": ["20"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('"AAPL"', body)
        self.assertNotIn('"MSFT"', body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_dispatch_page_routes_smoke(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        routes = ["/", "/healthz", "/readyz", "/api/project/status"]
        for route in routes:
            response = self.app.dispatch("GET", route, {}, {})
            self.assertIn(response.status, {200}, route)

    def test_static_asset_serves_css_and_blocks_traversal(self) -> None:
        response = self.app.serve_static("/static/styles.css")
        self.assertEqual(response.status, 200)
        self.assertIn("text/css", response.content_type)
        blocked = self.app.serve_static("/static/../README.md")
        self.assertEqual(blocked.status, 403)

    def test_artifact_route_handles_missing_and_unknown_files(self) -> None:
        missing = self.app.serve_artifact({})
        self.assertEqual(missing.status, 400)
        unknown = self.app.serve_artifact({"path": ["web/does-not-exist.json"]})
        self.assertEqual(unknown.status, 404)

    def test_run_submission_enqueues_when_another_job_exists(self) -> None:
        response = self.app.handle_run(
            {
                "view": ["run"],
                "subview": ["create"],
                "market": ["US"],
                "runtime_mode": ["LIVE"],
                "execution_mode": ["AUTO"],
                "broker": ["LOCAL_PAPER"],
                "route_orders": ["on"],
                "broker_account_id": ["web-paper-us"],
                "cash": ["100000"],
                "top_n": ["2"],
                "detail_limit": ["10"],
                "history_limit": ["90"],
                "beta_window": ["20"],
                "forward_days": ["0"],
                "symbols_us": ["AAPL"],
            }
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=run&subview=create")
        self.assertIn("已加入队列", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "run")

    def test_handle_run_invalid_form_value_redirects_with_flash(self) -> None:
        response = self.app.handle_run({"market": ["US"], "cash": ["abc"]})
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=run&subview=create")
        self.assertIn("策略运行参数错误", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "run")
        self.assertFalse(self.ops_store.begin_job.called)

    def test_handle_run_rejects_invalid_selected_strategy_before_job_start(self) -> None:
        response = self.app.handle_run(
            {
                "market": ["US"],
                "runtime_mode": ["PAPER"],
                "execution_mode": ["ADVISORY"],
                "cash": ["100000"],
                "detail_limit": ["10"],
                "history_limit": ["20"],
                "beta_window": ["20"],
                "top_n": ["2"],
                "forward_days": ["0"],
                "selected_strategy_us": ["not_a_real_preset"],
            }
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=run&subview=create")
        self.assertIn("策略运行参数错误", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "run")
        self.assertFalse(self.ops_store.begin_job.called)

    def test_factor_backtest_invalid_form_value_redirects_with_flash(self) -> None:
        response = self.app.handle_factor_backtest(
            {
                "factor_market": ["CN"],
                "factor": ["rel_ret_20"],
                "factor_start_date": ["bad-date"],
                "factor_end_date": ["2026-03-31"],
            }
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=optimize&subview=create")
        self.assertIn("策略实验参数错误", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "optimize")
        self.assertFalse(self.ops_store.begin_job.called)

    def test_factor_backtest_submission_stays_on_optimize_create_page(self) -> None:
        response = self.app.handle_factor_backtest(
            {
                "view": ["optimize"],
                "subview": ["create"],
                "factor_market": ["CN"],
                "factor": ["rel_ret_20"],
                "factor_start_date": ["2026-01-02"],
                "factor_end_date": ["2026-03-31"],
                "factor_holding_sessions": ["5"],
                "factor_detail_limit": ["50"],
                "factor_history_limit": ["200"],
                "factor_top_n": ["10"],
                "factor_initial_cash": ["100000"],
            }
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=optimize&subview=create")
        self.assertIn("已加入队列", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "optimize")

    def test_factor_backtest_submission_persists_auto_iteration_controls(self) -> None:
        response = self.app.handle_factor_backtest(
            {
                "view": ["optimize"],
                "subview": ["create"],
                "factor_market": ["CN"],
                "factor": ["rel_ret_20", "trend"],
                "factor_start_date": ["2026-01-02"],
                "factor_end_date": ["2026-03-31"],
                "factor_holding_sessions": ["5"],
                "factor_detail_limit": ["50"],
                "factor_history_limit": ["200"],
                "factor_top_n": ["10"],
                "factor_initial_cash": ["100000"],
                "factor_auto_iterate": ["on"],
                "factor_max_generations": ["4"],
            }
        )
        self.assertEqual(response.status, 303)
        begin_args, begin_kwargs = self.ops_store.begin_job.call_args
        self.assertEqual(begin_args[0], "factor_backtest")
        self.assertTrue(begin_kwargs["payload"]["auto_iterate"])
        self.assertEqual(begin_kwargs["payload"]["generation"], 1)
        self.assertEqual(begin_kwargs["payload"]["max_generations"], 4)
        self.assertTrue(begin_kwargs["metadata"]["auto_iterate"])
        self.assertEqual(begin_kwargs["metadata"]["generation"], 1)

    def test_factor_backtest_continue_requeues_checkpointed_job(self) -> None:
        self.ops_store.sqlite.get_job.return_value = {
            "job_id": "factor-job-1",
            "kind": "factor_backtest",
            "status": "FAILED",
            "payload": {
                "market": "US",
                "selected_factors": ["rel_ret_20", "trend"],
                "start_date": "2025-05-10",
                "end_date": "2026-05-10",
                "holding_sessions": 5,
                "detail_limit": 50,
                "history_limit": 200,
                "top_n": 10,
                "initial_cash": "100000",
                "factor_tilts": {"rel_ret_20": "1.0", "trend": "1.0"},
                "checkpoint_key": "ckpt-us-1",
            },
            "metadata": {"market": "US", "factors": ["rel_ret_20", "trend"]},
        }
        self.ops_store.sqlite.get_kv.return_value = {"processed_dates": 17}

        response = self.app.dispatch(
            "POST",
            "/factor-backtest/continue",
            {},
            {"view": ["optimize"], "subview": ["history"], "job_id": ["factor-job-1"]},
        )

        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=optimize&subview=history")
        self.ops_store.begin_job.assert_called_once()
        begin_args, begin_kwargs = self.ops_store.begin_job.call_args
        self.assertEqual(begin_args[0], "factor_backtest")
        self.assertEqual(begin_kwargs["payload"]["checkpoint_key"], "ckpt-us-1")
        self.assertEqual(begin_kwargs["payload"]["market"], "US")
        self.assertEqual(begin_kwargs["metadata"]["resume_processed_dates"], 17)
        self.assertIn("从第 17 个样本后继续", self.app.state.flash_messages[-1]["message"])
        self.assertEqual(self.app.state.flash_messages[-1]["audience"], "optimize")

    @patch.object(DashboardApp, "_run_factor_backtest")
    def test_factor_backtest_job_success_auto_requeues_next_generation(self, mock_run_factor_backtest) -> None:
        mock_run_factor_backtest.return_value = {
            "summary": {
                "subject_id": "cn_strategy_lab:2026-01-02:2026-03-31:auto1",
                "subject_name": "CN 因子实验 / 20日相对强度、趋势强度",
                "market": "CN",
                "start_date": "2026-01-02",
                "end_date": "2026-03-31",
                "selected_factors": ["rel_ret_20", "trend"],
                "total_return": "0.0120",
                "rolling_excess_return": "-0.0310",
                "max_drawdown": "-0.0900",
                "average_excess_return": "-0.0100",
                "top_n": 10,
            },
            "attribution": {
                "scorecard": {"decision": "REVIEW", "score": "0.12", "rationale": "weak up market"},
                "alpha_mix": [{"family": "momentum", "share_of_gross": "0.6800"}],
                "regime_summary": [{"regime": "UP", "average_excess_period_return": "-0.0040"}],
            },
            "rolling_backtest": {"summary": {"risk_exit_count": 3, "trend_exit_count": 0}},
            "artifacts": {"json": "/tmp/cn_factor.json", "markdown": "/tmp/cn_factor.md"},
        }
        self.ops_store.begin_job.return_value = {"accepted": True, "job": {"job_id": "factor-job-2", "kind": "factor_backtest"}}

        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_ensure_job_worker_running"), patch.object(self.app._job_worker_wakeup_event, "set") as mock_wakeup:
                    self.app._run_factor_backtest_job(
                        "factor-job-1",
                        web_module.Market.CN,
                        ["rel_ret_20", "trend"],
                        datetime.fromisoformat("2026-01-02T00:00:00").date(),
                        datetime.fromisoformat("2026-03-31T00:00:00").date(),
                        5,
                        50,
                        200,
                        10,
                        Decimal("100000"),
                        {"rel_ret_20": Decimal("1.0"), "trend": Decimal("1.0")},
                        checkpoint_key="ckpt-cn-1",
                        evolution_context={
                            "auto_iterate": True,
                            "generation": 1,
                            "max_generations": 3,
                            "lineage_id": "lineage-cn-1",
                            "parent_job_id": None,
                            "mutation_reason": "",
                        },
                    )

        begin_args, begin_kwargs = self.ops_store.begin_job.call_args
        self.assertEqual(begin_args[0], "factor_backtest")
        self.assertEqual(begin_kwargs["payload"]["generation"], 2)
        self.assertEqual(begin_kwargs["payload"]["lineage_id"], "lineage-cn-1")
        self.assertEqual(begin_kwargs["payload"]["parent_job_id"], "factor-job-1")
        self.assertIn("mutation_reason", begin_kwargs["payload"])
        self.assertTrue(begin_kwargs["payload"]["auto_iterate"])
        self.assertIn("自动派生", self.app.state.flash_messages[-1]["message"])
        mock_wakeup.assert_called()

    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_optimize_history_view_shows_generation_and_mutation_reason(self, _mock_config) -> None:
        self.ops_store.load_state.return_value = {
            "active_job": None,
            "queued_jobs": [
                {
                    "job_id": "factor-job-2",
                    "kind": "factor_backtest",
                    "status": "QUEUED",
                    "stage": "QUEUED",
                    "detail": "已加入队列：CN 因子回测自动派生任务",
                    "metadata": {
                        "market": "CN",
                        "generation": 2,
                        "max_generations": 4,
                        "lineage_id": "lineage-cn-1",
                        "mutation_reason": "上涨状态下跑输基准，转向突破确认与回调修复。",
                    },
                    "created_at": "2026-05-13T10:00:00",
                    "progress_pct": 0,
                }
            ],
            "job_history": [],
            "audit_events": [],
            "heartbeats": {},
        }

        response = self.app.render_home({"view": ["optimize"], "subview": ["history"]})

        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Generation / 代次: 2 / 4", body)
        self.assertIn("Mutation / 派生原因: 上涨状态下跑输基准", body)

    def test_load_project_config_sanitizes_bad_persisted_values(self) -> None:
        broken_payload = {
            "run_defaults": {
                "market": "BROKEN",
                "runtime_mode": "WRONG",
                "execution_mode": "NOPE",
                "broker": "UNKNOWN",
                "cash": "oops",
                "top_n": "0",
                "detail_limit": "-2",
                "history_limit": "nan",
                "beta_window": "",
                "forward_days": "-5",
                "as_of_date": "2026/01/01",
                "route_orders": "false",
            },
            "factor_defaults": {
                "factor_market": "ALL",
                "factor_start_date": "bad",
                "factor_end_date": "also-bad",
                "factor_holding_sessions": "0",
                "factor_top_n": "99",
                "factor_detail_limit": "",
                "factor_history_limit": "oops",
                "factor_initial_cash": "bad",
            },
            "ui_defaults": {
                "paper_account_id": "",
                "paper_start_date": "2026/04/01",
                "paper_end_date": "2026/04/31",
                "paper_recent_trade_limit": "0",
            },
        }
        with patch.object(web_module, "read_json_artifact", return_value=broken_payload):
            config = self.app._load_project_config()
        self.assertEqual(config["run_defaults"]["market"], DEFAULT_PROJECT_CONFIG["run_defaults"]["market"])
        self.assertEqual(config["run_defaults"]["cash"], DEFAULT_PROJECT_CONFIG["run_defaults"]["cash"])
        self.assertFalse(config["run_defaults"]["route_orders"])
        self.assertEqual(config["factor_defaults"]["factor_market"], DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_market"])
        self.assertEqual(config["ui_defaults"]["paper_recent_trade_limit"], DEFAULT_PROJECT_CONFIG["ui_defaults"]["paper_recent_trade_limit"])

    def test_artifact_route_serves_existing_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            relative_path = "web/example.json"
            artifact_path = artifact_root / relative_path
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text('{"ok": true}', encoding="utf-8")
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                response = self.app.serve_artifact({"path": [relative_path]})
        self.assertEqual(response.status, 200)
        self.assertIn('"ok": true', response.body.decode("utf-8"))

    def test_selected_artifact_prefers_normalized_summary(self) -> None:
        artifact = web_module.ArtifactEntry(
            relative_path="2026-03-31/us_strategy_suite.json",
            display_name="us_strategy_suite.json",
            mtime=0,
            summary={
                "normalized_summary": {
                    "subject_name": "美股基线质量动量",
                    "decision": "KEEP",
                    "score": "1.2345",
                    "return": "0.1200",
                    "excess_return": "0.0500",
                    "max_drawdown": "-0.0400",
                }
            },
        )

        html = self.app._render_selected_artifact(artifact)

        self.assertIn("Normalized Summary / 统一摘要", html)
        self.assertIn("美股基线质量动量", html)
        self.assertIn("1.2345", html)
        self.assertIn("0.1200", html)

    def test_local_paper_panel_renders_latest_run_summary(self) -> None:
        self.app.state.last_run_results = [
            {
                "paper_account": {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "cash": "80000",
                    "buying_power": "80000",
                    "position_count": 1,
                    "trade_count": 2,
                    "filtered_trade_count": 1,
                    "latest_nav": "100500.0000",
                    "cumulative_return": "0.0050",
                    "positions": [{"instrument_id": "US.AAPL", "qty": 10, "avg_cost": "200"}],
                    "nav_history": [{"trade_date": "2026-04-05", "nav": "100000.0000"}, {"trade_date": "2026-04-06", "nav": "100500.0000"}],
                    "recent_trades": [{"trade_date": "2026-04-06", "side": "BUY", "instrument_id": "US.AAPL", "filled_qty": 10, "estimated_price": "200", "cash_delta": "-2000"}],
                },
                "paper_trade_records": [{"instrument_id": "US.AAPL"}],
                "paper_run_summary": {
                    "strategy_id": "us_quality_momentum",
                    "trade_count": 1,
                    "as_of": "2026-04-06T16:00:00",
                    "position_count": 1,
                },
                "paper_paths": {"run_json": "artifacts/local_paper/web-paper-us/runs/demo.json"},
            }
        ]
        self.app.state.last_local_paper_account = self.app.state.last_run_results[-1]["paper_account"]
        with patch.object(self.app, "_enrich_local_paper_overview", side_effect=lambda overview: overview):
            with patch.object(web_module, "LocalPaperLedger") as mock_ledger_cls:
                ledger = mock_ledger_cls.return_value
                ledger.account_overview.return_value = self.app.state.last_local_paper_account
                ledger.list_accounts.return_value = ["web-paper-us"]
                html = self.app._render_local_paper_panel({})

        self.assertIn("Recent Run Context / 最近运行上下文", html)
        self.assertIn("us_quality_momentum", html)
        self.assertIn("2026-04-06T16:00:00", html)

    @patch.object(web_module, "build_market_snapshot")
    def test_enrich_local_paper_overview_uses_ledger_prices_without_live_fetch(self, mock_snapshot) -> None:
        overview = {
            "account_id": "web-paper-us",
            "market": "US",
            "cash": "98000",
            "latest_nav": "100000",
            "positions": [{"instrument_id": "US.AAPL", "qty": "10", "avg_cost": "180"}],
            "filtered_trades": [
                {
                    "trade_date": "2026-04-06",
                    "side": "BUY",
                    "instrument_id": "US.AAPL",
                    "estimated_price": "200",
                    "cash_delta": "-2000",
                    "name": "Apple Inc.",
                }
            ],
            "nav_history": [{"trade_date": "2026-04-06", "nav": "100000"}],
        }

        enriched = self.app._enrich_local_paper_overview(overview)

        mock_snapshot.assert_not_called()
        self.assertEqual(enriched["mark_source"], "ledger")
        self.assertEqual(enriched["position_rows"][0]["current_price"], "200.0000")
        self.assertEqual(enriched["position_rows"][0]["name"], "Apple Inc.")
        self.assertEqual(enriched["position_rows"][0]["sector"], "UNKNOWN")

    def test_local_paper_panel_prefers_matching_account_run_summary(self) -> None:
        self.app.state.last_run_results = [
            {
                "paper_account": {
                    "account_id": "web-paper-cn",
                    "market": "CN",
                    "cash": "70000",
                    "buying_power": "65000",
                    "position_count": 2,
                    "trade_count": 3,
                    "filtered_trade_count": 2,
                    "latest_nav": "102000.0000",
                    "cumulative_return": "0.0200",
                    "positions": [],
                    "nav_history": [],
                    "recent_trades": [],
                },
                "paper_trade_records": [{"instrument_id": "CN.600519"}],
                "paper_run_summary": {
                    "account_id": "web-paper-cn",
                    "strategy_id": "cn_momentum_core",
                    "trade_count": 1,
                    "as_of": "2026-04-06T14:00:00",
                    "position_count": 2,
                },
                "paper_paths": {"run_json": "artifacts/local_paper/web-paper-cn/runs/cn-demo.json"},
            },
            {
                "paper_account": {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "cash": "80000",
                    "buying_power": "80000",
                    "position_count": 1,
                    "trade_count": 2,
                    "filtered_trade_count": 1,
                    "latest_nav": "100500.0000",
                    "cumulative_return": "0.0050",
                    "positions": [],
                    "nav_history": [],
                    "recent_trades": [],
                },
                "paper_trade_records": [{"instrument_id": "US.AAPL"}],
                "paper_run_summary": {
                    "account_id": "web-paper-us",
                    "strategy_id": "us_quality_momentum",
                    "trade_count": 1,
                    "as_of": "2026-04-06T16:00:00",
                    "position_count": 1,
                },
                "paper_paths": {"run_json": "artifacts/local_paper/web-paper-us/runs/us-demo.json"},
            },
        ]
        with patch.object(self.app, "_enrich_local_paper_overview", side_effect=lambda overview: overview):
            with patch.object(web_module, "LocalPaperLedger") as mock_ledger_cls:
                ledger = mock_ledger_cls.return_value
                ledger.account_overview.return_value = {
                    "account_id": "web-paper-cn",
                    "market": "CN",
                    "cash": "70000",
                    "buying_power": "65000",
                    "position_count": 2,
                    "trade_count": 3,
                    "filtered_trade_count": 2,
                    "latest_nav": "102000.0000",
                    "cumulative_return": "0.0200",
                    "positions": [],
                    "nav_history": [],
                    "recent_trades": [],
                }
                ledger.list_accounts.return_value = ["web-paper-cn", "web-paper-us"]
                html = self.app._render_local_paper_panel({"paper_account_id": ["web-paper-cn"]})

        self.assertIn("cn_momentum_core", html)
        self.assertIn("2026-04-06T14:00:00", html)
        self.assertNotIn("us_quality_momentum", html)

    def test_local_paper_panel_falls_back_to_indexed_run_summary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "local_paper_run:US:web-paper-us:2026-04-18T10:00:00",
                            "artifact_kind": "local_paper_run",
                            "market": "US",
                            "sort_date": "2026-04-18T10:00:00",
                            "summary": {
                                "subject_name": "web-paper-us / us_quality_momentum",
                                "decision": "RECORDED",
                                "score": 2,
                                "rationale": "2 trades routed into local paper ledger",
                            },
                            "paper_run_summary": {
                                "strategy_id": "us_quality_momentum",
                                "trade_count": 2,
                                "as_of": "2026-04-18T10:00:00",
                                "position_count": 4,
                            },
                            "artifacts": {"json": "local_paper/web-paper-us/runs/demo.json"},
                        }
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_enrich_local_paper_overview", side_effect=lambda overview: overview):
                    with patch.object(web_module, "LocalPaperLedger") as mock_ledger_cls:
                        ledger = mock_ledger_cls.return_value
                        ledger.account_overview.return_value = {
                            "account_id": "web-paper-us",
                            "market": "US",
                            "cash": "80000",
                            "buying_power": "80000",
                            "position_count": 1,
                            "trade_count": 2,
                            "filtered_trade_count": 2,
                            "latest_nav": "100500.0000",
                            "cumulative_return": "0.0050",
                            "positions": [],
                            "recent_trades": [],
                            "nav_history": [],
                        }
                        ledger.list_accounts.return_value = ["web-paper-us"]
                        html = self.app._render_local_paper_panel({})

        self.assertIn("Recent Run Context / 最近运行上下文", html)
        self.assertIn("us_quality_momentum", html)
        self.assertIn("2026-04-18T10:00:00", html)

    def test_local_paper_panel_indexed_fallback_prefers_matching_account(self) -> None:
        with TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir)
            write_json_artifact(
                artifact_root,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "local_paper_run:US:web-paper-us:2026-04-18T10:00:00",
                            "artifact_kind": "local_paper_run",
                            "market": "US",
                            "sort_date": "2026-04-18T10:00:00",
                            "summary": {
                                "subject_name": "web-paper-us / us_quality_momentum",
                                "decision": "RECORDED",
                                "score": 2,
                                "rationale": "2 trades routed into local paper ledger",
                            },
                            "paper_run_summary": {
                                "account_id": "web-paper-us",
                                "strategy_id": "us_quality_momentum",
                                "trade_count": 2,
                                "as_of": "2026-04-18T10:00:00",
                                "position_count": 4,
                            },
                            "artifacts": {"json": "local_paper/web-paper-us/runs/us-demo.json"},
                        },
                        {
                            "result_id": "local_paper_run:CN:web-paper-cn:2026-04-18T09:00:00",
                            "artifact_kind": "local_paper_run",
                            "market": "CN",
                            "sort_date": "2026-04-18T09:00:00",
                            "summary": {
                                "subject_name": "web-paper-cn / cn_momentum_core",
                                "decision": "RECORDED",
                                "score": 1,
                                "rationale": "1 trade routed into local paper ledger",
                            },
                            "paper_run_summary": {
                                "account_id": "web-paper-cn",
                                "strategy_id": "cn_momentum_core",
                                "trade_count": 1,
                                "as_of": "2026-04-18T09:00:00",
                                "position_count": 3,
                            },
                            "artifacts": {"json": "local_paper/web-paper-cn/runs/cn-demo.json"},
                        },
                    ]
                },
            )
            with patch.object(web_module, "ARTIFACT_ROOT", artifact_root):
                with patch.object(self.app, "_enrich_local_paper_overview", side_effect=lambda overview: overview):
                    with patch.object(web_module, "LocalPaperLedger") as mock_ledger_cls:
                        ledger = mock_ledger_cls.return_value
                        ledger.account_overview.return_value = {
                            "account_id": "web-paper-cn",
                            "market": "CN",
                            "cash": "70000",
                            "buying_power": "65000",
                            "position_count": 3,
                            "trade_count": 4,
                            "filtered_trade_count": 4,
                            "latest_nav": "102000.0000",
                            "cumulative_return": "0.0200",
                            "positions": [],
                            "recent_trades": [],
                            "nav_history": [],
                        }
                        ledger.list_accounts.return_value = ["web-paper-cn", "web-paper-us"]
                        html = self.app._render_local_paper_panel({"paper_account_id": ["web-paper-cn"]})

        self.assertIn("cn_momentum_core", html)
        self.assertIn("2026-04-18T09:00:00", html)
        self.assertNotIn("us_quality_momentum", html)
