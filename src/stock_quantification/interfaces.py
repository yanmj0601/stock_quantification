from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence

from .models import (
    AccountState,
    Bar,
    FactorSnapshot,
    Instrument,
    Market,
    OrderIntent,
    ReviewReport,
    RuntimeContext,
    SignalSnapshot,
    StrategyProposal,
    TargetPosition,
    TradeSuggestion,
)


class MarketDataProvider(ABC):
    @abstractmethod
    def get_instrument(self, instrument_id: str) -> Instrument:
        raise NotImplementedError

    @abstractmethod
    def list_instruments(self, market: Market) -> List[Instrument]:
        raise NotImplementedError

    @abstractmethod
    def get_latest_bar(self, instrument_id: str, as_of: datetime) -> Bar:
        raise NotImplementedError

    @abstractmethod
    def get_price_history(self, instrument_id: str, as_of: datetime, limit: int) -> List[Bar]:
        raise NotImplementedError

    @abstractmethod
    def get_next_bar(self, instrument_id: str, after: datetime) -> Optional[Bar]:
        raise NotImplementedError


class CalendarProvider(ABC):
    @abstractmethod
    def is_session(self, market: Market, as_of: datetime) -> bool:
        raise NotImplementedError

    @abstractmethod
    def next_session(self, market: Market, as_of: datetime) -> datetime:
        raise NotImplementedError


class UniverseProvider(ABC):
    @abstractmethod
    def get_universe(self, market: Market, as_of: datetime) -> List[str]:
        raise NotImplementedError


class StrategyDefinition(ABC):
    strategy_id: str
    market: Market

    @abstractmethod
    def generate(
        self,
        data_provider: MarketDataProvider,
        universe: Sequence[str],
        as_of: datetime,
        current_weights: Optional[Dict[str, object]] = None,
    ) -> Dict[str, List]:
        raise NotImplementedError


class StrategyRunner(ABC):
    @abstractmethod
    def run(
        self,
        strategy: StrategyDefinition,
        as_of: datetime,
        account_states: Optional[Iterable[AccountState]] = None,
    ) -> Dict[str, List]:
        raise NotImplementedError


class PortfolioConstructor(ABC):
    @abstractmethod
    def build_targets(self, strategy_id: str, market: Market, as_of: datetime, signals: List[SignalSnapshot]) -> List[TargetPosition]:
        raise NotImplementedError


class ExecutionPlanner(ABC):
    @abstractmethod
    def build_trade_suggestions(
        self,
        account_states: Iterable[AccountState],
        targets: List[TargetPosition],
        as_of: datetime,
        source_strategy_id: str,
    ) -> List[TradeSuggestion]:
        raise NotImplementedError

    @abstractmethod
    def build_order_intents(
        self,
        trade_suggestions: List[TradeSuggestion],
        requires_manual_approval: bool,
    ) -> List[OrderIntent]:
        raise NotImplementedError


class MarketRules(ABC):
    @abstractmethod
    def validate_order_intent(
        self,
        account_state: AccountState,
        order_intent: OrderIntent,
        data_provider: MarketDataProvider,
        as_of: datetime,
    ) -> List[str]:
        raise NotImplementedError


class RiskEngine(ABC):
    @abstractmethod
    def validate(
        self,
        account_states: Dict[str, AccountState],
        order_intents: List[OrderIntent],
        context: RuntimeContext,
    ) -> Dict[str, List]:
        raise NotImplementedError


class BrokerAdapter(ABC):
    @abstractmethod
    def submit_orders(self, order_intents: List[OrderIntent]) -> List[object]:
        raise NotImplementedError


class StateStore(ABC):
    @abstractmethod
    def get_account_state(self, account_id: str) -> AccountState:
        raise NotImplementedError

    @abstractmethod
    def save_account_state(self, account_state: AccountState) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert_trade_suggestions(self, suggestions: List[TradeSuggestion]) -> List[TradeSuggestion]:
        raise NotImplementedError

    @abstractmethod
    def upsert_order_intents(self, order_intents: List[OrderIntent]) -> List[OrderIntent]:
        raise NotImplementedError


class AgentRuntime(ABC):
    @abstractmethod
    def run_research(self, market: Market, as_of: datetime) -> object:
        raise NotImplementedError

    @abstractmethod
    def run_strategy(
        self,
        strategy: StrategyDefinition,
        market: Market,
        as_of: datetime,
        account_states: Iterable[AccountState],
    ) -> StrategyProposal:
        raise NotImplementedError

    @abstractmethod
    def run_review(self, proposal: StrategyProposal) -> ReviewReport:
        raise NotImplementedError
