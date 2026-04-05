from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from .agents import Orchestrator, ResearchAgent, ReviewAgent, StrategyAgent
from .engine import (
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
from .markets import ChinaMarketRules, USMarketRules
from .models import (
    AccountConstraints,
    AccountState,
    AssetType,
    Bar,
    ExecutionMode,
    Instrument,
    LiveContext,
    Market,
    Position,
)
from .state import InMemoryStateStore


def build_demo_components():
    as_of = datetime(2026, 4, 3, 16, 0, 0)
    instruments = [
        Instrument("CN.600000", Market.CN, "600000", AssetType.COMMON_STOCK, "CNY", "SSE", attributes={"listed_days": 600, "is_st": False}),
        Instrument("CN.000001", Market.CN, "000001", AssetType.COMMON_STOCK, "CNY", "SZSE", attributes={"listed_days": 1000, "is_st": False}),
        Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ", attributes={"profitability": "0.8"}),
        Instrument("US.MSFT", Market.US, "MSFT", AssetType.COMMON_STOCK, "USD", "NASDAQ", attributes={"profitability": "0.9"}),
    ]
    bars = {
        "CN.600000": [
            Bar("CN.600000", datetime(2026, 4, 2, 15, 0, 0), Decimal("10"), Decimal("10.5"), Decimal("9.8"), Decimal("10"), 1000000, Decimal("800000000")),
            Bar("CN.600000", as_of, Decimal("10"), Decimal("10.8"), Decimal("10"), Decimal("10.6"), 1200000, Decimal("1000000000")),
        ],
        "CN.000001": [
            Bar("CN.000001", datetime(2026, 4, 2, 15, 0, 0), Decimal("8"), Decimal("8.1"), Decimal("7.8"), Decimal("8"), 900000, Decimal("600000000")),
            Bar("CN.000001", as_of, Decimal("8"), Decimal("8.5"), Decimal("7.9"), Decimal("8.2"), 1100000, Decimal("700000000")),
        ],
        "US.AAPL": [
            Bar("US.AAPL", datetime(2026, 4, 2, 16, 0, 0), Decimal("180"), Decimal("182"), Decimal("179"), Decimal("180"), 1000000, Decimal("1500000000")),
            Bar("US.AAPL", as_of, Decimal("180"), Decimal("186"), Decimal("180"), Decimal("185"), 1200000, Decimal("1800000000")),
        ],
        "US.MSFT": [
            Bar("US.MSFT", datetime(2026, 4, 2, 16, 0, 0), Decimal("300"), Decimal("305"), Decimal("299"), Decimal("300"), 900000, Decimal("1400000000")),
            Bar("US.MSFT", as_of, Decimal("300"), Decimal("309"), Decimal("300"), Decimal("308"), 1000000, Decimal("1700000000")),
        ],
    }
    data_provider = InMemoryMarketDataProvider(instruments, bars)
    calendar_provider = InMemoryCalendarProvider(
        {
            Market.CN: [as_of],
            Market.US: [as_of],
        }
    )
    universe_provider = InMemoryUniverseProvider(data_provider)
    strategy_runner = StandardStrategyRunner(data_provider, universe_provider, calendar_provider)
    portfolio_constructor = EqualWeightPortfolioConstructor(top_n=2)
    execution_planner = StandardExecutionPlanner(data_provider)
    risk_engine = StandardRiskEngine(data_provider, {Market.CN: ChinaMarketRules(), Market.US: USMarketRules()})
    state_store = InMemoryStateStore()
    state_store.save_account_state(
        AccountState(
            account_id="cn-main",
            market=Market.CN,
            broker_id="demo-cn",
            cash=Decimal("200000"),
            buying_power=Decimal("200000"),
            positions={"CN.600000": Position("CN.600000", 1000, Decimal("9.5"), last_trade_date=date(2026, 4, 1))},
            constraints=AccountConstraints(max_position_weight=Decimal("0.60"), max_single_order_value=Decimal("500000")),
        )
    )
    state_store.save_account_state(
        AccountState(
            account_id="us-main",
            market=Market.US,
            broker_id="demo-us",
            cash=Decimal("50000"),
            buying_power=Decimal("50000"),
            constraints=AccountConstraints(max_position_weight=Decimal("0.60"), max_single_order_value=Decimal("500000")),
        )
    )
    orchestrator = Orchestrator(
        research_agent=ResearchAgent(strategy_runner),
        strategy_agent=StrategyAgent(strategy_runner, portfolio_constructor, execution_planner, state_store),
        review_agent=ReviewAgent(),
        execution_planner=execution_planner,
        risk_engine=risk_engine,
        state_store=state_store,
    )
    return orchestrator, as_of


if __name__ == "__main__":
    orchestrator, as_of = build_demo_components()
    for strategy, accounts in [
        (AStockSelectionStrategy(), ["cn-main"]),
        (USStockSelectionStrategy(), ["us-main"]),
    ]:
        result = orchestrator.run(LiveContext(as_of=as_of), strategy, accounts, ExecutionMode.ADVISORY)
        print(strategy.strategy_id, [signal.instrument_id for signal in result.proposal.signals], len(result.order_intents))
