from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List

from .interfaces import MarketDataProvider, MarketRules
from .models import AccountState, OrderIntent, OrderSide


class ChinaMarketRules(MarketRules):
    def validate_order_intent(
        self,
        account_state: AccountState,
        order_intent: OrderIntent,
        data_provider: MarketDataProvider,
        as_of: datetime,
    ) -> List[str]:
        violations: List[str] = []
        instrument = data_provider.get_instrument(order_intent.instrument_id)
        bar = data_provider.get_latest_bar(order_intent.instrument_id, as_of)

        if instrument.status.value != "ACTIVE":
            violations.append("instrument_not_active")
        if bool(instrument.attributes.get("is_st")):
            violations.append("st_stock_blocked")
        if bool(bar.extras.get("halted")):
            violations.append("halted_security")
        if order_intent.qty <= 0 or order_intent.qty % 100 != 0:
            violations.append("lot_size_violation")
        if order_intent.side == OrderSide.BUY and bool(bar.extras.get("limit_up")):
            violations.append("limit_up_block")
        if order_intent.side == OrderSide.SELL and bool(bar.extras.get("limit_down")):
            violations.append("limit_down_block")

        position = account_state.positions.get(order_intent.instrument_id)
        if order_intent.side == OrderSide.SELL and position and position.last_trade_date == as_of.date():
            violations.append("t_plus_one_restriction")
        return violations


class USMarketRules(MarketRules):
    def validate_order_intent(
        self,
        account_state: AccountState,
        order_intent: OrderIntent,
        data_provider: MarketDataProvider,
        as_of: datetime,
    ) -> List[str]:
        violations: List[str] = []
        instrument = data_provider.get_instrument(order_intent.instrument_id)
        bar = data_provider.get_latest_bar(order_intent.instrument_id, as_of)

        if instrument.status.value != "ACTIVE":
            violations.append("instrument_not_active")
        if instrument.asset_type.value == "ADR":
            violations.append("adr_blocked")
        if bool(instrument.attributes.get("is_adr")):
            violations.append("adr_blocked")
        if order_intent.qty <= 0:
            violations.append("non_positive_qty")

        if not account_state.constraints.allow_extended_hours:
            if bool(bar.extras.get("extended_hours")):
                violations.append("extended_hours_blocked")

        limit_price = order_intent.limit_price
        if limit_price is not None:
            scaled = (limit_price * Decimal("100")).quantize(Decimal("1"))
            if scaled != limit_price * Decimal("100"):
                violations.append("tick_size_violation")
        return violations
