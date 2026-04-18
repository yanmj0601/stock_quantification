from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional


class Market(str, Enum):
    CN = "CN"
    US = "US"


class AssetType(str, Enum):
    COMMON_STOCK = "COMMON_STOCK"
    ETF = "ETF"
    ADR = "ADR"


class InstrumentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"


class ExecutionMode(str, Enum):
    ADVISORY = "ADVISORY"
    AUTO = "AUTO"


class RuntimeMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    market: Market
    symbol: str
    asset_type: AssetType
    currency: str
    exchange: str
    status: InstrumentStatus = InstrumentStatus.ACTIVE
    attributes: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Bar:
    instrument_id: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal
    adjustment_flag: str = "ADJ_CLOSE"
    extras: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FactorSnapshot:
    as_of: datetime
    instrument_id: str
    factor_name: str
    factor_value: Decimal


@dataclass(frozen=True)
class SignalSnapshot:
    as_of: datetime
    strategy_id: str
    instrument_id: str
    score: Decimal
    direction: str
    reason: str


@dataclass(frozen=True)
class TargetPosition:
    as_of: datetime
    strategy_id: str
    account_scope: str
    instrument_id: str
    target_weight: Decimal
    target_qty: int = 0


@dataclass(frozen=True)
class TradeSuggestion:
    suggestion_id: str
    as_of: datetime
    account_id: str
    instrument_id: str
    side: OrderSide
    suggested_qty: int
    rationale: str
    source_strategy_id: str
    target_qty: int


@dataclass(frozen=True)
class OrderIntent:
    order_intent_id: str
    account_id: str
    instrument_id: str
    side: OrderSide
    qty: int
    order_type: OrderType
    limit_price: Optional[Decimal]
    time_in_force: str
    source_strategy_id: str
    requires_manual_approval: bool


@dataclass(frozen=True)
class RiskCheckResult:
    account_id: str
    order_intent_id: str
    passed: bool
    violations: List[str]


@dataclass(frozen=True)
class BrokerOrder:
    broker_order_id: str
    account_id: str
    order_intent_id: str
    instrument_id: str
    side: str
    requested_qty: int
    status: str
    submitted_at: datetime
    filled_qty: int
    avg_fill_price: Optional[Decimal]


@dataclass(frozen=True)
class Position:
    instrument_id: str
    qty: int
    avg_cost: Decimal
    last_trade_date: Optional[date] = None


@dataclass(frozen=True)
class AccountConstraints:
    max_position_weight: Decimal = Decimal("0.25")
    max_single_order_value: Decimal = Decimal("50000")
    banned_instruments: List[str] = field(default_factory=list)
    allow_short: bool = False
    allow_extended_hours: bool = False


@dataclass
class AccountState:
    account_id: str
    market: Market
    broker_id: str
    cash: Decimal
    buying_power: Decimal
    positions: Dict[str, Position] = field(default_factory=dict)
    open_orders: List[OrderIntent] = field(default_factory=list)
    last_sync_at: Optional[datetime] = None
    constraints: AccountConstraints = field(default_factory=AccountConstraints)


@dataclass(frozen=True)
class RuntimeContext:
    as_of: datetime
    mode: RuntimeMode


@dataclass(frozen=True, init=False)
class BacktestContext(RuntimeContext):
    def __init__(self, as_of: datetime) -> None:
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "mode", RuntimeMode.BACKTEST)


@dataclass(frozen=True, init=False)
class PaperContext(RuntimeContext):
    def __init__(self, as_of: datetime) -> None:
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "mode", RuntimeMode.PAPER)


@dataclass(frozen=True, init=False)
class LiveContext(RuntimeContext):
    def __init__(self, as_of: datetime) -> None:
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "mode", RuntimeMode.LIVE)


@dataclass(frozen=True)
class ResearchReport:
    market: Market
    as_of: datetime
    highlights: List[str]
    candidate_instruments: List[str]


@dataclass(frozen=True)
class StrategyProposal:
    research_report: ResearchReport
    signals: List[SignalSnapshot]
    factors: List[FactorSnapshot]
    targets: List[TargetPosition]
    trade_suggestions: List[TradeSuggestion]
    portfolio_diagnostics: Dict[str, object] = field(default_factory=dict)
    research_rankings: List[Dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewReport:
    verdict: ReviewVerdict
    comments: List[str]


@dataclass(frozen=True)
class OrchestrationResult:
    context: RuntimeContext
    proposal: StrategyProposal
    review: ReviewReport
    order_intents: List[OrderIntent]
    risk_results: List[RiskCheckResult]
    execution_results: List[object] = field(default_factory=list)
