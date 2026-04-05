from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import unittest

from stock_quantification.agents import Orchestrator, ResearchAgent, ReviewAgent, StrategyAgent
from stock_quantification.engine import (
    AStockSelectionStrategy,
    EqualWeightPortfolioConstructor,
    InMemoryCalendarProvider,
    InMemoryMarketDataProvider,
    InMemoryUniverseProvider,
    StandardExecutionPlanner,
    StandardRiskEngine,
    StandardStrategyRunner,
    USStockSelectionStrategy,
)
from stock_quantification.markets import ChinaMarketRules, USMarketRules
from stock_quantification.models import (
    AccountConstraints,
    AccountState,
    AssetType,
    BacktestContext,
    Bar,
    ExecutionMode,
    Instrument,
    InstrumentStatus,
    LiveContext,
    Market,
    PaperContext,
    Position,
)
from stock_quantification.state import InMemoryStateStore


class PlatformFixture:
    def __init__(self) -> None:
        self.cn_as_of = datetime(2026, 4, 3, 15, 0, 0)
        self.us_as_of = datetime(2026, 4, 3, 16, 0, 0)
        instruments = [
            Instrument("CN.600000", Market.CN, "600000", AssetType.COMMON_STOCK, "CNY", "SSE", attributes={"listed_days": 600, "is_st": False}),
            Instrument("CN.000001", Market.CN, "000001", AssetType.COMMON_STOCK, "CNY", "SZSE", attributes={"listed_days": 900, "is_st": False}),
            Instrument("CN.600666", Market.CN, "600666", AssetType.COMMON_STOCK, "CNY", "SSE", attributes={"listed_days": 600, "is_st": True}),
            Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ", attributes={"profitability": "0.8"}),
            Instrument("US.MSFT", Market.US, "MSFT", AssetType.COMMON_STOCK, "USD", "NASDAQ", attributes={"profitability": "0.9"}),
            Instrument("US.BABA", Market.US, "BABA", AssetType.ADR, "USD", "NYSE", attributes={"profitability": "0.7", "is_adr": True}),
        ]
        bars = {
            "CN.600000": [
                Bar("CN.600000", datetime(2026, 4, 2, 15, 0, 0), Decimal("10"), Decimal("10.1"), Decimal("9.8"), Decimal("10"), 1000000, Decimal("800000000")),
                Bar("CN.600000", self.cn_as_of, Decimal("10"), Decimal("10.8"), Decimal("10"), Decimal("10.6"), 1200000, Decimal("1000000000")),
            ],
            "CN.000001": [
                Bar("CN.000001", datetime(2026, 4, 2, 15, 0, 0), Decimal("8"), Decimal("8.2"), Decimal("7.8"), Decimal("8"), 900000, Decimal("600000000")),
                Bar("CN.000001", self.cn_as_of, Decimal("8"), Decimal("8.4"), Decimal("7.9"), Decimal("8.1"), 950000, Decimal("500000000")),
            ],
            "CN.600666": [
                Bar("CN.600666", datetime(2026, 4, 2, 15, 0, 0), Decimal("5"), Decimal("5.2"), Decimal("4.8"), Decimal("5"), 500000, Decimal("200000000")),
                Bar("CN.600666", self.cn_as_of, Decimal("5"), Decimal("5.5"), Decimal("5"), Decimal("5.4"), 550000, Decimal("210000000")),
            ],
            "US.AAPL": [
                Bar("US.AAPL", datetime(2026, 4, 2, 16, 0, 0), Decimal("180"), Decimal("181"), Decimal("179"), Decimal("180"), 1000000, Decimal("1500000000")),
                Bar("US.AAPL", self.us_as_of, Decimal("180"), Decimal("186"), Decimal("180"), Decimal("185"), 1100000, Decimal("1800000000")),
            ],
            "US.MSFT": [
                Bar("US.MSFT", datetime(2026, 4, 2, 16, 0, 0), Decimal("300"), Decimal("301"), Decimal("299"), Decimal("300"), 1000000, Decimal("1400000000")),
                Bar("US.MSFT", self.us_as_of, Decimal("300"), Decimal("309"), Decimal("300"), Decimal("308"), 1200000, Decimal("1700000000")),
            ],
            "US.BABA": [
                Bar("US.BABA", datetime(2026, 4, 2, 16, 0, 0), Decimal("90"), Decimal("92"), Decimal("89"), Decimal("90"), 1000000, Decimal("1200000000")),
                Bar("US.BABA", self.us_as_of, Decimal("90"), Decimal("95"), Decimal("90"), Decimal("94"), 1200000, Decimal("1250000000")),
            ],
        }
        self.data_provider = InMemoryMarketDataProvider(instruments, bars)
        self.calendar_provider = InMemoryCalendarProvider({Market.CN: [self.cn_as_of], Market.US: [self.us_as_of]})
        self.universe_provider = InMemoryUniverseProvider(self.data_provider)
        self.strategy_runner = StandardStrategyRunner(self.data_provider, self.universe_provider, self.calendar_provider)
        self.portfolio_constructor = EqualWeightPortfolioConstructor(top_n=2)
        self.execution_planner = StandardExecutionPlanner(self.data_provider)
        self.risk_engine = StandardRiskEngine(self.data_provider, {Market.CN: ChinaMarketRules(), Market.US: USMarketRules()})
        self.state_store = InMemoryStateStore()
        self.state_store.save_account_state(
            AccountState(
                account_id="cn-alpha",
                market=Market.CN,
                broker_id="broker-cn",
                cash=Decimal("200000"),
                buying_power=Decimal("200000"),
                positions={
                    "CN.600000": Position("CN.600000", 1000, Decimal("9.5"), last_trade_date=date(2026, 4, 1)),
                },
                constraints=AccountConstraints(max_position_weight=Decimal("0.60"), max_single_order_value=Decimal("1000000")),
            )
        )
        self.state_store.save_account_state(
            AccountState(
                account_id="cn-beta",
                market=Market.CN,
                broker_id="broker-cn",
                cash=Decimal("100000"),
                buying_power=Decimal("100000"),
                positions={},
                constraints=AccountConstraints(max_position_weight=Decimal("0.60"), max_single_order_value=Decimal("1000000")),
            )
        )
        self.state_store.save_account_state(
            AccountState(
                account_id="us-alpha",
                market=Market.US,
                broker_id="broker-us",
                cash=Decimal("60000"),
                buying_power=Decimal("60000"),
                positions={},
                constraints=AccountConstraints(max_position_weight=Decimal("0.60"), max_single_order_value=Decimal("1000000")),
            )
        )
        self.orchestrator = Orchestrator(
            research_agent=ResearchAgent(self.strategy_runner),
            strategy_agent=StrategyAgent(
                self.strategy_runner,
                self.portfolio_constructor,
                self.execution_planner,
                self.state_store,
            ),
            review_agent=ReviewAgent(),
            execution_planner=self.execution_planner,
            risk_engine=self.risk_engine,
            state_store=self.state_store,
        )


class PlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = PlatformFixture()

    def test_cn_and_us_share_common_output_shapes(self) -> None:
        cn_result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.cn_as_of),
            AStockSelectionStrategy(),
            ["cn-alpha"],
            ExecutionMode.ADVISORY,
        )
        us_result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.us_as_of),
            USStockSelectionStrategy(),
            ["us-alpha"],
            ExecutionMode.ADVISORY,
        )

        self.assertTrue(cn_result.proposal.signals)
        self.assertTrue(us_result.proposal.signals)
        self.assertEqual(cn_result.proposal.signals[0].__class__, us_result.proposal.signals[0].__class__)
        self.assertEqual(cn_result.proposal.targets[0].__class__, us_result.proposal.targets[0].__class__)

    def test_agent_chain_generates_daily_output(self) -> None:
        result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.cn_as_of),
            AStockSelectionStrategy(),
            ["cn-alpha"],
            ExecutionMode.ADVISORY,
        )
        self.assertIn("signal_count=", result.proposal.research_report.highlights[1])
        self.assertTrue(result.proposal.trade_suggestions)
        self.assertEqual(result.review.verdict.value, "PASS")

    def test_risk_engine_keeps_submission_outside_agents(self) -> None:
        result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.cn_as_of),
            AStockSelectionStrategy(),
            ["cn-alpha"],
            ExecutionMode.ADVISORY,
        )
        self.assertTrue(result.order_intents)
        self.assertTrue(all(intent.requires_manual_approval for intent in result.order_intents))

    def test_multi_account_state_is_isolated(self) -> None:
        result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.cn_as_of),
            AStockSelectionStrategy(),
            ["cn-alpha", "cn-beta"],
            ExecutionMode.ADVISORY,
        )
        accounts = {suggestion.account_id for suggestion in result.proposal.trade_suggestions}
        self.assertEqual(accounts, {"cn-alpha", "cn-beta"})
        alpha_qty = [s.suggested_qty for s in result.proposal.trade_suggestions if s.account_id == "cn-alpha"]
        beta_qty = [s.suggested_qty for s in result.proposal.trade_suggestions if s.account_id == "cn-beta"]
        self.assertNotEqual(alpha_qty, beta_qty)

    def test_manual_and_auto_modes_share_same_planning_payload(self) -> None:
        advisory_result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.us_as_of),
            USStockSelectionStrategy(),
            ["us-alpha"],
            ExecutionMode.ADVISORY,
        )
        auto_result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.us_as_of),
            USStockSelectionStrategy(),
            ["us-alpha"],
            ExecutionMode.AUTO,
        )
        self.assertEqual(
            [(intent.instrument_id, intent.side, intent.qty) for intent in advisory_result.order_intents],
            [(intent.instrument_id, intent.side, intent.qty) for intent in auto_result.order_intents],
        )
        self.assertTrue(all(intent.requires_manual_approval for intent in advisory_result.order_intents))
        self.assertTrue(all(not intent.requires_manual_approval for intent in auto_result.order_intents))

    def test_repeated_refresh_deduplicates_suggestions_and_orders(self) -> None:
        first_result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.us_as_of),
            USStockSelectionStrategy(),
            ["us-alpha"],
            ExecutionMode.ADVISORY,
        )
        self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.us_as_of),
            USStockSelectionStrategy(),
            ["us-alpha"],
            ExecutionMode.ADVISORY,
        )
        expected_count = len(first_result.proposal.trade_suggestions)
        self.assertEqual(self.fixture.state_store.suggestion_count(), expected_count)
        self.assertEqual(self.fixture.state_store.order_intent_count(), expected_count)

    def test_china_rules_block_limit_up_and_t_plus_one(self) -> None:
        latest_cn_bar = self.fixture.data_provider._bars_by_instrument["CN.600000"][-1]
        latest_cn_bar.extras["limit_up"] = True
        account = self.fixture.state_store.get_account_state("cn-alpha")
        account.positions["CN.600000"] = Position("CN.600000", 1000, Decimal("9.5"), last_trade_date=self.fixture.cn_as_of.date())
        result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.cn_as_of),
            AStockSelectionStrategy(),
            ["cn-alpha"],
            ExecutionMode.ADVISORY,
        )
        violations = [violation for risk in result.risk_results for violation in risk.violations]
        self.assertTrue("limit_up_block" in violations or "t_plus_one_restriction" in violations)

    def test_us_rules_block_adr_and_extended_hours(self) -> None:
        instrument = self.fixture.data_provider.get_instrument("US.BABA")
        self.assertEqual(instrument.asset_type, AssetType.ADR)
        extended_bar = self.fixture.data_provider._bars_by_instrument["US.MSFT"][-1]
        extended_bar.extras["extended_hours"] = True
        result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.us_as_of),
            USStockSelectionStrategy(),
            ["us-alpha"],
            ExecutionMode.ADVISORY,
        )
        violations = [violation for risk in result.risk_results for violation in risk.violations]
        self.assertIn("extended_hours_blocked", violations)
        self.assertNotIn("US.BABA", [signal.instrument_id for signal in result.proposal.signals])

    def test_contexts_share_strategy_semantics(self) -> None:
        backtest_result = self.fixture.orchestrator.run(
            BacktestContext(as_of=self.fixture.us_as_of),
            USStockSelectionStrategy(),
            ["us-alpha"],
            ExecutionMode.ADVISORY,
        )
        paper_result = self.fixture.orchestrator.run(
            PaperContext(as_of=self.fixture.us_as_of),
            USStockSelectionStrategy(),
            ["us-alpha"],
            ExecutionMode.ADVISORY,
        )
        live_result = self.fixture.orchestrator.run(
            LiveContext(as_of=self.fixture.us_as_of),
            USStockSelectionStrategy(),
            ["us-alpha"],
            ExecutionMode.ADVISORY,
        )
        expected = [signal.instrument_id for signal in live_result.proposal.signals]
        self.assertEqual(expected, [signal.instrument_id for signal in backtest_result.proposal.signals])
        self.assertEqual(expected, [signal.instrument_id for signal in paper_result.proposal.signals])


if __name__ == "__main__":
    unittest.main()
