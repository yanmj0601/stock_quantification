from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Market(str, Enum):
    US = "US"
    CN = "CN"
    CRYPTO = "CRYPTO"


class StrategyStatus(str, Enum):
    RESEARCH = "research"
    CANDIDATE = "candidate"
    PAPER = "paper"
    SMALL_LIVE_READY = "small-live-ready"
    PRODUCTION_READY = "production-ready"
    RETIRED = "retired"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskMode(str, Enum):
    RESEARCH_ONLY = "research-only"
    PAPER_ONLY = "paper-only"
    PAUSED = "paused"


class SignalSide(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class OrderDraftStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    SUBMITTED = "submitted"
    BLOCKED = "blocked"


class TimeFrame(str, Enum):
    DAILY = "1d"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: Market
    asset_class: str
    currency: str
    exchange: str
    lot_size: int
    tradable: bool


@dataclass(frozen=True)
class Bar:
    symbol: str
    market: Market
    session: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjusted: bool
    source: str


@dataclass(frozen=True)
class StrategyCandidate:
    id: str
    name: str
    market: Market
    asset_class: str
    template_id: str
    parameters: Mapping[str, Any]
    status: StrategyStatus = StrategyStatus.RESEARCH
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
