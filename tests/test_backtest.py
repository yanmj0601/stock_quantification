from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from stock_quantification.backtest import (
    _actual_sessions,
    _mark_nav,
    _benchmark_window,
    _instrument_window,
    _trim_exit_events,
    build_forward_return_report,
    build_rolling_strategy_backtest_report,
    serialize_backtest_report,
    serialize_rolling_backtest_report,
)
from stock_quantification.backtest_dataset import MarketDataset, build_market_dataset
from stock_quantification.broker_ledger import BrokerLedger
from stock_quantification.engine import InMemoryCalendarProvider, InMemoryMarketDataProvider, InMemoryUniverseProvider
from stock_quantification.agents import ResearchAgent
from stock_quantification.models import ResearchReport, ReviewReport, ReviewVerdict, SignalSnapshot, StrategyProposal
from stock_quantification.research_data import ResearchDataBundle, build_default_bundle
from stock_quantification.real_data import MarketSnapshot
from stock_quantification.runtime import ExecutionFill, ExecutionResult, ExecutionStatus
from stock_quantification.strategy_catalog import strategy_presets_for_market

from stock_quantification.models import AccountState, AssetType, Bar, Instrument, Market, Position, RuntimeMode


class SnapshotBuilderSpy:
    def __init__(self, snapshots: Sequence[MarketSnapshot]) -> None:
        self._snapshots = {snapshot.as_of.date(): snapshot for snapshot in snapshots}
        self.calls: List[date] = []

    def __call__(self, market, symbols, detail_limit, history_limit, as_of_date):
        del market, symbols, detail_limit, history_limit
        self.calls.append(as_of_date)
        return self._snapshots[as_of_date]


class BacktestTests(TestCase):
    def test_trim_exit_events_can_preserve_full_history(self) -> None:
        events = [
            SimpleNamespace(trade_date=f"2026-03-{day:02d}")
            for day in range(1, 15)
        ]

        self.assertEqual(len(_trim_exit_events(events, max_exit_events=12)), 12)
        self.assertEqual(len(_trim_exit_events(events, max_exit_events=None)), 14)
        self.assertEqual(_trim_exit_events(events, max_exit_events=0), [])

    def test_research_agent_is_thin_wrapper_over_strategy_runner(self) -> None:
        as_of = datetime(2026, 3, 2, 16, 0, 0)
        strategy = Mock()
        strategy.market = Market.US
        runner = Mock()
        runner.run.return_value = {
            "signals": [
                SignalSnapshot(
                    as_of=as_of,
                    strategy_id="us_quality_momentum",
                    instrument_id="US.AAPL",
                    score=Decimal("1.2"),
                    direction="LONG",
                    reason="alpha(momentum)",
                ),
                SignalSnapshot(
                    as_of=as_of,
                    strategy_id="us_quality_momentum",
                    instrument_id="US.MSFT",
                    score=Decimal("0.8"),
                    direction="LONG",
                    reason="alpha(quality)",
                ),
            ],
            "factors": [],
            "targets": [],
            "portfolio_diagnostics": {"turnover": "0.0"},
            "rankings": [{"instrument_id": "US.AAPL", "score": Decimal("1.2")}],
        }

        analysis = ResearchAgent(runner).analyze(strategy, as_of, account_states=[])

        runner.run.assert_called_once_with(strategy, as_of, account_states=[])
        self.assertEqual(analysis.research_report.candidate_instruments, ["US.AAPL", "US.MSFT"])
        self.assertEqual(analysis.signals[0].instrument_id, "US.AAPL")
        self.assertEqual(analysis.rankings[0]["instrument_id"], "US.AAPL")

    def test_backtest_ledger_and_shared_broker_ledger_compute_nav_consistently(self) -> None:
        stock = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        provider = InMemoryMarketDataProvider(
            [stock],
            {
                stock.instrument_id: [
                    Bar(stock.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
                    Bar(stock.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("105"), Decimal("105"), Decimal("105"), Decimal("105"), 100, Decimal("1050")),
                ]
            },
        )
        account_state = AccountState(
            account_id="paper-us",
            market=Market.US,
            broker_id="local-paper",
            cash=Decimal("900"),
            buying_power=Decimal("900"),
            positions={"US.AAPL": Position("US.AAPL", 10, Decimal("100"))},
        )

        nav = _mark_nav(account_state, provider, datetime(2026, 3, 3, 16, 0, 0))
        ledger = BrokerLedger()
        snapshot = ledger.nav_snapshot(
            account_state=account_state,
            as_of=datetime(2026, 3, 3, 16, 0, 0),
            trade_date="2026-03-03",
            starting_cash=Decimal("1900"),
            price_map={"US.AAPL": Decimal("105")},
        )

        self.assertEqual(nav, Decimal("1950"))
        self.assertEqual(snapshot["nav"], "1950.0000")
        self.assertEqual(snapshot["position_value"], "1050.0000")

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

    @patch("stock_quantification.backtest.fetch_us_benchmark_history")
    @patch("stock_quantification.backtest.fetch_us_daily_history")
    def test_build_forward_return_report_skips_instruments_without_eligible_bars(self, mock_fetch_history, mock_fetch_benchmark) -> None:
        mock_fetch_history.side_effect = [
            (
                Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
                [
                    Bar("US.AAPL", datetime(2026, 3, 12, 16, 0, 0), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), 100, Decimal("1000")),
                    Bar("US.AAPL", datetime(2026, 3, 20, 16, 0, 0), Decimal("109"), Decimal("111"), Decimal("108"), Decimal("110"), 100, Decimal("1000")),
                ],
            ),
            (
                Instrument("US.MSFT", Market.US, "MSFT", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
                [
                    Bar("US.MSFT", datetime(2026, 3, 21, 16, 0, 0), Decimal("190"), Decimal("191"), Decimal("189"), Decimal("190"), 100, Decimal("1000")),
                ],
            ),
        ]
        mock_fetch_benchmark.return_value = (
            Instrument("US.SPY", Market.US, "SPY", AssetType.ETF, "USD", "NYSE"),
            [
                Bar("US.SPY", datetime(2026, 3, 12, 16, 0, 0), Decimal("300"), Decimal("301"), Decimal("299"), Decimal("300"), 100, Decimal("1000")),
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
        self.assertEqual(serialized["summary"]["selected_count"], 1)
        self.assertEqual(len(serialized["rows"]), 1)
        self.assertEqual(serialized["rows"][0]["instrument_id"], "US.AAPL")

    @patch("stock_quantification.backtest._run_backtest_orchestration")
    def test_build_rolling_strategy_backtest_report(self, mock_run_backtest_orchestration) -> None:
        mock_run_backtest_orchestration.return_value = type(
            "Result",
            (),
            {
                "execution_results": [],
                "proposal": type("Proposal", (), {"research_rankings": [], "targets": []})(),
                "review": ReviewReport(verdict=ReviewVerdict.PASS, comments=[]),
            },
        )()

        stock = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        benchmark = Instrument("US.SPY", Market.US, "SPY", AssetType.ETF, "USD", "NYSE")
        bars_by_instrument = {
            stock.instrument_id: [
                Bar(stock.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
                Bar(stock.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
            ],
            benchmark.instrument_id: [
                Bar(benchmark.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
                Bar(benchmark.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("110"), Decimal("110"), Decimal("110"), Decimal("110"), 100, Decimal("1100")),
            ],
        }
        provider = InMemoryMarketDataProvider([stock, benchmark], bars_by_instrument)
        bundle = build_default_bundle(provider, Market.US, "SP500_PROXY", date(2026, 3, 2))
        snapshot_1 = MarketSnapshot(
            market=Market.US,
            as_of=datetime(2026, 3, 2, 16, 0, 0),
            data_provider=provider,
            calendar_provider=InMemoryCalendarProvider({Market.US: [datetime(2026, 3, 2, 16, 0, 0)]}),
            universe_provider=InMemoryUniverseProvider(provider),
            research_data_bundle=ResearchDataBundle(
                market_data_provider=provider,
                fundamental_provider=bundle.fundamental_provider,
                benchmark_provider=bundle.benchmark_provider,
                corporate_action_provider=bundle.corporate_action_provider,
                benchmark_ids_by_market=bundle.benchmark_ids_by_market,
            ),
            benchmark_instrument_id=benchmark.instrument_id,
        )
        snapshot_2 = MarketSnapshot(
            market=Market.US,
            as_of=datetime(2026, 3, 3, 16, 0, 0),
            data_provider=provider,
            calendar_provider=InMemoryCalendarProvider({Market.US: [datetime(2026, 3, 3, 16, 0, 0)]}),
            universe_provider=InMemoryUniverseProvider(provider),
            research_data_bundle=snapshot_1.research_data_bundle,
            benchmark_instrument_id=benchmark.instrument_id,
        )

        def fake_build_snapshot(market, symbols, detail_limit, history_limit, as_of_date):
            if as_of_date == date(2026, 3, 2):
                return snapshot_1
            return snapshot_2

        preset = next(item for item in strategy_presets_for_market(Market.US) if item.preset_id == "us_momentum_core")
        report = build_rolling_strategy_backtest_report(
            market=Market.US,
            preset=preset,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 3),
            detail_limit=2,
            history_limit=5,
            build_snapshot_fn=fake_build_snapshot,
        )

        serialized = serialize_rolling_backtest_report(report)
        self.assertEqual(serialized["summary"]["trading_days"], 2)
        self.assertEqual(serialized["summary"]["total_return"], "0.0000")
        self.assertEqual(serialized["summary"]["benchmark_total_return"], "0.1000")
        self.assertEqual(serialized["summary"]["excess_return"], "-0.1000")
        self.assertEqual(serialized["summary"]["average_turnover"], "0.0000")
        self.assertEqual(serialized["summary"]["fee_drag"], "0.0000")
        self.assertTrue(serialized["summary"]["benchmark_available"])
        self.assertEqual(serialized["daily"][0]["period_return"], "0.0000")
        self.assertEqual(serialized["daily"][0]["cumulative_portfolio_return"], "0.0000")

    def test_actual_sessions_reuses_preloaded_market_dataset(self) -> None:
        stock = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        bars_by_instrument = {
            stock.instrument_id: [
                Bar(stock.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
                Bar(stock.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), 100, Decimal("1010")),
            ]
        }
        provider = InMemoryMarketDataProvider([stock], bars_by_instrument)
        snapshot_1 = MarketSnapshot(
            market=Market.US,
            as_of=datetime(2026, 3, 2, 16, 0, 0),
            data_provider=provider,
            calendar_provider=InMemoryCalendarProvider({Market.US: [datetime(2026, 3, 2, 16, 0, 0), datetime(2026, 3, 3, 16, 0, 0)]}),
            universe_provider=InMemoryUniverseProvider(provider),
            research_data_bundle=build_default_bundle(provider, Market.US, "SP500_PROXY", date(2026, 3, 2)),
            benchmark_instrument_id=None,
        )
        snapshot_2 = MarketSnapshot(
            market=Market.US,
            as_of=datetime(2026, 3, 3, 16, 0, 0),
            data_provider=provider,
            calendar_provider=InMemoryCalendarProvider({Market.US: [datetime(2026, 3, 2, 16, 0, 0), datetime(2026, 3, 3, 16, 0, 0)]}),
            universe_provider=InMemoryUniverseProvider(provider),
            research_data_bundle=build_default_bundle(provider, Market.US, "SP500_PROXY", date(2026, 3, 3)),
            benchmark_instrument_id=None,
        )
        dataset = MarketDataset(
            market=Market.US,
            sessions=(date(2026, 3, 2), date(2026, 3, 3)),
            snapshots_by_session={
                date(2026, 3, 2): snapshot_1,
                date(2026, 3, 3): snapshot_2,
            },
        )
        spy = SnapshotBuilderSpy([snapshot_1, snapshot_2])

        snapshots = _actual_sessions(
            market=Market.US,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 3),
            detail_limit=2,
            history_limit=5,
            build_snapshot_fn=spy,
            market_dataset=dataset,
        )

        self.assertEqual([snapshot.as_of.date() for snapshot in snapshots], [date(2026, 3, 2), date(2026, 3, 3)])
        self.assertEqual(spy.calls, [])

    @patch("stock_quantification.backtest.fetch_cn_benchmark_history")
    @patch("stock_quantification.backtest.fetch_cn_detailed_history")
    def test_cn_history_windows_expand_for_year_long_backtests(self, mock_fetch_cn_detailed_history, mock_fetch_cn_benchmark_history) -> None:
        benchmark = Instrument("CN.000300", Market.CN, "000300", AssetType.ETF, "CNY", "SSE")
        stock = Instrument("CN.600487", Market.CN, "600487", AssetType.COMMON_STOCK, "CNY", "SSE")
        benchmark_bars = [
            Bar(benchmark.instrument_id, datetime(2025, 5, 6, 15, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
            Bar(benchmark.instrument_id, datetime(2025, 5, 7, 15, 0, 0), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), 100, Decimal("1010")),
        ]
        stock_bars = [
            Bar(stock.instrument_id, datetime(2025, 5, 6, 15, 0, 0), Decimal("20"), Decimal("20"), Decimal("20"), Decimal("20"), 100, Decimal("2000")),
            Bar(stock.instrument_id, datetime(2025, 5, 7, 15, 0, 0), Decimal("21"), Decimal("21"), Decimal("21"), Decimal("21"), 100, Decimal("2100")),
        ]
        mock_fetch_cn_benchmark_history.return_value = (benchmark, benchmark_bars)
        mock_fetch_cn_detailed_history.return_value = (stock, stock_bars)

        benchmark_entry_price, benchmark_exit_price, exit_date = _benchmark_window(Market.CN, date(2025, 5, 6), 1)
        entry_date, resolved_exit_date, entry_price, exit_price = _instrument_window(Market.CN, "CN.600487", date(2025, 5, 6), 1)

        self.assertEqual(benchmark_entry_price, Decimal("100"))
        self.assertEqual(benchmark_exit_price, Decimal("101"))
        self.assertEqual(exit_date, date(2025, 5, 7))
        self.assertEqual(entry_date, date(2025, 5, 6))
        self.assertEqual(resolved_exit_date, date(2025, 5, 7))
        self.assertEqual(entry_price, Decimal("20"))
        self.assertEqual(exit_price, Decimal("21"))
        self.assertGreaterEqual(mock_fetch_cn_benchmark_history.call_args.kwargs["limit"], 240)
        self.assertGreaterEqual(mock_fetch_cn_detailed_history.call_args.kwargs["limit"], 240)

    @patch("stock_quantification.backtest.fetch_us_benchmark_history")
    @patch("stock_quantification.backtest.fetch_us_daily_history")
    def test_us_history_windows_expand_for_year_long_backtests(self, mock_fetch_us_daily_history, mock_fetch_us_benchmark_history) -> None:
        benchmark = Instrument("US.SPY", Market.US, "SPY", AssetType.ETF, "USD", "NYSE")
        stock = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        benchmark_bars = [
            Bar(benchmark.instrument_id, datetime(2025, 5, 12, 16, 0, 0), Decimal("500"), Decimal("500"), Decimal("500"), Decimal("500"), 100, Decimal("5000")),
            Bar(benchmark.instrument_id, datetime(2025, 5, 13, 16, 0, 0), Decimal("505"), Decimal("505"), Decimal("505"), Decimal("505"), 100, Decimal("5050")),
        ]
        stock_bars = [
            Bar(stock.instrument_id, datetime(2025, 5, 12, 16, 0, 0), Decimal("180"), Decimal("180"), Decimal("180"), Decimal("180"), 100, Decimal("1800")),
            Bar(stock.instrument_id, datetime(2025, 5, 13, 16, 0, 0), Decimal("183"), Decimal("183"), Decimal("183"), Decimal("183"), 100, Decimal("1830")),
        ]
        mock_fetch_us_benchmark_history.return_value = (benchmark, benchmark_bars)
        mock_fetch_us_daily_history.return_value = (stock, stock_bars)

        benchmark_entry_price, benchmark_exit_price, exit_date = _benchmark_window(Market.US, date(2025, 5, 12), 1)
        entry_date, resolved_exit_date, entry_price, exit_price = _instrument_window(Market.US, "US.AAPL", date(2025, 5, 12), 1)

        self.assertEqual(benchmark_entry_price, Decimal("500"))
        self.assertEqual(benchmark_exit_price, Decimal("505"))
        self.assertEqual(exit_date, date(2025, 5, 13))
        self.assertEqual(entry_date, date(2025, 5, 12))
        self.assertEqual(resolved_exit_date, date(2025, 5, 13))
        self.assertEqual(entry_price, Decimal("180"))
        self.assertEqual(exit_price, Decimal("183"))
        self.assertGreaterEqual(mock_fetch_us_benchmark_history.call_args.kwargs["limit"], 240)
        self.assertGreaterEqual(mock_fetch_us_benchmark_history.call_args.kwargs["lookback_days"], 365)
        self.assertGreaterEqual(mock_fetch_us_daily_history.call_args.kwargs["limit"], 240)
        self.assertGreaterEqual(mock_fetch_us_daily_history.call_args.kwargs["lookback_days"], 365)

    @patch("stock_quantification.backtest._run_backtest_orchestration")
    def test_build_rolling_strategy_backtest_report_records_exit_signals(self, mock_run_backtest_orchestration) -> None:
        fill = ExecutionFill(
            order_intent_id="sell-aapl",
            account_id="us-test",
            instrument_id="US.AAPL",
            mode=RuntimeMode.BACKTEST,
            status=ExecutionStatus.FILLED,
            requested_qty=10,
            filled_qty=10,
            remaining_qty=0,
            reference_price=Decimal("100"),
            estimated_price=Decimal("100"),
            realized_price=Decimal("100"),
            slippage_bps=Decimal("0"),
            commission=Decimal("0"),
            taxes=Decimal("0"),
            total_fees=Decimal("0"),
            cash_delta=Decimal("1000"),
            estimated_cash_delta=Decimal("1000"),
        )
        execution_result = ExecutionResult(
            context=type("Context", (), {"as_of": datetime(2026, 3, 2, 16, 0, 0), "mode": RuntimeMode.BACKTEST})(),
            input_account_state=AccountState(
                account_id="us-test",
                market=Market.US,
                broker_id="paper-us",
                cash=Decimal("0"),
                buying_power=Decimal("0"),
            ),
            output_account_state=AccountState(
                account_id="us-test",
                market=Market.US,
                broker_id="paper-us",
                cash=Decimal("1000"),
                buying_power=Decimal("1000"),
            ),
            fills=[fill],
            applied_corporate_actions=[],
        )
        proposal = type(
            "Proposal",
            (),
            {
                "targets": [],
                "research_rankings": [
                    {
                        "instrument_id": "US.AAPL",
                        "score": Decimal("-0.2200"),
                        "selected": False,
                        "target_weight": Decimal("0"),
                        "raw_features": {"trend": Decimal("-0.3000")},
                        "contributions": {"trend": Decimal("-0.1800"), "volatility": Decimal("-0.0200")},
                    }
                ],
            },
        )()
        mock_run_backtest_orchestration.return_value = type(
            "Result",
            (),
            {
                "execution_results": [execution_result],
                "proposal": proposal,
                "review": ReviewReport(verdict=ReviewVerdict.PASS, comments=[]),
            },
        )()

        stock = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        benchmark = Instrument("US.SPY", Market.US, "SPY", AssetType.ETF, "USD", "NYSE")
        bars_by_instrument = {
            stock.instrument_id: [
                Bar(stock.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
                Bar(stock.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
            ],
            benchmark.instrument_id: [
                Bar(benchmark.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
                Bar(benchmark.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
            ],
        }
        provider = InMemoryMarketDataProvider([stock, benchmark], bars_by_instrument)
        bundle = build_default_bundle(provider, Market.US, "SP500_PROXY", date(2026, 3, 2))
        snapshot_1 = MarketSnapshot(
            market=Market.US,
            as_of=datetime(2026, 3, 2, 16, 0, 0),
            data_provider=provider,
            calendar_provider=InMemoryCalendarProvider({Market.US: [datetime(2026, 3, 2, 16, 0, 0)]}),
            universe_provider=InMemoryUniverseProvider(provider),
            research_data_bundle=ResearchDataBundle(
                market_data_provider=provider,
                fundamental_provider=bundle.fundamental_provider,
                benchmark_provider=bundle.benchmark_provider,
                corporate_action_provider=bundle.corporate_action_provider,
                benchmark_ids_by_market=bundle.benchmark_ids_by_market,
            ),
            benchmark_instrument_id=benchmark.instrument_id,
        )
        snapshot_2 = MarketSnapshot(
            market=Market.US,
            as_of=datetime(2026, 3, 3, 16, 0, 0),
            data_provider=provider,
            calendar_provider=InMemoryCalendarProvider({Market.US: [datetime(2026, 3, 3, 16, 0, 0)]}),
            universe_provider=InMemoryUniverseProvider(provider),
            research_data_bundle=snapshot_1.research_data_bundle,
            benchmark_instrument_id=benchmark.instrument_id,
        )

        def fake_build_snapshot(market, symbols, detail_limit, history_limit, as_of_date):
            if as_of_date == date(2026, 3, 2):
                return snapshot_1
            return snapshot_2

        preset = next(item for item in strategy_presets_for_market(Market.US) if item.preset_id == "us_momentum_core")
        report = build_rolling_strategy_backtest_report(
            market=Market.US,
            preset=preset,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 3),
            detail_limit=2,
            history_limit=5,
            build_snapshot_fn=fake_build_snapshot,
        )

        serialized = serialize_rolling_backtest_report(report)
        self.assertEqual(serialized["summary"]["trend_exit_count"], 1)
        self.assertEqual(serialized["summary"]["rank_exit_count"], 0)
        self.assertEqual(serialized["summary"]["risk_exit_count"], 0)
        self.assertEqual(serialized["summary"]["other_exit_count"], 0)
        self.assertEqual(serialized["exit_events"][0]["instrument_id"], "US.AAPL")
        self.assertEqual(serialized["exit_events"][0]["reason_label"], "趋势失效")

    @patch("stock_quantification.backtest._build_orchestrator", side_effect=AssertionError("orchestrator shell should not be used"), create=True)
    @patch("stock_quantification.backtest.run_strategy_cycle")
    def test_build_rolling_strategy_backtest_report_does_not_require_orchestrator_shell(
        self,
        mock_run_strategy_cycle,
        _mock_build_orchestrator,
    ) -> None:
        stock = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        benchmark = Instrument("US.SPY", Market.US, "SPY", AssetType.ETF, "USD", "NYSE")
        bars_by_instrument = {
            stock.instrument_id: [
                Bar(stock.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
                Bar(stock.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), 100, Decimal("1010")),
            ],
            benchmark.instrument_id: [
                Bar(benchmark.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
                Bar(benchmark.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("102"), Decimal("102"), Decimal("102"), Decimal("102"), 100, Decimal("1020")),
            ],
        }
        provider = InMemoryMarketDataProvider([stock, benchmark], bars_by_instrument)
        bundle = build_default_bundle(provider, Market.US, "SP500_PROXY", date(2026, 3, 2))
        snapshot_1 = MarketSnapshot(
            market=Market.US,
            as_of=datetime(2026, 3, 2, 16, 0, 0),
            data_provider=provider,
            calendar_provider=InMemoryCalendarProvider({Market.US: [datetime(2026, 3, 2, 16, 0, 0)]}),
            universe_provider=InMemoryUniverseProvider(provider),
            research_data_bundle=ResearchDataBundle(
                market_data_provider=provider,
                fundamental_provider=bundle.fundamental_provider,
                benchmark_provider=bundle.benchmark_provider,
                corporate_action_provider=bundle.corporate_action_provider,
                benchmark_ids_by_market=bundle.benchmark_ids_by_market,
            ),
            benchmark_instrument_id=benchmark.instrument_id,
        )
        snapshot_2 = MarketSnapshot(
            market=Market.US,
            as_of=datetime(2026, 3, 3, 16, 0, 0),
            data_provider=provider,
            calendar_provider=InMemoryCalendarProvider({Market.US: [datetime(2026, 3, 3, 16, 0, 0)]}),
            universe_provider=InMemoryUniverseProvider(provider),
            research_data_bundle=snapshot_1.research_data_bundle,
            benchmark_instrument_id=benchmark.instrument_id,
        )

        def fake_build_snapshot(market, symbols, detail_limit, history_limit, as_of_date):
            if as_of_date == date(2026, 3, 2):
                return snapshot_1
            return snapshot_2

        proposal = StrategyProposal(
            research_report=ResearchReport(
                market=Market.US,
                as_of=snapshot_1.as_of,
                highlights=["signal_count=1"],
                candidate_instruments=["US.AAPL"],
            ),
            signals=[
                SignalSnapshot(
                    as_of=snapshot_1.as_of,
                    strategy_id="us_quality_momentum",
                    instrument_id="US.AAPL",
                    score=Decimal("1.0"),
                    direction="LONG",
                    reason="alpha(momentum)",
                )
            ],
            factors=[],
            targets=[],
            trade_suggestions=[],
        )
        mock_run_strategy_cycle.return_value = SimpleNamespace(
            proposal=proposal,
            review=ReviewReport(verdict=ReviewVerdict.PASS, comments=[]),
            order_intents=[],
            risk_results=[],
            execution_results=[],
        )

        preset = next(item for item in strategy_presets_for_market(Market.US) if item.preset_id == "us_momentum_core")
        report = build_rolling_strategy_backtest_report(
            market=Market.US,
            preset=preset,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 3),
            detail_limit=2,
            history_limit=5,
            build_snapshot_fn=fake_build_snapshot,
        )

        serialized = serialize_rolling_backtest_report(report)
        self.assertEqual(serialized["summary"]["trading_days"], 2)
        self.assertEqual(mock_run_strategy_cycle.call_count, 1)

    @patch("stock_quantification.backtest_dataset._fetch_market_benchmark_constituents")
    @patch("stock_quantification.backtest_dataset.fetch_us_benchmark_history")
    @patch("stock_quantification.backtest_dataset.fetch_us_daily_history")
    def test_market_dataset_builds_sessions_once_for_requested_range(
        self,
        mock_fetch_us_daily_history,
        mock_fetch_us_benchmark_history,
        mock_fetch_constituents,
    ) -> None:
        mock_fetch_constituents.return_value = []
        benchmark = Instrument("US.SPY", Market.US, "SPY", AssetType.ETF, "USD", "NYSE")
        aapl = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        msft = Instrument("US.MSFT", Market.US, "MSFT", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        benchmark_bars = [
            Bar(benchmark.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
            Bar(benchmark.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("102"), Decimal("102"), Decimal("102"), Decimal("102"), 100, Decimal("1020")),
        ]
        stock_bars = [
            Bar(aapl.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
            Bar(aapl.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), 100, Decimal("1010")),
        ]
        msft_bars = [
            Bar(msft.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("200"), Decimal("200"), Decimal("200"), Decimal("200"), 100, Decimal("2000")),
            Bar(msft.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("198"), Decimal("198"), Decimal("198"), Decimal("198"), 100, Decimal("1980")),
        ]
        mock_fetch_us_daily_history.side_effect = [
            (aapl, stock_bars),
            (msft, msft_bars),
        ]
        mock_fetch_us_benchmark_history.return_value = (benchmark, benchmark_bars)

        dataset = build_market_dataset(
            market=Market.US,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 3),
            detail_limit=2,
            history_limit=5,
            symbols=["AAPL", "MSFT"],
        )

        self.assertEqual(dataset.sessions, (date(2026, 3, 2), date(2026, 3, 3)))
        self.assertEqual(mock_fetch_us_daily_history.call_count, 2)
        self.assertEqual(mock_fetch_us_benchmark_history.call_count, 1)

    @patch("stock_quantification.backtest_dataset._fetch_market_benchmark_constituents")
    @patch("stock_quantification.backtest_dataset.fetch_us_benchmark_history")
    @patch("stock_quantification.backtest_dataset.fetch_us_daily_history")
    def test_market_dataset_can_materialize_snapshot_for_each_session(
        self,
        mock_fetch_us_daily_history,
        mock_fetch_us_benchmark_history,
        mock_fetch_constituents,
    ) -> None:
        mock_fetch_constituents.return_value = []
        benchmark = Instrument("US.SPY", Market.US, "SPY", AssetType.ETF, "USD", "NYSE")
        stock = Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ")
        bars = [
            Bar(stock.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
            Bar(stock.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), 100, Decimal("1010")),
        ]
        benchmark_bars = [
            Bar(benchmark.instrument_id, datetime(2026, 3, 2, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100, Decimal("1000")),
            Bar(benchmark.instrument_id, datetime(2026, 3, 3, 16, 0, 0), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), 100, Decimal("1010")),
        ]
        mock_fetch_us_daily_history.return_value = (stock, bars)
        mock_fetch_us_benchmark_history.return_value = (benchmark, benchmark_bars)

        dataset = build_market_dataset(
            market=Market.US,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 3),
            detail_limit=1,
            history_limit=5,
            symbols=["AAPL"],
        )

        self.assertEqual(dataset.snapshot_for_session(date(2026, 3, 2)).as_of.date(), date(2026, 3, 2))
        self.assertEqual(dataset.snapshot_for_session(date(2026, 3, 3)).as_of.date(), date(2026, 3, 3))
        self.assertEqual([snapshot.as_of.date() for snapshot in dataset.materialize_snapshots()], [date(2026, 3, 2), date(2026, 3, 3)])
