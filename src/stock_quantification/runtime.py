from __future__ import annotations

from abc import ABC, abstractmethod
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


class CorporateActionSource(ABC):
    @abstractmethod
    def get_actions(self, account_state: AccountState, context: RuntimeContext) -> Sequence["CorporateAction"]:
        raise NotImplementedError


@dataclass(frozen=True)
class FeeSchedule:
    commission_bps: Decimal
    minimum_commission: Decimal
    buy_tax_bps: Decimal = Decimal("0")
    sell_tax_bps: Decimal = Decimal("0")
    buy_per_share_fee: Decimal = Decimal("0")
    sell_per_share_fee: Decimal = Decimal("0")
    fixed_fee: Decimal = Decimal("0")

    def estimate(self, side: OrderSide, price: Decimal, qty: int) -> tuple[Decimal, Decimal]:
        notional = price * Decimal(qty)
        commission = max((notional * self.commission_bps) / Decimal("10000"), self.minimum_commission)
        taxes = self.fixed_fee
        taxes += Decimal(qty) * (self.buy_per_share_fee if side == OrderSide.BUY else self.sell_per_share_fee)
        taxes += (notional * (self.buy_tax_bps if side == OrderSide.BUY else self.sell_tax_bps)) / Decimal("10000")
        return commission, taxes


@dataclass(frozen=True)
class SlippageModel:
    buy_base_bps: Decimal
    sell_base_bps: Decimal
    volatility_multiplier: Decimal
    participation_multiplier: Decimal
    low_volume_floor: int
    low_volume_penalty_bps: Decimal
    max_bps: Decimal

    def estimate_bps(self, bar: Bar, qty: int, side: OrderSide) -> Decimal:
        close = bar.close if bar.close != 0 else Decimal("1")
        bar_range_bps = ((bar.high - bar.low).copy_abs() / close) * Decimal("10000")
        volume = max(bar.volume, 1)
        participation = Decimal(qty) / Decimal(volume)
        direction_bias = self.buy_base_bps if side == OrderSide.BUY else self.sell_base_bps
        participation_component = participation * self.participation_multiplier * Decimal("100")
        low_volume_component = Decimal("0")
        if bar.volume < self.low_volume_floor:
            shortfall_ratio = Decimal(self.low_volume_floor - bar.volume) / Decimal(self.low_volume_floor)
            low_volume_component = shortfall_ratio * self.low_volume_penalty_bps
        slippage = direction_bias + (bar_range_bps * self.volatility_multiplier) + participation_component + low_volume_component
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
class MarketExecutionProfile:
    slippage_model: SlippageModel
    fee_schedule: FeeSchedule
    allow_partial_fills: bool
    participation_cap: Decimal


@dataclass(frozen=True)
class ExecutionQuote:
    order_intent_id: str
    account_id: str
    instrument_id: str
    mode: RuntimeMode
    status: ExecutionStatus
    requested_qty: int
    fillable_qty: int
    reference_price: Decimal
    estimated_price: Decimal
    slippage_bps: Decimal
    commission: Decimal
    taxes: Decimal
    total_fees: Decimal
    estimated_cash_delta: Decimal
    notes: List[str] = field(default_factory=list)


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
            buy_base_bps=Decimal("8"),
            sell_base_bps=Decimal("10"),
            volatility_multiplier=Decimal("0.25"),
            participation_multiplier=Decimal("30"),
            low_volume_floor=5000,
            low_volume_penalty_bps=Decimal("8"),
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
            buy_base_bps=Decimal("3"),
            sell_base_bps=Decimal("4"),
            volatility_multiplier=Decimal("0.12"),
            participation_multiplier=Decimal("12"),
            low_volume_floor=3000,
            low_volume_penalty_bps=Decimal("4"),
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
            buy_base_bps=Decimal("1"),
            sell_base_bps=Decimal("2"),
            volatility_multiplier=Decimal("0.08"),
            participation_multiplier=Decimal("6"),
            low_volume_floor=3000,
            low_volume_penalty_bps=Decimal("3"),
            max_bps=Decimal("12"),
        ),
        allow_partial_fills=False,
        participation_cap=Decimal("1"),
        apply_state_updates=False,
        estimate_only=True,
    ),
}

DEFAULT_EXECUTION_PROFILES: Dict[RuntimeMode, Dict[Market, MarketExecutionProfile]] = {
    RuntimeMode.BACKTEST: {
        Market.CN: MarketExecutionProfile(
            slippage_model=SlippageModel(
                buy_base_bps=Decimal("9"),
                sell_base_bps=Decimal("11"),
                volatility_multiplier=Decimal("0.25"),
                participation_multiplier=Decimal("32"),
                low_volume_floor=5000,
                low_volume_penalty_bps=Decimal("10"),
                max_bps=Decimal("80"),
            ),
            fee_schedule=FeeSchedule(
                commission_bps=Decimal("3"),
                minimum_commission=Decimal("5"),
                sell_tax_bps=Decimal("10"),
            ),
            allow_partial_fills=True,
            participation_cap=Decimal("0.10"),
        ),
        Market.US: MarketExecutionProfile(
            slippage_model=SlippageModel(
                buy_base_bps=Decimal("4"),
                sell_base_bps=Decimal("6"),
                volatility_multiplier=Decimal("0.12"),
                participation_multiplier=Decimal("18"),
                low_volume_floor=10000,
                low_volume_penalty_bps=Decimal("6"),
                max_bps=Decimal("25"),
            ),
            fee_schedule=FeeSchedule(
                commission_bps=Decimal("1"),
                minimum_commission=Decimal("1"),
                sell_per_share_fee=Decimal("0.0008"),
            ),
            allow_partial_fills=True,
            participation_cap=Decimal("0.20"),
        ),
    },
    RuntimeMode.PAPER: {
        Market.CN: MarketExecutionProfile(
            slippage_model=SlippageModel(
                buy_base_bps=Decimal("5"),
                sell_base_bps=Decimal("7"),
                volatility_multiplier=Decimal("0.12"),
                participation_multiplier=Decimal("20"),
                low_volume_floor=3000,
                low_volume_penalty_bps=Decimal("6"),
                max_bps=Decimal("25"),
            ),
            fee_schedule=FeeSchedule(
                commission_bps=Decimal("2"),
                minimum_commission=Decimal("5"),
                sell_tax_bps=Decimal("10"),
            ),
            allow_partial_fills=False,
            participation_cap=Decimal("1"),
        ),
        Market.US: MarketExecutionProfile(
            slippage_model=SlippageModel(
                buy_base_bps=Decimal("2"),
                sell_base_bps=Decimal("3"),
                volatility_multiplier=Decimal("0.08"),
                participation_multiplier=Decimal("10"),
                low_volume_floor=8000,
                low_volume_penalty_bps=Decimal("4"),
                max_bps=Decimal("18"),
            ),
            fee_schedule=FeeSchedule(
                commission_bps=Decimal("1"),
                minimum_commission=Decimal("0.35"),
                sell_per_share_fee=Decimal("0.0005"),
            ),
            allow_partial_fills=False,
            participation_cap=Decimal("1"),
        ),
    },
    RuntimeMode.LIVE: {
        Market.CN: MarketExecutionProfile(
            slippage_model=SlippageModel(
                buy_base_bps=Decimal("3"),
                sell_base_bps=Decimal("4"),
                volatility_multiplier=Decimal("0.08"),
                participation_multiplier=Decimal("12"),
                low_volume_floor=3000,
                low_volume_penalty_bps=Decimal("5"),
                max_bps=Decimal("12"),
            ),
            fee_schedule=FeeSchedule(
                commission_bps=Decimal("2"),
                minimum_commission=Decimal("5"),
                sell_tax_bps=Decimal("10"),
            ),
            allow_partial_fills=False,
            participation_cap=Decimal("1"),
        ),
        Market.US: MarketExecutionProfile(
            slippage_model=SlippageModel(
                buy_base_bps=Decimal("1"),
                sell_base_bps=Decimal("2"),
                volatility_multiplier=Decimal("0.05"),
                participation_multiplier=Decimal("6"),
                low_volume_floor=8000,
                low_volume_penalty_bps=Decimal("3"),
                max_bps=Decimal("10"),
            ),
            fee_schedule=FeeSchedule(
                commission_bps=Decimal("1"),
                minimum_commission=Decimal("0.35"),
                sell_per_share_fee=Decimal("0.0005"),
            ),
            allow_partial_fills=False,
            participation_cap=Decimal("1"),
        ),
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
        execution_profiles: Optional[Dict[RuntimeMode, Dict[Market, MarketExecutionProfile]]] = None,
    ) -> None:
        self._data_provider = data_provider
        self._calendar_provider = calendar_provider
        self._profiles = profiles or DEFAULT_RUNTIME_PROFILES
        self._execution_profiles = execution_profiles or DEFAULT_EXECUTION_PROFILES

    def execute(
        self,
        context: RuntimeContext,
        account_state: AccountState,
        order_intents: Sequence[OrderIntent],
        corporate_actions: Optional[Sequence[CorporateAction]] = None,
        corporate_action_source: Optional["CorporateActionSource"] = None,
    ) -> ExecutionResult:
        if self._calendar_provider is not None and not self._calendar_provider.is_session(account_state.market, context.as_of):
            raise ValueError("context.as_of must be a valid session for %s" % account_state.market.value)

        profile = self._profiles[context.mode]
        execution_profile = self._execution_profiles[context.mode][account_state.market]
        input_state = _clone_account_state(account_state)
        output_state = _clone_account_state(account_state)
        resolved_actions = self.resolve_corporate_actions(
            account_state=output_state,
            context=context,
            corporate_action_source=corporate_action_source,
            corporate_actions=corporate_actions,
        )
        applied_actions = self._apply_corporate_actions(output_state, resolved_actions, context.as_of)

        fills: List[ExecutionFill] = []
        for order_intent in order_intents:
            fills.append(self._execute_order(output_state, order_intent, profile, execution_profile, context))

        return ExecutionResult(
            context=context,
            input_account_state=input_state,
            output_account_state=output_state,
            fills=fills,
            applied_corporate_actions=applied_actions,
        )

    def resolve_corporate_actions(
        self,
        account_state: AccountState,
        context: RuntimeContext,
        corporate_action_source: Optional["CorporateActionSource"] = None,
        corporate_actions: Optional[Sequence[CorporateAction]] = None,
    ) -> List[CorporateAction]:
        resolved: List[CorporateAction] = []
        if corporate_action_source is not None:
            resolved.extend(corporate_action_source.get_actions(account_state, context))
        if corporate_actions is not None:
            resolved.extend(list(corporate_actions))
        return resolved

    def quote_order(
        self,
        context: RuntimeContext,
        account_state: AccountState,
        order_intent: OrderIntent,
    ) -> ExecutionQuote:
        profile = self._profiles[context.mode]
        execution_profile = self._execution_profiles[context.mode][account_state.market]
        bar = self._resolve_bar(order_intent.instrument_id, context.as_of, profile.price_anchor)
        notes: List[str] = []
        if bar is None:
            notes.append("no_price_bar_available")
            return self._skipped_quote(order_intent, context.mode, notes)

        reference_price = bar.open if profile.price_anchor == PriceAnchor.NEXT_BAR_OPEN else bar.close
        slippage_bps = execution_profile.slippage_model.estimate_bps(bar, order_intent.qty, order_intent.side)
        estimated_price = self._apply_slippage(reference_price, order_intent.side, slippage_bps)

        if order_intent.order_type == OrderType.LIMIT and order_intent.limit_price is not None:
            limit_price = order_intent.limit_price
            if order_intent.side == OrderSide.BUY and estimated_price > limit_price:
                notes.append("limit_price_not_reached")
                return self._skipped_quote(order_intent, context.mode, notes, reference_price, estimated_price, slippage_bps)
            if order_intent.side == OrderSide.SELL and estimated_price < limit_price:
                notes.append("limit_price_not_reached")
                return self._skipped_quote(order_intent, context.mode, notes, reference_price, estimated_price, slippage_bps)

        fillable_qty = self._determine_fillable_qty(account_state, order_intent, estimated_price, execution_profile, bar)
        if fillable_qty <= 0:
            notes.append("insufficient_liquidity_or_position_or_cash")
            return self._skipped_quote(order_intent, context.mode, notes, reference_price, estimated_price, slippage_bps)

        if not execution_profile.allow_partial_fills and fillable_qty < order_intent.qty:
            notes.append("partial_fill_not_allowed")
            return self._skipped_quote(order_intent, context.mode, notes, reference_price, estimated_price, slippage_bps)

        commission, taxes = execution_profile.fee_schedule.estimate(order_intent.side, estimated_price, fillable_qty)
        total_fees = commission + taxes
        estimated_cash_delta = self._estimated_cash_impact(order_intent.side, estimated_price * Decimal(fillable_qty), total_fees)
        status = ExecutionStatus.FILLED if fillable_qty >= order_intent.qty else ExecutionStatus.PARTIALLY_FILLED
        return ExecutionQuote(
            order_intent_id=order_intent.order_intent_id,
            account_id=order_intent.account_id,
            instrument_id=order_intent.instrument_id,
            mode=context.mode,
            status=status,
            requested_qty=order_intent.qty,
            fillable_qty=fillable_qty,
            reference_price=_quantize_money(reference_price),
            estimated_price=_quantize_money(estimated_price),
            slippage_bps=slippage_bps,
            commission=_quantize_money(commission),
            taxes=_quantize_money(taxes),
            total_fees=_quantize_money(total_fees),
            estimated_cash_delta=_quantize_money(estimated_cash_delta),
            notes=notes,
        )

    def _execute_order(
        self,
        account_state: AccountState,
        order_intent: OrderIntent,
        profile: RuntimeProfile,
        execution_profile: MarketExecutionProfile,
        context: RuntimeContext,
    ) -> ExecutionFill:
        quote = self.quote_order(context, account_state, order_intent)
        if quote.status == ExecutionStatus.SKIPPED:
            return self._skipped_fill(
                order_intent,
                context.mode,
                quote.reference_price,
                quote.estimated_price,
                quote.slippage_bps,
                quote.notes,
            )

        requested_qty = order_intent.qty
        filled_qty = 0 if profile.estimate_only else quote.fillable_qty
        status = ExecutionStatus.PENDING_BROKER if profile.estimate_only else quote.status
        if not profile.estimate_only and 0 < filled_qty < requested_qty:
            status = ExecutionStatus.PARTIALLY_FILLED
        if not profile.estimate_only and filled_qty >= requested_qty:
            status = ExecutionStatus.FILLED

        realized_price = None if profile.estimate_only else quote.estimated_price
        commission, taxes = execution_profile.fee_schedule.estimate(order_intent.side, quote.estimated_price, filled_qty)
        total_fees = commission + taxes
        cash_delta = Decimal("0")

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
            reference_price=quote.reference_price,
            estimated_price=quote.estimated_price,
            realized_price=_quantize_money(realized_price) if realized_price is not None else None,
            slippage_bps=quote.slippage_bps,
            commission=_quantize_money(commission),
            taxes=_quantize_money(taxes),
            total_fees=_quantize_money(total_fees),
            cash_delta=_quantize_money(cash_delta),
            estimated_cash_delta=quote.estimated_cash_delta,
            notes=quote.notes + (["live_routed_for_broker_confirmation"] if profile.estimate_only else []),
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

    def _determine_fillable_qty(
        self,
        account_state: AccountState,
        order_intent: OrderIntent,
        estimated_price: Decimal,
        execution_profile: MarketExecutionProfile,
        bar: Bar,
    ) -> int:
        requested_qty = order_intent.qty
        fillable_qty = requested_qty
        current_position = account_state.positions.get(order_intent.instrument_id)
        available_qty = current_position.qty if current_position is not None else 0

        volume_cap = int((Decimal(bar.volume) * execution_profile.participation_cap).to_integral_value(rounding=ROUND_DOWN))
        if volume_cap > 0:
            fillable_qty = min(fillable_qty, volume_cap)
        else:
            fillable_qty = 0

        if order_intent.side == OrderSide.SELL:
            if current_position is None:
                return 0
            fillable_qty = min(fillable_qty, available_qty)
        else:
            if estimated_price <= 0:
                return 0
            affordable_qty = int((account_state.buying_power / estimated_price).to_integral_value(rounding=ROUND_DOWN))
            fillable_qty = min(fillable_qty, affordable_qty)

        return fillable_qty

    def _skipped_quote(
        self,
        order_intent: OrderIntent,
        mode: RuntimeMode,
        notes: List[str],
        reference_price: Decimal = Decimal("0"),
        estimated_price: Decimal = Decimal("0"),
        slippage_bps: Decimal = Decimal("0"),
    ) -> ExecutionQuote:
        return ExecutionQuote(
            order_intent_id=order_intent.order_intent_id,
            account_id=order_intent.account_id,
            instrument_id=order_intent.instrument_id,
            mode=mode,
            status=ExecutionStatus.SKIPPED,
            requested_qty=order_intent.qty,
            fillable_qty=0,
            reference_price=_quantize_money(reference_price),
            estimated_price=_quantize_money(estimated_price),
            slippage_bps=slippage_bps,
            commission=Decimal("0"),
            taxes=Decimal("0"),
            total_fees=Decimal("0"),
            estimated_cash_delta=Decimal("0"),
            notes=notes,
        )

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
