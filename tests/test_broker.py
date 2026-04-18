from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from stock_quantification.broker import AlpacaPaperBrokerAdapter, BrokerError, UnsupportedBrokerMarketError, build_broker_adapter
from stock_quantification.models import OrderIntent, OrderSide, OrderType


class BrokerAdapterTests(TestCase):
    def test_sync_account_state_parses_cash_and_positions(self) -> None:
        adapter = AlpacaPaperBrokerAdapter("key", "secret")
        with patch.object(
            adapter,
            "_request_json",
            side_effect=[
                {"cash": "10500.25", "buying_power": "21000.50"},
                [
                    {"symbol": "AAPL", "qty": "12", "avg_entry_price": "198.55"},
                    {"symbol": "MSFT", "qty": "5", "avg_entry_price": "410.10"},
                ],
            ],
        ):
            account_state = adapter.sync_account_state(account_id="alpaca-main")

        self.assertEqual(account_state.account_id, "alpaca-main")
        self.assertEqual(account_state.cash, Decimal("10500.25"))
        self.assertEqual(account_state.buying_power, Decimal("21000.50"))
        self.assertEqual(account_state.positions["US.AAPL"].qty, 12)
        self.assertEqual(account_state.positions["US.MSFT"].avg_cost, Decimal("410.10"))

    def test_submit_orders_maps_response_to_broker_orders(self) -> None:
        adapter = AlpacaPaperBrokerAdapter("key", "secret")
        intents = [
            OrderIntent(
                order_intent_id="acct:US.AAPL:2026-04-05T20:00:00",
                account_id="acct",
                instrument_id="US.AAPL",
                side=OrderSide.BUY,
                qty=10,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force="DAY",
                source_strategy_id="us_multifactor",
                requires_manual_approval=False,
            )
        ]
        with patch.object(
            adapter,
            "_request_json",
            return_value={
                "id": "broker-order-1",
                "status": "accepted",
                "submitted_at": "2026-04-05T12:00:00Z",
                "filled_qty": "0",
                "filled_avg_price": None,
            },
        ) as request_json:
            orders = adapter.submit_orders(intents)

        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].broker_order_id, "broker-order-1")
        self.assertEqual(orders[0].order_intent_id, "acct:US.AAPL:2026-04-05T20:00:00")
        self.assertEqual(orders[0].instrument_id, "US.AAPL")
        self.assertEqual(orders[0].side, "BUY")
        self.assertEqual(orders[0].requested_qty, 10)
        self.assertEqual(orders[0].status, "accepted")
        self.assertEqual(orders[0].submitted_at, datetime.fromisoformat("2026-04-05T12:00:00+00:00"))
        payload = request_json.call_args.args[2]
        self.assertEqual(payload["symbol"], "AAPL")
        self.assertEqual(payload["side"], "buy")
        self.assertEqual(payload["type"], "market")

    def test_submit_orders_rejects_non_us_instruments(self) -> None:
        adapter = AlpacaPaperBrokerAdapter("key", "secret")
        with self.assertRaises(UnsupportedBrokerMarketError):
            adapter.submit_orders(
                [
                    OrderIntent(
                        order_intent_id="acct:CN.600000:2026-04-05T20:00:00",
                        account_id="acct",
                        instrument_id="CN.600000",
                        side=OrderSide.BUY,
                        qty=100,
                        order_type=OrderType.MARKET,
                        limit_price=None,
                        time_in_force="DAY",
                        source_strategy_id="cn_multifactor",
                        requires_manual_approval=False,
                    )
                ]
            )

    def test_build_broker_adapter_requires_known_name(self) -> None:
        with self.assertRaises(BrokerError):
            build_broker_adapter("UNKNOWN")
