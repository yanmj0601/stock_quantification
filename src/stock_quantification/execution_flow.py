from __future__ import annotations

from typing import Iterable, Optional

from .agents import ResearchAgent, ReviewAgent, StrategyAgent
from .engine import EqualWeightPortfolioConstructor, StandardExecutionPlanner, StandardRiskEngine, StandardStrategyRunner
from .markets import ChinaMarketRules, USMarketRules
from .models import AccountState, ExecutionMode, OrchestrationResult, RuntimeContext
from .runtime import RuntimeEngine
from .state import InMemoryStateStore


def run_strategy_cycle(
    *,
    strategy,
    context: RuntimeContext,
    account_states: Iterable[AccountState],
    execution_mode: ExecutionMode,
    data_provider,
    universe_provider,
    calendar_provider,
    state_store: Optional[InMemoryStateStore] = None,
    top_n: int = 10,
) -> OrchestrationResult:
    effective_state_store = state_store or InMemoryStateStore()
    normalized_account_states = list(account_states)
    for account_state in normalized_account_states:
        effective_state_store.save_account_state(account_state)

    strategy_runner = StandardStrategyRunner(
        data_provider,
        universe_provider,
        calendar_provider,
    )
    execution_planner = StandardExecutionPlanner(data_provider)
    strategy_agent = StrategyAgent(
        strategy_runner,
        EqualWeightPortfolioConstructor(top_n=top_n),
        execution_planner,
        effective_state_store,
    )
    research_agent = ResearchAgent(strategy_runner)
    review_agent = ReviewAgent()
    risk_engine = StandardRiskEngine(
        data_provider,
        {strategy.market: ChinaMarketRules() if strategy.market.value == "CN" else USMarketRules()},
    )
    runtime_engine = RuntimeEngine(data_provider, calendar_provider)

    analysis = research_agent.analyze(strategy, context.as_of, account_states=normalized_account_states)
    proposal = strategy_agent.run(
        strategy,
        analysis.research_report,
        context.as_of,
        normalized_account_states,
        analysis=analysis,
    )
    review = review_agent.run(proposal, normalized_account_states)
    order_intents = execution_planner.build_order_intents(
        proposal.trade_suggestions,
        requires_manual_approval=execution_mode == ExecutionMode.ADVISORY,
    )
    order_intents = effective_state_store.upsert_order_intents(order_intents)
    risk_output = risk_engine.validate(
        {account_state.account_id: account_state for account_state in normalized_account_states},
        order_intents,
        context,
    )
    execution_results = []
    approved_by_account = {}
    for order_intent in risk_output["order_intents"]:
        approved_by_account.setdefault(order_intent.account_id, []).append(order_intent)
    for account_state in normalized_account_states:
        approved = approved_by_account.get(account_state.account_id, [])
        if not approved:
            continue
        execution_result = runtime_engine.execute(context, account_state, approved)
        execution_results.append(execution_result)
        effective_state_store.save_account_state(execution_result.output_account_state)
    return OrchestrationResult(
        context=context,
        proposal=proposal,
        review=review,
        order_intents=risk_output["order_intents"],
        risk_results=risk_output["risk_results"],
        execution_results=execution_results,
    )
