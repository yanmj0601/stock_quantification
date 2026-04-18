from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest import TestCase

from stock_quantification.engine import InMemoryCalendarProvider, InMemoryMarketDataProvider
from stock_quantification.models import (
    AccountState,
    AssetType,
    Bar,
    BacktestContext,
    Instrument,
    LiveContext,
    Market,
    OrderIntent,
    OrderSide,
    OrderType,
    PaperContext,
    Position,
)
from stock_quantification.runtime import (
    CorporateAction,
    CorporateActionType,
    ExecutionStatus,
    RuntimeEngine,
)


class RuntimeFixture:
    def __init__(self) -> None:
        self.as_of = datetime(2026, 4, 3, 15, 0, 0)
        self.next_session = datetime(2026, 4, 6, 15, 0, 0)
        instruments = [
            Instrument("CN.600000", Market.CN, "600000", AssetType.COMMON_STOCK, "CNY", "SSE"),
            Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
        ]
        bars = {
            "CN.600000": [
                Bar("CN.600000", self.as_of, Decimal("10.00"), Decimal("10.20"), Decimal("9.90"), Decimal("10.00"), 1000, Decimal("10000")),
                Bar("CN.600000", self.next_session, Decimal("10.30"), Decimal("10.50"), Decimal("10.20"), Decimal("10.40"), 10000, Decimal("104000")),
            ],
            "US.AAPL": [
                Bar("US.AAPL", self.as_of, Decimal("200.00"), Decimal("201.00"), Decimal("199.00"), Decimal("200.00"), 2000, Decimal("400000")),
                Bar("US.AAPL", self.next_session, Decimal("201.00"), Decimal("204.00"), Decimal("200.00"), Decimal("203.00"), 20000, Decimal("4060000")),
            ],
        }
        self.data_provider = InMemoryMarketDataProvider(instruments, bars)
        self.calendar_provider = InMemoryCalendarProvider({Market.CN: [self.as_of, self.next_session], Market.US: [self.as_of, self.next_session]})
        self.engine = RuntimeEngine(self.data_provider, self.calendar_provider)

        self.cn_account = AccountState(
            account_id="cn-01",
            market=Market.CN,
            broker_id="cn-broker",
            cash=Decimal("50000"),
            buying_power=Decimal("50000"),
            positions={"CN.600000": Position("CN.600000", 100, Decimal("9.50"))},
        )
        self.us_account = AccountState(
            account_id="us-01",
            market=Market.US,
            broker_id="us-broker",
            cash=Decimal("50000"),
            buying_power=Decimal("50000"),
        )


class RuntimeTests(TestCase):
    def setUp(self) -> None:
        self.fixture = RuntimeFixture()

    def test_backtest_uses_next_bar_and_partial_fills(self) -> None:
        order = OrderIntent(
            order_intent_id="cn-01:CN.600000:test",
            account_id="cn-01",
            instrument_id="CN.600000",
            side=OrderSide.BUY,
            qty=1500,
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force="DAY",
            source_strategy_id="strat",
            requires_manual_approval=True,
        )
        result = self.fixture.engine.execute(BacktestContext(as_of=self.fixture.as_of), self.fixture.cn_account, [order])

        fill = result.fills[0]
        self.assertEqual(fill.status, ExecutionStatus.PARTIALLY_FILLED)
        self.assertEqual(fill.filled_qty, 1000)
        self.assertGreater(fill.realized_price, Decimal("10.30"))
        self.assertEqual(fill.cash_delta, fill.estimated_cash_delta)
        self.assertLess(result.output_account_state.cash, self.fixture.cn_account.cash)

    def test_paper_fills_full_at_current_close(self) -> None:
        order = OrderIntent(
            order_intent_id="us-01:US.AAPL:test",
            account_id="us-01",
            instrument_id="US.AAPL",
            side=OrderSide.BUY,
            qty=150,
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force="DAY",
            source_strategy_id="strat",
            requires_manual_approval=True,
        )
        result = self.fixture.engine.execute(PaperContext(as_of=self.fixture.as_of), self.fixture.us_account, [order])

        fill = result.fills[0]
        self.assertEqual(fill.status, ExecutionStatus.FILLED)
        self.assertEqual(fill.filled_qty, 150)
        self.assertEqual(fill.remaining_qty, 0)
        self.assertGreater(fill.realized_price, Decimal("200.0"))
        self.assertEqual(fill.cash_delta, fill.estimated_cash_delta)
        self.assertLess(result.output_account_state.cash, self.fixture.us_account.cash)

    def test_live_only_estimates_and_does_not_mutate_state(self) -> None:
        order = OrderIntent(
            order_intent_id="us-01:US.AAPL:live",
            account_id="us-01",
            instrument_id="US.AAPL",
            side=OrderSide.BUY,
            qty=120,
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force="DAY",
            source_strategy_id="strat",
            requires_manual_approval=False,
        )
        result = self.fixture.engine.execute(LiveContext(as_of=self.fixture.as_of), self.fixture.us_account, [order])

        fill = result.fills[0]
        self.assertEqual(fill.status, ExecutionStatus.PENDING_BROKER)
        self.assertEqual(fill.filled_qty, 0)
        self.assertEqual(fill.cash_delta, Decimal("0"))
        self.assertNotEqual(fill.estimated_cash_delta, Decimal("0"))
        self.assertEqual(result.output_account_state.cash, self.fixture.us_account.cash)
        self.assertEqual(result.output_account_state.positions, self.fixture.us_account.positions)

    def test_corporate_actions_adjust_positions_and_cash(self) -> None:
        actions = [
            CorporateAction(
                instrument_id="CN.600000",
                action_type=CorporateActionType.SPLIT,
                effective_date=self.fixture.as_of.date(),
                ratio=Decimal("2"),
            ),
            CorporateAction(
                instrument_id="CN.600000",
                action_type=CorporateActionType.CASH_DIVIDEND,
                effective_date=self.fixture.as_of.date(),
                cash_per_share=Decimal("1.2"),
            ),
        ]
        result = self.fixture.engine.execute(
            PaperContext(as_of=self.fixture.as_of),
            self.fixture.cn_account,
            [],
            corporate_actions=actions,
        )

        position = result.output_account_state.positions["CN.600000"]
        self.assertEqual(position.qty, 200)
        self.assertEqual(position.avg_cost, Decimal("4.75"))
        self.assertEqual(result.output_account_state.cash, Decimal("50240.0"))
        self.assertEqual(len(result.applied_corporate_actions), 2)
