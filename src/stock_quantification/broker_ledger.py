from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from .models import AccountState, OrderIntent, Position
from .runtime import ExecutionResult


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


class BrokerLedger:
    def mark_nav(
        self,
        account_state: AccountState,
        *,
        price_map: Optional[Mapping[str, Decimal]] = None,
        price_lookup=None,
    ) -> Decimal:
        nav, _ = self.mark_nav_components(
            account_state,
            price_map=price_map,
            price_lookup=price_lookup,
        )
        return nav

    def mark_nav_components(
        self,
        account_state: AccountState,
        *,
        price_map: Optional[Mapping[str, Decimal]] = None,
        price_lookup=None,
    ) -> tuple[Decimal, Decimal]:
        price_map = price_map or {}
        position_value = Decimal("0")
        for position in account_state.positions.values():
            if position.qty == 0:
                continue
            mark_price = self._resolve_mark_price(position, price_map=price_map, price_lookup=price_lookup)
            position_value += Decimal(position.qty) * mark_price
        nav = account_state.cash + position_value
        return nav, position_value

    def nav_snapshot(
        self,
        *,
        account_state: AccountState,
        as_of: datetime,
        trade_date: str,
        starting_cash: Decimal,
        price_map: Optional[Mapping[str, Decimal]] = None,
        price_lookup=None,
    ) -> Dict[str, str]:
        nav, position_value = self.mark_nav_components(
            account_state,
            price_map=price_map,
            price_lookup=price_lookup,
        )
        nav = nav.quantize(Decimal("0.0001"))
        position_value = position_value.quantize(Decimal("0.0001"))
        cumulative_return = Decimal("0")
        if starting_cash != 0:
            cumulative_return = ((nav / starting_cash) - Decimal("1")).quantize(Decimal("0.0001"))
        return {
            "as_of": as_of.isoformat(),
            "trade_date": trade_date,
            "nav": str(nav),
            "cash": str(account_state.cash.quantize(Decimal("0.0001"))),
            "position_value": str(position_value),
            "cumulative_return": str(cumulative_return),
        }

    def execution_trade_records(
        self,
        *,
        account_id: str,
        strategy_id: str,
        market: str,
        order_intents: Iterable[OrderIntent],
        execution_results: Sequence[ExecutionResult],
        instrument_names: Optional[Mapping[str, str]] = None,
    ) -> list[Dict[str, Any]]:
        instrument_names = instrument_names or {}
        order_lookup = {intent.order_intent_id: intent for intent in order_intents if intent.account_id == account_id}
        trade_records: list[Dict[str, Any]] = []
        for result in execution_results:
            if result.output_account_state.account_id != account_id:
                continue
            for fill in result.fills:
                if fill.filled_qty <= 0:
                    continue
                order_intent = order_lookup.get(fill.order_intent_id)
                trade_records.append(
                    {
                        "executed_at": result.context.as_of.isoformat(),
                        "trade_date": result.context.as_of.date().isoformat(),
                        "account_id": account_id,
                        "market": market,
                        "strategy_id": strategy_id,
                        "instrument_id": fill.instrument_id,
                        "name": instrument_names.get(fill.instrument_id, fill.instrument_id),
                        "side": order_intent.side.value if order_intent is not None else "UNKNOWN",
                        "requested_qty": fill.requested_qty,
                        "filled_qty": fill.filled_qty,
                        "estimated_price": str(fill.estimated_price),
                        "realized_price": str(fill.realized_price) if fill.realized_price is not None else None,
                        "cash_delta": str(fill.cash_delta),
                        "status": fill.status.value,
                    }
                )
        return trade_records

    def liquidate_unknown_positions(
        self,
        *,
        account_state: AccountState,
        valid_instrument_ids: Iterable[str],
        as_of: datetime,
        strategy_id: str = "system_unknown_position_cleanup",
    ) -> tuple[AccountState, list[Dict[str, Any]]]:
        next_state = deepcopy(account_state)
        valid_ids = {str(instrument_id) for instrument_id in valid_instrument_ids}
        trade_records: list[Dict[str, Any]] = []
        for instrument_id, position in list(next_state.positions.items()):
            if instrument_id in valid_ids or position.qty <= 0:
                continue
            liquidation_price = position.avg_cost
            cash_delta = (liquidation_price * Decimal(position.qty)).quantize(Decimal("0.0001"))
            next_state.cash = (next_state.cash + cash_delta).quantize(Decimal("0.0001"))
            next_state.buying_power = (next_state.buying_power + cash_delta).quantize(Decimal("0.0001"))
            next_state.positions.pop(instrument_id, None)
            trade_records.append(
                {
                    "executed_at": as_of.isoformat(),
                    "trade_date": as_of.date().isoformat(),
                    "account_id": next_state.account_id,
                    "market": next_state.market.value,
                    "strategy_id": strategy_id,
                    "instrument_id": instrument_id,
                    "name": instrument_id,
                    "side": "SELL",
                    "requested_qty": position.qty,
                    "filled_qty": position.qty,
                    "estimated_price": str(liquidation_price),
                    "realized_price": str(liquidation_price),
                    "cash_delta": str(cash_delta),
                    "status": "FILLED",
                    "note": "unknown_position_auto_liquidation",
                }
            )
        next_state.last_sync_at = as_of
        return next_state, trade_records

    def _resolve_mark_price(
        self,
        position: Position,
        *,
        price_map: Mapping[str, Decimal],
        price_lookup=None,
    ) -> Decimal:
        if position.instrument_id in price_map:
            return _to_decimal(price_map[position.instrument_id])
        if price_lookup is not None:
            return _to_decimal(price_lookup(position.instrument_id))
        return position.avg_cost
