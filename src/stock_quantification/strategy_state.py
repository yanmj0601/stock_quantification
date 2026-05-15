from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .models import Market
from .sqlite_state import SQLiteStateStore

DEFAULT_STRATEGY_STATE_RELATIVE_PATH = "web/strategy_state.json"
_MARKETS = (Market.CN, Market.US)
_KNOWN_MARKET_VALUES = {market.value for market in _MARKETS}
_STATE_FIELDS = ("champion_preset_id", "challenger_preset_id", "current_execution_preset_id")


def _empty_market_state() -> Dict[str, None]:
    return {field: None for field in _STATE_FIELDS}


def _empty_state() -> Dict[str, Any]:
    return {"markets": {market.value: _empty_market_state() for market in _MARKETS}}


def _normalize_market(market: Market | str) -> Market:
    return market if isinstance(market, Market) else Market(str(market))


def _normalize_market_state(state: Any) -> Dict[str, None]:
    if not isinstance(state, dict):
        return _empty_market_state()
    normalized = _empty_market_state()
    for field in _STATE_FIELDS:
        value = state.get(field)
        normalized[field] = value if value is None or isinstance(value, str) else str(value)
    return normalized


def _normalize_state(state: Any) -> Dict[str, Any]:
    normalized = _empty_state()
    if not isinstance(state, dict):
        return normalized
    markets = state.get("markets")
    if not isinstance(markets, dict):
        return normalized
    for market_key, market_state in markets.items():
        if market_key not in _KNOWN_MARKET_VALUES:
            normalized["markets"][str(market_key)] = market_state
    for market in _MARKETS:
        normalized["markets"][market.value] = _normalize_market_state(markets.get(market.value))
    return normalized


class StrategyStateStore:
    def __init__(
        self,
        base_dir: str | Path,
        relative_path: str = DEFAULT_STRATEGY_STATE_RELATIVE_PATH,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._relative_path = relative_path
        self._sqlite = SQLiteStateStore(self._base_dir)

    def load_state(self) -> Dict[str, Any]:
        raw_state = self._sqlite.load_strategy_state()
        if self._sqlite_strategy_state_is_empty(raw_state):
            self._import_legacy_json_if_needed()
            raw_state = self._sqlite.load_strategy_state()
        return _normalize_state(raw_state)

    def load_market_state(self, market: Market | str) -> Dict[str, None]:
        market_key = market.value if isinstance(market, Market) else str(market)
        markets = self.load_state()["markets"]
        if market_key in _KNOWN_MARKET_VALUES:
            return markets[market_key]
        raw_market_state = markets.get(market_key)
        return raw_market_state if isinstance(raw_market_state, dict) else _empty_market_state()

    def set_market_state(
        self,
        market: Market | str,
        *,
        champion_preset_id: str | None,
        challenger_preset_id: str | None,
        current_execution_preset_id: str | None,
    ) -> Dict[str, Any]:
        market_enum = _normalize_market(market)
        self._sqlite.save_market_strategy_state(
            market_enum.value,
            {
                "champion_preset_id": champion_preset_id,
                "challenger_preset_id": challenger_preset_id,
                "current_execution_preset_id": current_execution_preset_id,
            },
        )
        return self.load_state()

    def set_current_execution_preset(self, market: Market | str, preset_id: str) -> Dict[str, Any]:
        market_enum = _normalize_market(market)
        state = self.load_state()
        market_state = _normalize_market_state(state["markets"].get(market_enum.value))
        if not market_state.get("champion_preset_id"):
            market_state["champion_preset_id"] = preset_id
        market_state["current_execution_preset_id"] = preset_id
        self._sqlite.save_market_strategy_state(market_enum.value, market_state)
        state["markets"][market_enum.value] = market_state
        return state

    def _sqlite_strategy_state_is_empty(self, state: Any) -> bool:
        markets = state.get("markets") if isinstance(state, dict) else None
        return not isinstance(markets, dict) or not markets

    def _import_legacy_json_if_needed(self) -> None:
        self._sqlite.import_legacy_strategy_state_json(
            self._base_dir,
            relative_path=self._relative_path,
        )
