from __future__ import annotations

from dataclasses import replace
from typing import Dict, List

from .interfaces import StateStore
from .models import AccountState, OrderIntent, TradeSuggestion


class InMemoryStateStore(StateStore):
    def __init__(self) -> None:
        self._accounts: Dict[str, AccountState] = {}
        self._trade_suggestions: Dict[str, TradeSuggestion] = {}
        self._order_intents: Dict[str, OrderIntent] = {}

    def get_account_state(self, account_id: str) -> AccountState:
        return self._accounts[account_id]

    def save_account_state(self, account_state: AccountState) -> None:
        self._accounts[account_state.account_id] = account_state

    def upsert_trade_suggestions(self, suggestions: List[TradeSuggestion]) -> List[TradeSuggestion]:
        for suggestion in suggestions:
            self._trade_suggestions[suggestion.suggestion_id] = suggestion
        return [self._trade_suggestions[s.suggestion_id] for s in suggestions]

    def upsert_order_intents(self, order_intents: List[OrderIntent]) -> List[OrderIntent]:
        for order_intent in order_intents:
            self._order_intents[order_intent.order_intent_id] = order_intent
        return [self._order_intents[o.order_intent_id] for o in order_intents]

    def suggestion_count(self) -> int:
        return len(self._trade_suggestions)

    def order_intent_count(self) -> int:
        return len(self._order_intents)
