from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from datetime import date
from decimal import Decimal
from unittest import TestCase

from stock_quantification.engine import InMemoryCalendarProvider, InMemoryMarketDataProvider
from stock_quantification.models import (
    AccountState,
    AssetType,
    BacktestContext,
    Bar,
    Instrument,
    Market,
    OrderIntent,
    OrderSide,
    OrderType,
    PaperContext,
    Position,
)
from stock_quantification.runtime import CorporateAction, CorporateActionSource, CorporateActionType
from stock_quantification.runtime import RuntimeEngine

from test_runtime import RuntimeFixture


class RecordingCorporateActionSource(CorporateActionSource):
    def __init__(self, actions: list[CorporateAction]) -> None:
        self._actions = actions
        self.calls: list[tuple[str, str]] = []

    def get_actions(self, account_state, context):
        self.calls.append((account_state.account_id, context.mode.value))
        return self._actions


class RuntimeBehaviorTests(TestCase):
    def setUp(self) -> None:
        self.fixture = RuntimeFixture()

    def _build_microstructure_fixture(self):
        as_of = datetime(2026, 4, 3, 15, 0, 0)
        next_session = as_of + timedelta(days=3)
        instruments = [
            Instrument("CN.TEST", Market.CN, "TEST", AssetType.COMMON_STOCK, "CNY", "SSE"),
            Instrument("US.TEST", Market.US, "TEST", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
        ]
        bars = {
            "CN.TEST": [
                Bar("CN.TEST", as_of, Decimal("100.00"), Decimal("100.80"), Decimal("99.80"), Decimal("100.00"), 2000, Decimal("200000")),
                Bar("CN.TEST", next_session, Decimal("100.10"), Decimal("100.30"), Decimal("99.90"), Decimal("100.05"), 2000, Decimal("200100")),
            ],
            "US.TEST": [
                Bar("US.TEST", as_of, Decimal("200.00"), Decimal("200.40"), Decimal("199.80"), Decimal("200.00"), 3000, Decimal("600000")),
                Bar("US.TEST", next_session, Decimal("200.20"), Decimal("200.50"), Decimal("199.90"), Decimal("200.10"), 3000, Decimal("600300")),
            ],
        }
        engine = RuntimeEngine(
            InMemoryMarketDataProvider(instruments, bars),
            InMemoryCalendarProvider({Market.CN: [as_of, next_session], Market.US: [as_of, next_session]}),
        )
        cn_account = AccountState(
            account_id="cn-01",
            market=Market.CN,
            broker_id="cn-broker",
            cash=Decimal("50000"),
            buying_power=Decimal("50000"),
            positions={"CN.TEST": Position("CN.TEST", 100, Decimal("98.00"))},
        )
        us_account = AccountState(
            account_id="us-01",
            market=Market.US,
            broker_id="us-broker",
            cash=Decimal("50000"),
            buying_power=Decimal("50000"),
            positions={"US.TEST": Position("US.TEST", 100, Decimal("198.00"))},
        )
        return engine, as_of, cn_account, us_account

    def test_market_and_direction_costs_are_different(self) -> None:
        engine, as_of, cn_account, us_account = self._build_microstructure_fixture()

        cn_buy = engine.quote_order(
            BacktestContext(as_of=self.fixture.as_of),
            cn_account,
            OrderIntent(
                order_intent_id="cn-buy",
                account_id="cn-01",
                instrument_id="CN.TEST",
                side=OrderSide.BUY,
                qty=10,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force="DAY",
                source_strategy_id="strat",
                requires_manual_approval=True,
            ),
        )
        cn_sell = engine.quote_order(
            BacktestContext(as_of=as_of),
            cn_account,
            OrderIntent(
                order_intent_id="cn-sell",
                account_id="cn-01",
                instrument_id="CN.TEST",
                side=OrderSide.SELL,
                qty=10,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force="DAY",
                source_strategy_id="strat",
                requires_manual_approval=True,
            ),
        )
        us_buy = engine.quote_order(
            BacktestContext(as_of=as_of),
            us_account,
            OrderIntent(
                order_intent_id="us-buy",
                account_id="us-01",
                instrument_id="US.TEST",
                side=OrderSide.BUY,
                qty=10,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force="DAY",
                source_strategy_id="strat",
                requires_manual_approval=True,
            ),
        )
        us_sell = engine.quote_order(
            BacktestContext(as_of=as_of),
            us_account,
            OrderIntent(
                order_intent_id="us-sell",
                account_id="us-01",
                instrument_id="US.TEST",
                side=OrderSide.SELL,
                qty=10,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force="DAY",
                source_strategy_id="strat",
                requires_manual_approval=True,
            ),
        )

        self.assertGreater(cn_sell.slippage_bps, cn_buy.slippage_bps)
        self.assertGreater(cn_sell.total_fees, cn_buy.total_fees)
        self.assertGreater(us_sell.total_fees, us_buy.total_fees)
        self.assertGreater(us_sell.slippage_bps, us_buy.slippage_bps)

    def test_slippage_grows_with_participation_in_low_liquidity_conditions(self) -> None:
        engine, as_of, cn_account, _ = self._build_microstructure_fixture()

        small = engine.quote_order(
            PaperContext(as_of=as_of),
            cn_account,
            OrderIntent(
                order_intent_id="small",
                account_id="cn-01",
                instrument_id="CN.TEST",
                side=OrderSide.BUY,
                qty=1,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force="DAY",
                source_strategy_id="strat",
                requires_manual_approval=True,
            ),
        )
        large = engine.quote_order(
            PaperContext(as_of=as_of),
            cn_account,
            OrderIntent(
                order_intent_id="large",
                account_id="cn-01",
                instrument_id="CN.TEST",
                side=OrderSide.BUY,
                qty=5,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force="DAY",
                source_strategy_id="strat",
                requires_manual_approval=True,
            ),
        )

        self.assertGreater(large.slippage_bps, small.slippage_bps)
        self.assertLess(large.estimated_cash_delta, small.estimated_cash_delta)

    def test_corporate_action_source_is_applied_before_order_execution(self) -> None:
        source = RecordingCorporateActionSource(
            [
                CorporateAction(
                    instrument_id="CN.600000",
                    action_type=CorporateActionType.SPLIT,
                    effective_date=date(2026, 4, 3),
                    ratio=Decimal("2"),
                )
            ]
        )
        sell_order = OrderIntent(
            order_intent_id="sell-after-split",
            account_id="cn-01",
            instrument_id="CN.600000",
            side=OrderSide.SELL,
            qty=150,
            order_type=OrderType.MARKET,
            limit_price=None,
            time_in_force="DAY",
            source_strategy_id="strat",
            requires_manual_approval=True,
        )

        result = self.fixture.engine.execute(
            BacktestContext(as_of=self.fixture.as_of),
            self.fixture.cn_account,
            [sell_order],
            corporate_action_source=source,
        )

        self.assertEqual(source.calls, [("cn-01", "BACKTEST")])
        self.assertEqual(result.applied_corporate_actions[0].action_type, CorporateActionType.SPLIT)
        self.assertEqual(result.fills[0].filled_qty, 150)
        self.assertEqual(result.output_account_state.positions["CN.600000"].qty, 50)
