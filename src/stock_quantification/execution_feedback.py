from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Sequence

from .models import Position

_RATE_QUANTIZER = Decimal("0.0001")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_RATE_QUANTIZER, rounding=ROUND_HALF_UP)


def _coerce_qty(value: object) -> int:
    if isinstance(value, Position):
        return value.qty
    if type(value) is int:
        return value
    raise TypeError(f"unsupported quantity value: {value!r}")


def _require_int_qty(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an int")
    return value


def _require_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    raise TypeError(f"{field_name} must be a Decimal")


@dataclass(frozen=True)
class ExecutionAttempt:
    order_intent_id: str
    account_id: str
    instrument_id: str
    requested_qty: int
    filled_qty: int
    slippage_bps: Decimal

    def __post_init__(self) -> None:
        requested_qty = _require_int_qty(self.requested_qty, "requested_qty")
        filled_qty = _require_int_qty(self.filled_qty, "filled_qty")
        _require_decimal(self.slippage_bps, "slippage_bps")
        if requested_qty < 0:
            raise ValueError("requested_qty must be non-negative")
        if filled_qty < 0:
            raise ValueError("filled_qty must be non-negative")
        if filled_qty > requested_qty:
            raise ValueError("filled_qty cannot exceed requested_qty")


@dataclass(frozen=True)
class ReconciliationDifference:
    instrument_id: str
    intended_qty: int
    observed_qty: int
    delta_qty: int


@dataclass(frozen=True)
class ExecutionFeedbackSummary:
    total_attempts: int
    total_requested_qty: int
    total_filled_qty: int
    fill_rate: Decimal
    average_slippage_bps: Decimal
    reconciliation_differences: tuple[ReconciliationDifference, ...]
    health_status: str

    @property
    def mismatch_count(self) -> int:
        return len(self.reconciliation_differences)


def aggregate_fill_rate(attempts: Sequence[ExecutionAttempt]) -> Decimal:
    total_requested = sum(attempt.requested_qty for attempt in attempts)
    total_filled = sum(attempt.filled_qty for attempt in attempts)
    if total_requested <= 0:
        return Decimal("0").quantize(_RATE_QUANTIZER)
    return _quantize(Decimal(total_filled) / Decimal(total_requested))


def average_slippage_bps(attempts: Sequence[ExecutionAttempt]) -> Decimal:
    filled_attempts = [attempt.slippage_bps for attempt in attempts if attempt.filled_qty > 0]
    if not filled_attempts:
        return Decimal("0").quantize(_RATE_QUANTIZER)
    total_slippage = sum(filled_attempts, Decimal("0"))
    return _quantize(total_slippage / Decimal(len(filled_attempts)))


def reconcile_positions(
    intended_positions: Mapping[str, object],
    observed_positions: Mapping[str, object],
) -> tuple[ReconciliationDifference, ...]:
    instruments = sorted(set(intended_positions) | set(observed_positions))
    differences = []
    for instrument_id in instruments:
        intended_raw = intended_positions.get(instrument_id)
        observed_raw = observed_positions.get(instrument_id)
        intended_qty = 0 if intended_raw is None else _coerce_qty(intended_raw)
        observed_qty = 0 if observed_raw is None else _coerce_qty(observed_raw)
        if intended_qty == observed_qty:
            continue
        differences.append(
            ReconciliationDifference(
                instrument_id=instrument_id,
                intended_qty=intended_qty,
                observed_qty=observed_qty,
                delta_qty=observed_qty - intended_qty,
            )
        )
    return tuple(differences)


def summarize_execution_health(
    attempts: Sequence[ExecutionAttempt],
    intended_positions: Mapping[str, object] | None = None,
    observed_positions: Mapping[str, object] | None = None,
) -> ExecutionFeedbackSummary:
    if intended_positions is None:
        intended_positions = {}
    if observed_positions is None:
        observed_positions = {}
    reconciliation_differences = reconcile_positions(intended_positions, observed_positions)
    fill_rate = aggregate_fill_rate(attempts)
    avg_slippage = average_slippage_bps(attempts)

    if reconciliation_differences:
        health_status = "MISMATCH"
    elif not attempts:
        health_status = "NO_ACTIVITY"
    elif fill_rate >= Decimal("0.9000"):
        health_status = "HEALTHY"
    elif fill_rate >= Decimal("0.5000"):
        health_status = "DEGRADED"
    else:
        health_status = "CRITICAL"

    total_requested_qty = sum(attempt.requested_qty for attempt in attempts)
    total_filled_qty = sum(attempt.filled_qty for attempt in attempts)
    return ExecutionFeedbackSummary(
        total_attempts=len(attempts),
        total_requested_qty=total_requested_qty,
        total_filled_qty=total_filled_qty,
        fill_rate=fill_rate,
        average_slippage_bps=avg_slippage,
        reconciliation_differences=reconciliation_differences,
        health_status=health_status,
    )
