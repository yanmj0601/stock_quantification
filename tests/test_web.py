from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from unittest.mock import patch
from unittest import TestCase

from stock_quantification.artifacts import write_json_artifact
from stock_quantification import web as web_module
from stock_quantification.web import DashboardApp, DEFAULT_PROJECT_CONFIG


class WebTests(TestCase):
    def setUp(self) -> None:
        self.app = DashboardApp()
        self.ops_store = Mock()
        self.ops_store.begin_job.return_value = {"accepted": True, "job": {"job_id": "job-1", "kind": "test"}}
        self.ops_store.finish_job.return_value = {}
        self.ops_store.append_event.return_value = {}
        self.ops_store.heartbeat.return_value = {}
        self.ops_store.load_state.return_value = {"active_job": None, "job_history": [], "audit_events": [], "heartbeats": {}}
        self.app._ops_store = Mock(return_value=self.ops_store)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_renders_sidebar_navigation(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Overview / 总览", body)
        self.assertIn("Research Workbench / 研究工作台", body)
        self.assertIn("Research Results / 研究结果", body)
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertNotIn("模块导航", body)

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
        self.assertIn("Research Results / 研究结果", body)
        self.assertIn("/?view=results&artifact=2026-03-31/us_strategy_suite.json", body)
        self.assertNotIn("双市场量化项目工作台", body)

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
        response = self.app.render_home({"view": ["paper"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertIn('action="/?view=paper"', body)
        self.assertIn('name="view" value="paper"', body)

    def test_home_page_falls_back_to_overview_for_invalid_view(self) -> None:
        response = self.app.render_home({"view": ["not-a-real-view"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("双市场量化项目工作台", body)
        self.assertIn('class="module-link module-link--active" href="/"', body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_supports_workbench_view(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({"view": ["workbench"]})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("研究工作台", body)
        self.assertNotIn("双市场量化项目工作台", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_renders_dashboard(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("双市场量化项目工作台", body)
        self.assertIn("Project Status", body)
        self.assertIn("Overview / 总览", body)
        self.assertIn("Research Workbench / 研究工作台", body)
        self.assertIn("Research Results / 研究结果", body)
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertNotIn("模块导航", body)
        self.assertIn("研究结果中心", body)
        self.assertIn("最近结果", body)
        self.assertIn("策略实验台", body)
        self.assertIn("模拟盘账户", body)
        self.assertIn("推荐账户名", body)
        self.assertIn("web-paper-us", body)
        self.assertIn("任务进度", body)
        self.assertIn("data-async-job-form=\"strategy_run\"", body)
        self.assertIn("留空表示全市场", body)

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
                response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Research Results / 研究结果中心", body)
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
                response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Research Results / 研究结果中心", body)
        self.assertIn("Runtime Results / 运行结果", body)
        self.assertIn("美股基线质量动量", body)
        self.assertIn("web-paper-us / us_quality_momentum", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_renders_strategy_lab_result_sections(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        self.app.state.last_factor_backtest_result = {
            "summary": {
                "market": "US",
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
            "signal_validation": {"daily": [{"trade_date": "2026-03-12", "equal_weight_return": "0.0120", "excess_return": "0.0050", "win_rate": "0.6000"}]},
            "rolling_backtest": {"daily": [{"trade_date": "2026-03-12", "end_of_day_nav": "100000"}, {"trade_date": "2026-03-13", "end_of_day_nav": "101200", "period_return": "0.0120", "cumulative_portfolio_return": "0.0120", "turnover": "0.0800", "total_fees": "12.5"}]},
            "attribution": {
                "alpha_mix": [{"family": "momentum", "net_weight": "0.4200", "gross_weight": "0.4200", "share_of_gross": "0.5300"}],
                "regime_summary": [{"regime": "UP", "observations": 8, "average_period_return": "0.0050", "average_excess_period_return": "0.0020", "win_rate": "0.6250"}],
                "scorecard": {"decision": "KEEP", "score": "0.8800", "rationale": "net=0.08", "strengths": ["净收益为正"], "warnings": ["换手略高"]},
                "iteration_notes": [{"level": "good", "title": "继续跟踪", "detail": "保持当前结构，下一轮微调动量强度。"}],
            },
            "artifacts": {"json": "/tmp/us_factor.json", "markdown": "/tmp/us_factor.md"},
        }
        response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Factor Setup / 因子配置", body)
        self.assertIn("Regime Attribution / 市场状态归因", body)
        self.assertIn("Alpha Mix / 因子家族暴露", body)
        self.assertIn("Next Iteration / 下一轮迭代建议", body)
        self.assertIn("当前已选因子", body)

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
                "total_return": "0.0432",
            },
            "attribution": {"scorecard": {"decision": "REVIEW"}},
            "artifacts": {"json": "/tmp/cn_factor.json", "markdown": "/tmp/cn_factor.md"},
        }
        with patch.object(self.app, "_start_background_task", side_effect=lambda target, *args: target(*args)):
            response = self.app.handle_factor_backtest(
                {
                    "view": ["workbench"],
                    "factor_market": ["CN"],
                    "factor": ["rel_ret_20", "rel_ret_60"],
                    "factor_start_date": ["2026-01-02"],
                    "factor_end_date": ["2026-03-31"],
                    "factor_holding_sessions": ["5"],
                    "factor_detail_limit": ["8"],
                    "factor_history_limit": ["60"],
                    "factor_top_n": ["4"],
                    "factor_initial_cash": ["100000"],
                    "factor_turnover_cap": ["0.18"],
                    "factor_rebalance_buffer": ["0.05"],
                    "factor_tilt_rel_ret_20": ["1.2"],
                    "factor_tilt_rel_ret_60": ["0.8"],
                }
            )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=workbench")
        self.assertEqual(self.app.state.last_factor_backtest_result["summary"]["market"], "CN")

    @patch.object(DashboardApp, "_run_factor_backtest")
    def test_factor_backtest_falls_back_to_hidden_factor_payload(self, mock_run_factor_backtest) -> None:
        mock_run_factor_backtest.return_value = {
            "summary": {"market": "CN", "selected_factors": ["rel_ret_20"], "total_return": "0.0100"},
            "attribution": {"scorecard": {"decision": "REVIEW"}},
            "artifacts": {"json": "/tmp/cn_factor.json", "markdown": "/tmp/cn_factor.md"},
        }
        with patch.object(self.app, "_start_background_task", side_effect=lambda target, *args: target(*args)):
            response = self.app.handle_factor_backtest(
                {
                    "factor_market": ["CN"],
                    "factor_selection_payload": ["rel_ret_20,trend"],
                    "factor_start_date": ["2026-01-02"],
                    "factor_end_date": ["2026-03-31"],
                    "factor_holding_sessions": ["5"],
                    "factor_detail_limit": ["8"],
                    "factor_history_limit": ["60"],
                    "factor_top_n": ["4"],
                    "factor_initial_cash": ["100000"],
                    "factor_turnover_cap": ["0.18"],
                    "factor_rebalance_buffer": ["0.05"],
                }
            )
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
        with patch.object(self.app, "_start_background_task", side_effect=lambda target, *args: target(*args)):
            response = self.app.handle_factor_backtest(
                {
                    "factor_market": ["CN"],
                    "factor_start_date": ["2026-01-02"],
                    "factor_end_date": ["2026-03-31"],
                    "factor_holding_sessions": ["5"],
                    "factor_detail_limit": ["8"],
                    "factor_history_limit": ["60"],
                    "factor_top_n": ["4"],
                    "factor_initial_cash": ["100000"],
                    "factor_turnover_cap": ["0.18"],
                    "factor_rebalance_buffer": ["0.05"],
                    "factor_tilt_rel_ret_20": ["1.0"],
                    "factor_tilt_rel_ret_60": ["1.0"],
                    "factor_tilt_trend": ["1.0"],
                    "factor_tilt_quality": ["1.0"],
                }
            )
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
        with patch.object(self.app, "_start_background_task", side_effect=lambda target, *args: target(*args)):
            response = self.app.handle_run(
                {
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
        self.assertEqual(self.app.state.last_local_paper_account["account_id"], "web-paper-us")

    @patch("stock_quantification.web.LocalPaperLedger")
    def test_local_paper_reset_redirects_and_flashes(self, mock_ledger_cls) -> None:
        ledger = mock_ledger_cls.return_value
        ledger.reset_account.return_value = True
        response = self.app.handle_local_paper_reset({"view": ["paper"], "account_id": ["web-paper-us"]})
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=paper")
        self.assertIn("已重置", self.app.state.flash_messages[-1])

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_project_config_page_renders(self, _mock_config, _mock_symbol_catalog) -> None:
        response = self.app.render_project_config()
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("项目配置页", body)
        self.assertIn("保存项目配置", body)
        self.assertIn("推荐账户名", body)
        self.assertIn("立即搜索", body)
        self.assertIn("Turnover Cap / 换手上限", body)

    @patch.object(DashboardApp, "_load_task_logs", return_value=[{"created_at": "2026-04-06T09:30:00", "category": "runtime", "action": "strategy_run", "status": "SUCCESS", "detail": "ok", "metadata": {"market": "US"}}])
    def test_task_logs_page_renders(self, _mock_logs) -> None:
        response = self.app.render_task_logs()
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("任务日志页", body)
        self.assertIn("strategy_run", body)

    @patch.object(DashboardApp, "_build_system_status", return_value={"overall_status": "WARN", "artifact_count": 5, "task_log_count": 3, "paper_account_count": 1, "broker_credentials_ready": False, "latest_review": "WARN", "active_job": None, "job_history": [], "audit_events": [], "components": [{"name": "artifact_storage", "status": "UP", "detail": "ok"}]})
    def test_ops_center_renders(self, _mock_status) -> None:
        response = self.app.render_ops_center()
        body = response.body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("后台运维中心", body)
        self.assertIn("artifact_storage", body)

    def test_release_active_job_redirects_and_flashes(self) -> None:
        self.ops_store.load_state.return_value = {"active_job": {"job_id": "job-1", "kind": "factor_backtest"}, "job_history": [], "audit_events": [], "heartbeats": {}}
        self.ops_store.release_active_job.return_value = {"active_job": None}
        response = self.app.handle_release_active_job({"action": ["release_active_job"]})
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/project/ops")
        self.assertIn("已释放任务", self.app.state.flash_messages[-1])

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
        routes = ["/", "/project/config", "/project/logs", "/project/ops", "/healthz", "/readyz", "/api/project/status"]
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

    def test_run_guard_blocks_when_active_job_exists(self) -> None:
        ops_store = Mock()
        ops_store.begin_job.return_value = {"accepted": False, "active_job": {"kind": "factor_backtest"}}
        with patch.object(self.app, "_ops_store", return_value=ops_store):
            response = self.app.handle_run(
                {
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
        self.assertEqual(response.headers["Location"], "/project/ops")

    @patch.object(DashboardApp, "_save_project_config")
    @patch.object(DashboardApp, "_load_project_config", return_value=DEFAULT_PROJECT_CONFIG)
    def test_project_config_save_redirects(self, _mock_config, mock_save) -> None:
        response = self.app.handle_project_config(
            {
                "market": ["US"],
                "runtime_mode": ["LIVE"],
                "execution_mode": ["AUTO"],
                "broker": ["LOCAL_PAPER"],
                "cash": ["200000"],
                "broker_account_id": ["paper-us"],
                "top_n": ["8"],
                "detail_limit": ["16"],
                "history_limit": ["120"],
                "beta_window": ["30"],
                "forward_days": ["5"],
                "as_of_date": [""],
                "symbols_cn": [""],
                "symbols_us": ["AAPL,MSFT,NVDA"],
                "route_orders": ["on"],
                "factor_market": ["US"],
                "factor_start_date": ["2026-01-01"],
                "factor_end_date": ["2026-03-31"],
                "factor_holding_sessions": ["5"],
                "factor_top_n": ["6"],
                "factor_detail_limit": ["10"],
                "factor_history_limit": ["90"],
                "factor_initial_cash": ["150000"],
                "factor_turnover_cap": ["0.16"],
                "factor_rebalance_buffer": ["0.06"],
                "paper_account_id": ["paper-us"],
                "paper_start_date": ["2026-04-01"],
                "paper_end_date": ["2026-04-30"],
                "paper_recent_trade_limit": ["20"],
            }
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/project/config")
        self.assertTrue(mock_save.called)

    def test_handle_run_invalid_form_value_redirects_with_flash(self) -> None:
        response = self.app.handle_run({"market": ["US"], "cash": ["abc"]})
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/?view=overview")
        self.assertIn("策略运行参数错误", self.app.state.flash_messages[-1])
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
        self.assertEqual(response.headers["Location"], "/?view=workbench")
        self.assertIn("策略实验参数错误", self.app.state.flash_messages[-1])
        self.assertFalse(self.ops_store.begin_job.called)

    @patch.object(DashboardApp, "_save_project_config")
    def test_project_config_invalid_input_does_not_save(self, mock_save) -> None:
        response = self.app.handle_project_config(
            {
                "market": ["US"],
                "runtime_mode": ["LIVE"],
                "execution_mode": ["AUTO"],
                "broker": ["LOCAL_PAPER"],
                "cash": ["0"],
                "broker_account_id": ["paper-us"],
                "top_n": ["8"],
                "detail_limit": ["16"],
                "history_limit": ["120"],
                "beta_window": ["30"],
                "forward_days": ["5"],
                "as_of_date": [""],
                "symbols_cn": [""],
                "symbols_us": ["AAPL,MSFT,NVDA"],
                "route_orders": ["on"],
                "factor_market": ["US"],
                "factor_start_date": ["2026-04-01"],
                "factor_end_date": ["2026-03-31"],
                "factor_holding_sessions": ["5"],
                "factor_top_n": ["6"],
                "factor_detail_limit": ["10"],
                "factor_history_limit": ["90"],
                "factor_initial_cash": ["150000"],
                "factor_turnover_cap": ["0.16"],
                "factor_rebalance_buffer": ["0.06"],
                "paper_account_id": ["paper-us"],
                "paper_start_date": ["2026-04-01"],
                "paper_end_date": ["2026-04-30"],
                "paper_recent_trade_limit": ["20"],
            }
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/project/config")
        self.assertIn("项目配置保存失败", self.app.state.flash_messages[-1])
        self.assertFalse(mock_save.called)

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
                "route_orders": "yes",
            },
            "factor_defaults": {
                "factor_market": "ALL",
                "factor_start_date": "bad",
                "factor_end_date": "also-bad",
                "factor_holding_sessions": "0",
                "factor_top_n": "-1",
                "factor_detail_limit": "",
                "factor_history_limit": "oops",
                "factor_initial_cash": "bad",
                "factor_turnover_cap": "-1",
                "factor_rebalance_buffer": "-1",
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

        self.assertIn("Latest Paper Run / 最近模拟盘运行", html)
        self.assertIn("us_quality_momentum", html)
        self.assertIn("2026-04-06T16:00:00", html)

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

        self.assertIn("Latest Paper Run / 最近模拟盘运行", html)
        self.assertIn("us_quality_momentum", html)
        self.assertIn("2026-04-18T10:00:00", html)
