from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import unittest

from stock_quantification.agents import ResearchAgent, ReviewAgent, StrategyAgent
from stock_quantification.engine import EqualWeightPortfolioConstructor
from stock_quantification.interfaces import StrategyDefinition
from stock_quantification.models import (
    AccountConstraints,
    AccountState,
    FactorSnapshot,
    Instrument,
    Market,
    OrderSide,
    Position,
    ResearchReport,
    ReviewVerdict,
    SignalSnapshot,
    StrategyProposal,
    TargetPosition,
    TradeSuggestion,
)
from stock_quantification.state import InMemoryStateStore


class DummyStrategy(StrategyDefinition):
    strategy_id = "dummy"
    market = Market.US

    def generate(self, data_provider, universe, as_of, current_weights=None):  # pragma: no cover - not used in this test file
        del data_provider, universe, as_of, current_weights
        return {"signals": [], "factors": []}


class CountingRunner:
    def __init__(self, result):
        self.calls = 0
        self._result = result

    def run(self, strategy, as_of, account_states=None):
        del strategy, as_of, account_states
        self.calls += 1
        return self._result


class PlannerStub:
    def build_trade_suggestions(self, account_states, targets, as_of, source_strategy_id):
        del account_states, as_of, source_strategy_id
        suggestions = []
        for target in targets:
            suggestions.append(
                TradeSuggestion(
                    suggestion_id=f"{target.instrument_id}:suggestion",
                    as_of=target.as_of,
                    account_id="acct-1",
                    instrument_id=target.instrument_id,
                    side=OrderSide.BUY,
                    suggested_qty=20,
                    rationale="stub",
                    source_strategy_id=target.strategy_id,
                    target_qty=100,
                )
            )
        return suggestions

    def build_order_intents(self, trade_suggestions, requires_manual_approval):
        del requires_manual_approval
        return []


class AgentTests(unittest.TestCase):
    def test_strategy_agent_reuses_shared_research_analysis(self) -> None:
        strategy = DummyStrategy()
        runner_result = {
            "signals": [
                SignalSnapshot(
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    strategy_id="dummy",
                    instrument_id="US.AAPL",
                    score=Decimal("0.2100"),
                    direction="LONG",
                    reason="momentum",
                ),
                SignalSnapshot(
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    strategy_id="dummy",
                    instrument_id="US.MSFT",
                    score=Decimal("0.1800"),
                    direction="LONG",
                    reason="profitability",
                ),
            ],
            "factors": [
                FactorSnapshot(
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    instrument_id="US.AAPL",
                    factor_name="momentum",
                    factor_value=Decimal("0.21"),
                )
            ],
        }
        runner = CountingRunner(runner_result)
        research_agent = ResearchAgent(runner)
        analysis = research_agent.analyze(strategy, datetime(2026, 4, 3, 15, 0, 0))

        state_store = InMemoryStateStore()
        state_store.save_account_state(
            AccountState(
                account_id="acct-1",
                market=Market.US,
                broker_id="paper-us",
                cash=Decimal("10000"),
                buying_power=Decimal("10000"),
                constraints=AccountConstraints(max_position_weight=Decimal("0.60"), max_single_order_value=Decimal("10000")),
            )
        )

        strategy_agent = StrategyAgent(
            runner,
            EqualWeightPortfolioConstructor(top_n=2),
            PlannerStub(),
            state_store,
        )
        proposal = strategy_agent.run(strategy, analysis.research_report, datetime(2026, 4, 3, 15, 0, 0), [state_store.get_account_state("acct-1")], analysis=analysis)

        self.assertEqual(runner.calls, 1)
        self.assertEqual([signal.instrument_id for signal in proposal.signals], ["US.AAPL", "US.MSFT"])
        self.assertEqual([factor.factor_name for factor in proposal.factors], ["momentum"])

    def test_review_agent_reports_concentration_turnover_and_drift(self) -> None:
        proposal = StrategyProposal(
            research_report=ResearchReport(
                market=Market.US,
                as_of=datetime(2026, 4, 3, 15, 0, 0),
                highlights=["top_candidates=US.AAPL,US.MSFT"],
                candidate_instruments=["US.AAPL", "US.MSFT"],
            ),
            signals=[
                SignalSnapshot(
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    strategy_id="dummy",
                    instrument_id="US.AAPL",
                    score=Decimal("0.2100"),
                    direction="LONG",
                    reason="momentum",
                ),
                SignalSnapshot(
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    strategy_id="dummy",
                    instrument_id="US.MSFT",
                    score=Decimal("0.1800"),
                    direction="LONG",
                    reason="profitability",
                ),
            ],
            factors=[],
            targets=[
                TargetPosition(
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    strategy_id="dummy",
                    account_scope="US",
                    instrument_id="US.AAPL",
                    target_weight=Decimal("0.5000"),
                    target_qty=100,
                ),
                TargetPosition(
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    strategy_id="dummy",
                    account_scope="US",
                    instrument_id="US.MSFT",
                    target_weight=Decimal("0.5000"),
                    target_qty=100,
                ),
            ],
            trade_suggestions=[
                TradeSuggestion(
                    suggestion_id="US.AAPL:suggestion",
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    account_id="acct-1",
                    instrument_id="US.AAPL",
                    side=OrderSide.BUY,
                    suggested_qty=10,
                    rationale="stub",
                    source_strategy_id="dummy",
                    target_qty=100,
                ),
                TradeSuggestion(
                    suggestion_id="US.MSFT:suggestion",
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    account_id="acct-1",
                    instrument_id="US.MSFT",
                    side=OrderSide.BUY,
                    suggested_qty=20,
                    rationale="stub",
                    source_strategy_id="dummy",
                    target_qty=100,
                ),
            ],
        )

        account_state = AccountState(
            account_id="acct-1",
            market=Market.US,
            broker_id="paper-us",
            cash=Decimal("10000"),
            buying_power=Decimal("10000"),
            positions={
                "US.AAPL": Position("US.AAPL", 80, Decimal("200.00")),
            },
        )

        review = ReviewAgent().run(proposal, [account_state])

        self.assertEqual(review.verdict, ReviewVerdict.PASS)
        self.assertIn("target_hhi=0.5000", review.comments)
        self.assertIn("max_target_weight=0.5000", review.comments)
        self.assertIn("rebalance_qty=30", review.comments)
        self.assertIn("drift_ratio=0.1500", review.comments)
        self.assertIn("account_count=1", review.comments)

    def test_review_agent_warns_on_single_name_concentration(self) -> None:
        proposal = StrategyProposal(
            research_report=ResearchReport(
                market=Market.US,
                as_of=datetime(2026, 4, 3, 15, 0, 0),
                highlights=["top_candidates=US.AAPL"],
                candidate_instruments=["US.AAPL"],
            ),
            signals=[
                SignalSnapshot(
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    strategy_id="dummy",
                    instrument_id="US.AAPL",
                    score=Decimal("0.3000"),
                    direction="LONG",
                    reason="momentum",
                ),
            ],
            factors=[],
            targets=[
                TargetPosition(
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    strategy_id="dummy",
                    account_scope="US",
                    instrument_id="US.AAPL",
                    target_weight=Decimal("1.0000"),
                    target_qty=100,
                ),
            ],
            trade_suggestions=[
                TradeSuggestion(
                    suggestion_id="US.AAPL:suggestion",
                    as_of=datetime(2026, 4, 3, 15, 0, 0),
                    account_id="acct-1",
                    instrument_id="US.AAPL",
                    side=OrderSide.BUY,
                    suggested_qty=100,
                    rationale="stub",
                    source_strategy_id="dummy",
                    target_qty=100,
                ),
            ],
        )

        review = ReviewAgent().run(proposal)
        self.assertEqual(review.verdict, ReviewVerdict.WARN)
        self.assertIn("target_hhi=1.0000", review.comments)
        self.assertIn("max_target_weight=1.0000", review.comments)


if __name__ == "__main__":
    unittest.main()
