from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Mapping


DEFAULT_DECIMAL_QUANT = Decimal("0.0001")


def to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def format_decimal(value: Decimal, quant: Decimal = DEFAULT_DECIMAL_QUANT) -> str:
    return str(value.quantize(quant))


def serialize_flat_record(item: object, quant: Decimal = DEFAULT_DECIMAL_QUANT) -> Dict[str, Any]:
    if is_dataclass(item):
        payload = asdict(item)
    elif isinstance(item, Mapping):
        payload = dict(item)
    else:
        raise TypeError("serialize_flat_record expects a dataclass or mapping")
    return {
        key: _serialize_scalar(value, quant)
        for key, value in payload.items()
    }


def _serialize_scalar(value: Any, quant: Decimal) -> Any:
    if isinstance(value, Decimal):
        return format_decimal(value, quant)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
