from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from stock_quantification.backtest import (
    build_forward_return_report,
    build_rolling_strategy_backtest_report,
    serialize_backtest_report,
    serialize_rolling_backtest_report,
)
from stock_quantification.engine import InMemoryCalendarProvider, InMemoryMarketDataProvider, InMemoryUniverseProvider
from stock_quantification.research_data import ResearchDataBundle, build_default_bundle
from stock_quantification.real_data import MarketSnapshot
from stock_quantification.strategy_catalog import strategy_presets_for_market

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

    @patch("stock_quantification.backtest._build_orchestrator")
    def test_build_rolling_strategy_backtest_report(self, mock_build_orchestrator) -> None:
        class FakeOrchestrator:
            def run(self, *args, **kwargs):
                return type("Result", (), {"execution_results": []})()

        mock_build_orchestrator.return_value = FakeOrchestrator()

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
