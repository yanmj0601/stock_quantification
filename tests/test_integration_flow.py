from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch

from stock_quantification.agents import Orchestrator, ResearchAgent, ReviewAgent, StrategyAgent
from stock_quantification.engine import (
    BaseSelectionStrategy,
    EqualWeightPortfolioConstructor,
    InMemoryCalendarProvider,
    InMemoryMarketDataProvider,
    InMemoryUniverseProvider,
    StandardExecutionPlanner,
    StandardRiskEngine,
    StandardStrategyRunner,
)
from stock_quantification.markets import ChinaMarketRules, USMarketRules
from stock_quantification.models import (
    AccountConstraints,
    AccountState,
    AssetType,
    Bar,
    ExecutionMode,
    Instrument,
    Market,
    PaperContext,
    Position,
    SignalSnapshot,
    TargetPosition,
)
from stock_quantification.pipeline import build_us_quality_momentum_blueprint
from stock_quantification.real_data import build_market_snapshot
from stock_quantification.research_data import build_default_bundle
from stock_quantification.state import InMemoryStateStore


class FixedTargetsStrategy:
    strategy_id = "fixed_targets"
    market = Market.US

    def __init__(self, as_of: datetime, targets: list[TargetPosition], signal_ids: list[str]) -> None:
        self._as_of = as_of
        self._targets = targets
        self._signal_ids = signal_ids

    def generate(self, data_provider, universe, as_of, current_weights=None):
        del data_provider, universe, current_weights
        signals = [
            SignalSnapshot(
                as_of=as_of,
                strategy_id=self.strategy_id,
                instrument_id=instrument_id,
                score=Decimal("1.0") - Decimal(index) / Decimal("10"),
                direction="LONG",
                reason=f"fixed_signal_{instrument_id}",
            )
            for index, instrument_id in enumerate(self._signal_ids)
        ]
        rankings = [
            {
                "instrument_id": target.instrument_id,
                "score": Decimal("1.0") - Decimal(index) / Decimal("10"),
                "sector": "Technology",
                "selected": target.target_weight > 0,
                "target_weight": target.target_weight,
                "contributions": {"fixed": Decimal("1.0")},
                "raw_features": {},
            }
            for index, target in enumerate(self._targets)
        ]
        return {
            "signals": signals,
            "factors": [],
            "targets": self._targets,
            "portfolio_diagnostics": {"turnover": "0.0000", "selected_count": len(self._targets)},
            "rankings": rankings,
        }


class TurnoverAwareStrategy(BaseSelectionStrategy):
    strategy_id = "turnover_aware"
    market = Market.US

    def generate(self, data_provider, universe, as_of, current_weights=None):
        return self._run_pipeline(data_provider, universe, as_of, current_weights=current_weights)

    def _pipeline_blueprint(self, allowed_instrument_ids):
        blueprint = build_us_quality_momentum_blueprint(
            benchmark_instrument_id=None,
            allowed_instrument_ids=tuple(allowed_instrument_ids),
            benchmark_weights={},
        )
        return replace(
            blueprint,
            alpha_weights={
                "rel_ret_20": Decimal("0.70"),
                "rel_ret_60": Decimal("0.30"),
            },
            portfolio_policy=replace(
                blueprint.portfolio_policy,
                top_n=1,
                benchmark_blend=Decimal("0"),
                turnover_cap=Decimal("0.10"),
                cash_buffer=Decimal("0"),
                max_position_weight=Decimal("1.0"),
                max_sector_weight=Decimal("1.0"),
            ),
        )


def _build_bars(instrument_id: str, start: Decimal, end: Decimal, as_of: datetime, sessions: int = 70) -> list[Bar]:
    bars: list[Bar] = []
    step = (end - start) / Decimal(sessions - 1)
    for index in range(sessions):
        close = (start + step * Decimal(index)).quantize(Decimal("0.0001"))
        timestamp = as_of - timedelta(days=sessions - 1 - index)
        timestamp = timestamp.replace(hour=16, minute=0, second=0)
        bars.append(
            Bar(
                instrument_id=instrument_id,
                timestamp=timestamp,
                open=close,
                high=close * Decimal("1.01"),
                low=close * Decimal("0.99"),
                close=close,
                volume=1_000_000,
                turnover=Decimal("100000000"),
            )
        )
    return bars


class IntegrationFlowTests(unittest.TestCase):
    @patch("stock_quantification.real_data._build_real_research_bundle")
    @patch("stock_quantification.real_data.fetch_cn_benchmark_history")
    @patch("stock_quantification.real_data.fetch_cn_detailed_history")
    def test_symbols_mode_historical_snapshot_uses_full_research_window(
        self,
        mock_fetch_detailed,
        mock_fetch_benchmark,
        mock_bundle_builder,
    ) -> None:
        as_of = datetime(2026, 4, 3, 15, 0, 0)
        symbol_bars = [
            Bar(
                "CN.600000",
                (as_of - timedelta(days=index)).replace(hour=15, minute=0, second=0),
                Decimal("10"),
                Decimal("10.1"),
                Decimal("9.9"),
                Decimal("10"),
                1_000_000,
                Decimal("100000000"),
            )
            for index in reversed(range(120))
        ]
        benchmark_bars = [
            Bar(
                "CN.000300",
                (as_of - timedelta(days=index)).replace(hour=15, minute=0, second=0),
                Decimal("4"),
                Decimal("4.1"),
                Decimal("3.9"),
                Decimal("4"),
                1_000_000,
                Decimal("100000000"),
            )
            for index in reversed(range(120))
        ]
        mock_fetch_detailed.return_value = (
            Instrument("CN.600000", Market.CN, "600000", AssetType.COMMON_STOCK, "CNY", "SSE", attributes={"listed_days": 500, "is_st": False}),
            symbol_bars,
        )
        mock_fetch_benchmark.return_value = (
            Instrument("CN.000300", Market.CN, "000300", AssetType.ETF, "CNY", "SSE"),
            benchmark_bars,
        )
        mock_bundle_builder.side_effect = (
            lambda provider, market, bundle_as_of, benchmark_id, **kwargs: build_default_bundle(
                provider,
                market,
                benchmark_id,
                bundle_as_of,
            )
        )
        snapshot = build_market_snapshot(
            Market.CN,
            symbols=["600000"],
            history_limit=60,
            as_of_date=date(2026, 3, 15),
        )
        history = snapshot.data_provider.get_price_history("CN.600000", snapshot.as_of, 60)
        self.assertEqual(snapshot.as_of.date().isoformat(), "2026-03-15")
        self.assertEqual(len(history), 60)

    def test_execution_planner_rebalances_and_sells_removed_positions(self) -> None:
        as_of = datetime(2026, 4, 3, 16, 0, 0)
        instruments = [
            Instrument("US.KEEP", Market.US, "KEEP", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
            Instrument("US.NEW", Market.US, "NEW", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
            Instrument("US.OLD", Market.US, "OLD", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
        ]
        bars = {
            instrument.instrument_id: [
                Bar(instrument.instrument_id, as_of, Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1_000_000, Decimal("100000000"))
            ]
            for instrument in instruments
        }
        data_provider = InMemoryMarketDataProvider(instruments, bars)
        calendar_provider = InMemoryCalendarProvider({Market.US: [as_of]})
        universe_provider = InMemoryUniverseProvider(data_provider)
        strategy_runner = StandardStrategyRunner(data_provider, universe_provider, calendar_provider)
        execution_planner = StandardExecutionPlanner(data_provider)
        risk_engine = StandardRiskEngine(data_provider, {Market.US: USMarketRules()})
        state_store = InMemoryStateStore()
        state_store.save_account_state(
            AccountState(
                account_id="acct",
                market=Market.US,
                broker_id="paper-us",
                cash=Decimal("0"),
                buying_power=Decimal("0"),
                positions={
                    "US.KEEP": Position("US.KEEP", 50, Decimal("10")),
                    "US.OLD": Position("US.OLD", 50, Decimal("10")),
                },
                constraints=AccountConstraints(max_position_weight=Decimal("1.0"), max_single_order_value=Decimal("100000")),
            )
        )
        strategy = FixedTargetsStrategy(
            as_of,
            targets=[
                TargetPosition(as_of, "fixed_targets", "US", "US.KEEP", Decimal("0.25")),
                TargetPosition(as_of, "fixed_targets", "US", "US.NEW", Decimal("0.25")),
            ],
            signal_ids=["US.KEEP", "US.NEW"],
        )
        orchestrator = Orchestrator(
            research_agent=ResearchAgent(strategy_runner),
            strategy_agent=StrategyAgent(strategy_runner, EqualWeightPortfolioConstructor(top_n=2), execution_planner, state_store),
            review_agent=ReviewAgent(),
            execution_planner=execution_planner,
            risk_engine=risk_engine,
            state_store=state_store,
        )
        result = orchestrator.run(PaperContext(as_of=as_of), strategy, ["acct"], ExecutionMode.ADVISORY)
        actions = {(item.instrument_id, item.side.value, item.suggested_qty) for item in result.proposal.trade_suggestions}
        self.assertIn(("US.OLD", "SELL", 50), actions)
        self.assertIn(("US.KEEP", "SELL", 25), actions)
        self.assertIn(("US.NEW", "BUY", 25), actions)

    def test_risk_engine_updates_cash_and_rejects_second_buy_sequentially(self) -> None:
        as_of = datetime(2026, 4, 3, 16, 0, 0)
        instruments = [
            Instrument("US.AAA", Market.US, "AAA", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
            Instrument("US.BBB", Market.US, "BBB", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
        ]
        bars = {
            "US.AAA": [Bar("US.AAA", as_of, Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1_000_000, Decimal("100000000"))],
            "US.BBB": [Bar("US.BBB", as_of, Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1_000_000, Decimal("100000000"))],
        }
        data_provider = InMemoryMarketDataProvider(instruments, bars)
        calendar_provider = InMemoryCalendarProvider({Market.US: [as_of]})
        universe_provider = InMemoryUniverseProvider(data_provider)
        strategy_runner = StandardStrategyRunner(data_provider, universe_provider, calendar_provider)
        execution_planner = StandardExecutionPlanner(data_provider)
        risk_engine = StandardRiskEngine(data_provider, {Market.US: USMarketRules()})
        state_store = InMemoryStateStore()
        state_store.save_account_state(
            AccountState(
                account_id="acct",
                market=Market.US,
                broker_id="paper-us",
                cash=Decimal("1000"),
                buying_power=Decimal("1000"),
                positions={},
                constraints=AccountConstraints(max_position_weight=Decimal("1.0"), max_single_order_value=Decimal("100000")),
            )
        )
        strategy = FixedTargetsStrategy(
            as_of,
            targets=[
                TargetPosition(as_of, "fixed_targets", "US", "US.AAA", Decimal("0.80")),
                TargetPosition(as_of, "fixed_targets", "US", "US.BBB", Decimal("0.80")),
            ],
            signal_ids=["US.AAA", "US.BBB"],
        )
        orchestrator = Orchestrator(
            research_agent=ResearchAgent(strategy_runner),
            strategy_agent=StrategyAgent(strategy_runner, EqualWeightPortfolioConstructor(top_n=2), execution_planner, state_store),
            review_agent=ReviewAgent(),
            execution_planner=execution_planner,
            risk_engine=risk_engine,
            state_store=state_store,
        )
        result = orchestrator.run(PaperContext(as_of=as_of), strategy, ["acct"], ExecutionMode.ADVISORY)
        approved = [(intent.instrument_id, intent.qty) for intent in result.order_intents]
        self.assertEqual(approved, [("US.AAA", 80)])
        rejections = {
            risk.order_intent_id: risk.violations
            for risk in result.risk_results
            if not risk.passed
        }
        self.assertTrue(any("insufficient_buying_power" in violations for violations in rejections.values()))

    def test_current_holdings_flow_into_pipeline_turnover_cap(self) -> None:
        as_of = datetime(2026, 4, 3, 16, 0, 0)
        instruments = [
            Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ", attributes={"listed_days": 500, "profitability": "0.5"}),
            Instrument("US.MSFT", Market.US, "MSFT", AssetType.COMMON_STOCK, "USD", "NASDAQ", attributes={"listed_days": 500, "profitability": "0.8"}),
        ]
        bars = {
            "US.AAPL": _build_bars("US.AAPL", Decimal("100"), Decimal("95"), as_of),
            "US.MSFT": _build_bars("US.MSFT", Decimal("100"), Decimal("160"), as_of),
        }
        data_provider = InMemoryMarketDataProvider(instruments, bars)
        calendar_provider = InMemoryCalendarProvider({Market.US: [as_of]})
        universe_provider = InMemoryUniverseProvider(data_provider)
        strategy_runner = StandardStrategyRunner(data_provider, universe_provider, calendar_provider)
        execution_planner = StandardExecutionPlanner(data_provider)
        risk_engine = StandardRiskEngine(data_provider, {Market.US: USMarketRules()})
        state_store = InMemoryStateStore()
        state_store.save_account_state(
            AccountState(
                account_id="acct",
                market=Market.US,
                broker_id="paper-us",
                cash=Decimal("0"),
                buying_power=Decimal("0"),
                positions={"US.AAPL": Position("US.AAPL", 50, Decimal("100"))},
                constraints=AccountConstraints(max_position_weight=Decimal("1.0"), max_single_order_value=Decimal("100000")),
            )
        )
        orchestrator = Orchestrator(
            research_agent=ResearchAgent(strategy_runner),
            strategy_agent=StrategyAgent(strategy_runner, EqualWeightPortfolioConstructor(top_n=2), execution_planner, state_store),
            review_agent=ReviewAgent(),
            execution_planner=execution_planner,
            risk_engine=risk_engine,
            state_store=state_store,
        )
        result = orchestrator.run(PaperContext(as_of=as_of), TurnoverAwareStrategy(top_n=1), ["acct"], ExecutionMode.ADVISORY)
        target_ids = {target.instrument_id for target in result.proposal.targets}
        self.assertIn("US.AAPL", target_ids)
        self.assertIn("US.MSFT", target_ids)
        self.assertLessEqual(Decimal(result.proposal.portfolio_diagnostics["turnover"]), Decimal("0.1000"))
        actions = {(item.instrument_id, item.side.value) for item in result.proposal.trade_suggestions}
        self.assertIn(("US.AAPL", "SELL"), actions)
        self.assertIn(("US.MSFT", "BUY"), actions)


if __name__ == "__main__":
    unittest.main()
