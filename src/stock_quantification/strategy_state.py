from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .artifacts import read_json_artifact, write_json_artifact
from .models import Market

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

    def load_state(self) -> Dict[str, Any]:
        try:
            raw_state = read_json_artifact(self._base_dir, self._relative_path)
        except json.JSONDecodeError:
            return _empty_state()
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
        state = self.load_state()
        state["markets"][market_enum.value] = {
            "champion_preset_id": champion_preset_id,
            "challenger_preset_id": challenger_preset_id,
            "current_execution_preset_id": current_execution_preset_id,
        }
        write_json_artifact(self._base_dir, self._relative_path, state)
        return state
