from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence

from .interfaces import CalendarProvider, MarketDataProvider
from .models import (
    AccountState,
    Bar,
    Market,
    OrderIntent,
    OrderSide,
    OrderType,
    Position,
    RuntimeContext,
    RuntimeMode,
)


class ExecutionStatus(str, Enum):
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    PENDING_BROKER = "PENDING_BROKER"
    SKIPPED = "SKIPPED"


class CorporateActionType(str, Enum):
    SPLIT = "SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"
    STOCK_DIVIDEND = "STOCK_DIVIDEND"


class PriceAnchor(str, Enum):
    NEXT_BAR_OPEN = "NEXT_BAR_OPEN"
    LAST_BAR_CLOSE = "LAST_BAR_CLOSE"
    LIVE_QUOTE = "LIVE_QUOTE"


@dataclass(frozen=True)
class FeeSchedule:
    commission_bps: Decimal
    minimum_commission: Decimal
    sell_tax_bps: Decimal = Decimal("0")
    fixed_fee: Decimal = Decimal("0")


@dataclass(frozen=True)
class SlippageModel:
    base_bps: Decimal
    volatility_multiplier: Decimal
    size_multiplier: Decimal
    max_bps: Decimal

    def estimate_bps(self, bar: Bar, qty: int) -> Decimal:
        close = bar.close if bar.close != 0 else Decimal("1")
        bar_range_bps = ((bar.high - bar.low).copy_abs() / close) * Decimal("10000")
        volume = max(bar.volume, 1)
        participation = Decimal(qty) / Decimal(volume)
        size_component = participation * self.size_multiplier * Decimal("100")
        slippage = self.base_bps + (bar_range_bps * self.volatility_multiplier) + size_component
        return min(slippage, self.max_bps).quantize(Decimal("0.0001"))


@dataclass(frozen=True)
class RuntimeProfile:
    mode: RuntimeMode
    price_anchor: PriceAnchor
    slippage_model: SlippageModel
    allow_partial_fills: bool
    participation_cap: Decimal
    apply_state_updates: bool
    estimate_only: bool


@dataclass(frozen=True)
class CorporateAction:
    instrument_id: str
    action_type: CorporateActionType
    effective_date: date
    ratio: Decimal = Decimal("1")
    cash_per_share: Decimal = Decimal("0")
    description: str = ""


@dataclass(frozen=True)
class ExecutionFill:
    order_intent_id: str
    account_id: str
    instrument_id: str
    mode: RuntimeMode
    status: ExecutionStatus
    requested_qty: int
    filled_qty: int
    remaining_qty: int
    reference_price: Decimal
    estimated_price: Decimal
    realized_price: Optional[Decimal]
    slippage_bps: Decimal
    commission: Decimal
    taxes: Decimal
    total_fees: Decimal
    cash_delta: Decimal
    estimated_cash_delta: Decimal
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionResult:
    context: RuntimeContext
    input_account_state: AccountState
    output_account_state: AccountState
    fills: List[ExecutionFill]
    applied_corporate_actions: List[CorporateAction]


DEFAULT_RUNTIME_PROFILES: Dict[RuntimeMode, RuntimeProfile] = {
    RuntimeMode.BACKTEST: RuntimeProfile(
        mode=RuntimeMode.BACKTEST,
        price_anchor=PriceAnchor.NEXT_BAR_OPEN,
        slippage_model=SlippageModel(
            base_bps=Decimal("8"),
            volatility_multiplier=Decimal("0.25"),
            size_multiplier=Decimal("30"),
            max_bps=Decimal("80"),
        ),
        allow_partial_fills=True,
        participation_cap=Decimal("0.10"),
        apply_state_updates=True,
        estimate_only=False,
    ),
    RuntimeMode.PAPER: RuntimeProfile(
        mode=RuntimeMode.PAPER,
        price_anchor=PriceAnchor.LAST_BAR_CLOSE,
        slippage_model=SlippageModel(
            base_bps=Decimal("3"),
            volatility_multiplier=Decimal("0.12"),
            size_multiplier=Decimal("12"),
            max_bps=Decimal("25"),
        ),
        allow_partial_fills=False,
        participation_cap=Decimal("1"),
        apply_state_updates=True,
        estimate_only=False,
    ),
    RuntimeMode.LIVE: RuntimeProfile(
        mode=RuntimeMode.LIVE,
        price_anchor=PriceAnchor.LIVE_QUOTE,
        slippage_model=SlippageModel(
            base_bps=Decimal("1"),
            volatility_multiplier=Decimal("0.08"),
            size_multiplier=Decimal("6"),
            max_bps=Decimal("12"),
        ),
        allow_partial_fills=False,
        participation_cap=Decimal("1"),
        apply_state_updates=False,
        estimate_only=True,
    ),
}

DEFAULT_FEE_SCHEDULES: Dict[RuntimeMode, Dict[Market, FeeSchedule]] = {
    RuntimeMode.BACKTEST: {
        Market.CN: FeeSchedule(commission_bps=Decimal("3"), minimum_commission=Decimal("5"), sell_tax_bps=Decimal("5")),
        Market.US: FeeSchedule(commission_bps=Decimal("5"), minimum_commission=Decimal("1")),
    },
    RuntimeMode.PAPER: {
        Market.CN: FeeSchedule(commission_bps=Decimal("2"), minimum_commission=Decimal("5"), sell_tax_bps=Decimal("0")),
        Market.US: FeeSchedule(commission_bps=Decimal("3"), minimum_commission=Decimal("0.35")),
    },
    RuntimeMode.LIVE: {
        Market.CN: FeeSchedule(commission_bps=Decimal("2"), minimum_commission=Decimal("5"), sell_tax_bps=Decimal("0")),
        Market.US: FeeSchedule(commission_bps=Decimal("3"), minimum_commission=Decimal("0.35")),
    },
}


def _clone_account_state(account_state: AccountState) -> AccountState:
    return deepcopy(account_state)


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"))


class RuntimeEngine:
    def __init__(
        self,
        data_provider: MarketDataProvider,
        calendar_provider: Optional[CalendarProvider] = None,
        profiles: Optional[Dict[RuntimeMode, RuntimeProfile]] = None,
        fee_schedules: Optional[Dict[RuntimeMode, Dict[Market, FeeSchedule]]] = None,
    ) -> None:
        self._data_provider = data_provider
        self._calendar_provider = calendar_provider
        self._profiles = profiles or DEFAULT_RUNTIME_PROFILES
        self._fee_schedules = fee_schedules or DEFAULT_FEE_SCHEDULES

    def execute(
        self,
        context: RuntimeContext,
        account_state: AccountState,
        order_intents: Sequence[OrderIntent],
        corporate_actions: Optional[Sequence[CorporateAction]] = None,
    ) -> ExecutionResult:
        if self._calendar_provider is not None and not self._calendar_provider.is_session(account_state.market, context.as_of):
            raise ValueError("context.as_of must be a valid session for %s" % account_state.market.value)

        profile = self._profiles[context.mode]
        fee_schedule = self._fee_schedules[context.mode][account_state.market]
        input_state = _clone_account_state(account_state)
        output_state = _clone_account_state(account_state)
        applied_actions = self._apply_corporate_actions(output_state, corporate_actions or [], context.as_of)

        fills: List[ExecutionFill] = []
        for order_intent in order_intents:
            fills.append(
                self._execute_order(
                    output_state,
                    order_intent,
                    profile,
                    fee_schedule,
                    context,
                )
            )

        return ExecutionResult(
            context=context,
            input_account_state=input_state,
            output_account_state=output_state,
            fills=fills,
            applied_corporate_actions=applied_actions,
        )

    def _execute_order(
        self,
        account_state: AccountState,
        order_intent: OrderIntent,
        profile: RuntimeProfile,
        fee_schedule: FeeSchedule,
        context: RuntimeContext,
    ) -> ExecutionFill:
        bar = self._resolve_bar(order_intent.instrument_id, context.as_of, profile.price_anchor)
        notes: List[str] = []
        if bar is None:
            notes.append("no_price_bar_available")
            return ExecutionFill(
                order_intent_id=order_intent.order_intent_id,
                account_id=order_intent.account_id,
                instrument_id=order_intent.instrument_id,
                mode=context.mode,
                status=ExecutionStatus.SKIPPED,
                requested_qty=order_intent.qty,
                filled_qty=0,
                remaining_qty=order_intent.qty,
                reference_price=Decimal("0"),
                estimated_price=Decimal("0"),
                realized_price=None,
                slippage_bps=Decimal("0"),
                commission=Decimal("0"),
                taxes=Decimal("0"),
                total_fees=Decimal("0"),
                cash_delta=Decimal("0"),
                estimated_cash_delta=Decimal("0"),
                notes=notes,
            )

        reference_price = bar.open if profile.price_anchor == PriceAnchor.NEXT_BAR_OPEN else bar.close
        slippage_bps = profile.slippage_model.estimate_bps(bar, order_intent.qty)
        estimated_price = self._apply_slippage(reference_price, order_intent.side, slippage_bps)

        if order_intent.order_type == OrderType.LIMIT and order_intent.limit_price is not None:
            limit_price = order_intent.limit_price
            if order_intent.side == OrderSide.BUY and estimated_price > limit_price:
                notes.append("limit_price_not_reached")
                return self._skipped_fill(order_intent, context.mode, reference_price, estimated_price, slippage_bps, notes)
            if order_intent.side == OrderSide.SELL and estimated_price < limit_price:
                notes.append("limit_price_not_reached")
                return self._skipped_fill(order_intent, context.mode, reference_price, estimated_price, slippage_bps, notes)

        requested_qty = order_intent.qty
        max_fill_qty = requested_qty
        current_position = account_state.positions.get(order_intent.instrument_id)
        available_qty = current_position.qty if current_position is not None else 0

        if profile.allow_partial_fills:
            volume_cap = int((Decimal(bar.volume) * profile.participation_cap).to_integral_value(rounding=ROUND_DOWN))
            if volume_cap > 0:
                max_fill_qty = min(max_fill_qty, volume_cap)
            else:
                max_fill_qty = 0

        if order_intent.side == OrderSide.SELL and current_position is not None:
            max_fill_qty = min(max_fill_qty, available_qty)
        elif order_intent.side == OrderSide.SELL and current_position is None:
            max_fill_qty = 0

        if max_fill_qty <= 0:
            notes.append("insufficient_liquidity_or_position")
            return self._skipped_fill(order_intent, context.mode, reference_price, estimated_price, slippage_bps, notes)

        if profile.estimate_only:
            status = ExecutionStatus.PENDING_BROKER
            notes.append("live_routed_for_broker_confirmation")
        elif max_fill_qty < requested_qty:
            status = ExecutionStatus.PARTIALLY_FILLED
            notes.append("partial_fill_due_to_liquidity_or_position_constraint")
        else:
            status = ExecutionStatus.FILLED

        filled_qty = max_fill_qty if not profile.estimate_only else 0
        realized_price = None if profile.estimate_only else estimated_price
        commission, taxes = self._calculate_fees(fee_schedule, order_intent.side, estimated_price, filled_qty)
        estimated_commission, estimated_taxes = self._calculate_fees(fee_schedule, order_intent.side, estimated_price, requested_qty)
        total_fees = commission + taxes
        estimated_notional = estimated_price * Decimal(requested_qty)
        cash_delta = Decimal("0")
        estimated_cash_delta = self._estimated_cash_impact(
            order_intent.side,
            estimated_notional,
            estimated_commission + estimated_taxes,
        )

        if profile.apply_state_updates and filled_qty > 0:
            cash_delta = self._apply_fill_to_state(
                account_state,
                order_intent,
                filled_qty,
                realized_price,
                total_fees,
                context.as_of.date(),
            )

        return ExecutionFill(
            order_intent_id=order_intent.order_intent_id,
            account_id=order_intent.account_id,
            instrument_id=order_intent.instrument_id,
            mode=context.mode,
            status=status,
            requested_qty=requested_qty,
            filled_qty=filled_qty,
            remaining_qty=requested_qty - filled_qty,
            reference_price=_quantize_money(reference_price),
            estimated_price=_quantize_money(estimated_price),
            realized_price=_quantize_money(realized_price) if realized_price is not None else None,
            slippage_bps=slippage_bps,
            commission=_quantize_money(commission),
            taxes=_quantize_money(taxes),
            total_fees=_quantize_money(total_fees),
            cash_delta=_quantize_money(cash_delta),
            estimated_cash_delta=_quantize_money(estimated_cash_delta),
            notes=notes,
        )

    def _resolve_bar(self, instrument_id: str, as_of: datetime, price_anchor: PriceAnchor) -> Optional[Bar]:
        if price_anchor == PriceAnchor.NEXT_BAR_OPEN:
            next_bar = self._data_provider.get_next_bar(instrument_id, as_of)
            if next_bar is not None:
                return next_bar
        return self._data_provider.get_latest_bar(instrument_id, as_of)

    def _apply_slippage(self, price: Decimal, side: OrderSide, slippage_bps: Decimal) -> Decimal:
        ratio = slippage_bps / Decimal("10000")
        if side == OrderSide.BUY:
            return price * (Decimal("1") + ratio)
        return price * (Decimal("1") - ratio)

    def _calculate_fees(self, fee_schedule: FeeSchedule, side: OrderSide, price: Decimal, qty: int) -> tuple[Decimal, Decimal]:
        notional = price * Decimal(qty)
        commission = max((notional * fee_schedule.commission_bps) / Decimal("10000"), fee_schedule.minimum_commission)
        taxes = fee_schedule.fixed_fee
        if side == OrderSide.SELL:
            taxes += (notional * fee_schedule.sell_tax_bps) / Decimal("10000")
        return commission, taxes

    def _estimated_cash_impact(self, side: OrderSide, estimated_notional: Decimal, total_fees: Decimal) -> Decimal:
        if side == OrderSide.BUY:
            return -(estimated_notional + total_fees)
        return estimated_notional - total_fees

    def _apply_fill_to_state(
        self,
        account_state: AccountState,
        order_intent: OrderIntent,
        filled_qty: int,
        realized_price: Decimal,
        total_fees: Decimal,
        trade_date: date,
    ) -> Decimal:
        realized_notional = realized_price * Decimal(filled_qty)
        if order_intent.side == OrderSide.BUY:
            cash_delta = -(realized_notional + total_fees)
            account_state.cash += cash_delta
            account_state.buying_power += cash_delta
            self._increase_position(account_state, order_intent.instrument_id, filled_qty, realized_price, trade_date)
            return cash_delta

        cash_delta = realized_notional - total_fees
        account_state.cash += cash_delta
        account_state.buying_power += cash_delta
        self._decrease_position(account_state, order_intent.instrument_id, filled_qty)
        return cash_delta

    def _increase_position(
        self,
        account_state: AccountState,
        instrument_id: str,
        qty: int,
        price: Decimal,
        trade_date: Optional[date],
    ) -> None:
        current = account_state.positions.get(instrument_id)
        if current is None:
            account_state.positions[instrument_id] = Position(
                instrument_id=instrument_id,
                qty=qty,
                avg_cost=price,
                last_trade_date=trade_date,
            )
            return
        new_qty = current.qty + qty
        new_avg = ((current.avg_cost * Decimal(current.qty)) + (price * Decimal(qty))) / Decimal(new_qty)
        account_state.positions[instrument_id] = Position(
            instrument_id=instrument_id,
            qty=new_qty,
            avg_cost=new_avg,
            last_trade_date=trade_date or current.last_trade_date,
        )

    def _decrease_position(self, account_state: AccountState, instrument_id: str, qty: int) -> None:
        current = account_state.positions.get(instrument_id)
        if current is None:
            return
        new_qty = current.qty - qty
        if new_qty <= 0:
            account_state.positions.pop(instrument_id, None)
            return
        account_state.positions[instrument_id] = Position(
            instrument_id=instrument_id,
            qty=new_qty,
            avg_cost=current.avg_cost,
            last_trade_date=current.last_trade_date,
        )

    def _apply_corporate_actions(
        self,
        account_state: AccountState,
        actions: Sequence[CorporateAction],
        as_of: datetime,
    ) -> List[CorporateAction]:
        applied: List[CorporateAction] = []
        for action in sorted(actions, key=lambda item: item.effective_date):
            if action.effective_date > as_of.date():
                continue
            position = account_state.positions.get(action.instrument_id)
            if position is None:
                continue

            if action.action_type == CorporateActionType.SPLIT:
                ratio = action.ratio
                if ratio <= 0:
                    continue
                new_qty = int((Decimal(position.qty) * ratio).to_integral_value(rounding=ROUND_DOWN))
                new_avg_cost = position.avg_cost / ratio
                account_state.positions[action.instrument_id] = Position(
                    instrument_id=position.instrument_id,
                    qty=new_qty,
                    avg_cost=new_avg_cost,
                    last_trade_date=position.last_trade_date,
                )
                applied.append(action)
                continue

            if action.action_type == CorporateActionType.CASH_DIVIDEND:
                cash_amount = Decimal(position.qty) * action.cash_per_share
                account_state.cash += cash_amount
                account_state.buying_power += cash_amount
                applied.append(action)
                continue

            if action.action_type == CorporateActionType.STOCK_DIVIDEND:
                bonus_ratio = action.ratio
                if bonus_ratio <= 0:
                    continue
                bonus_qty = int((Decimal(position.qty) * bonus_ratio).to_integral_value(rounding=ROUND_DOWN))
                new_qty = position.qty + bonus_qty
                if new_qty <= 0:
                    continue
                new_avg_cost = position.avg_cost / (Decimal("1") + bonus_ratio)
                account_state.positions[action.instrument_id] = Position(
                    instrument_id=position.instrument_id,
                    qty=new_qty,
                    avg_cost=new_avg_cost,
                    last_trade_date=position.last_trade_date,
                )
                applied.append(action)
        return applied

    def _skipped_fill(
        self,
        order_intent: OrderIntent,
        mode: RuntimeMode,
        reference_price: Decimal,
        estimated_price: Decimal,
        slippage_bps: Decimal,
        notes: List[str],
    ) -> ExecutionFill:
        return ExecutionFill(
            order_intent_id=order_intent.order_intent_id,
            account_id=order_intent.account_id,
            instrument_id=order_intent.instrument_id,
            mode=mode,
            status=ExecutionStatus.SKIPPED,
            requested_qty=order_intent.qty,
            filled_qty=0,
            remaining_qty=order_intent.qty,
            reference_price=_quantize_money(reference_price),
            estimated_price=_quantize_money(estimated_price),
            realized_price=None,
            slippage_bps=slippage_bps,
            commission=Decimal("0"),
            taxes=Decimal("0"),
            total_fees=Decimal("0"),
            cash_delta=Decimal("0"),
            estimated_cash_delta=Decimal("0"),
            notes=notes,
        )
