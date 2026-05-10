from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

from .artifacts import read_json_artifact, write_json_artifact
from .models import Market
from .pipeline import build_cn_index_enhancement_blueprint, build_us_quality_momentum_blueprint


DEFAULT_STRATEGY_REGISTRY_RELATIVE_PATH = "web/strategy_registry.json"
_MARKETS = (Market.CN, Market.US)


def _baseline_alpha_keys(market: Market) -> List[str]:
    if market == Market.CN:
        return list(build_cn_index_enhancement_blueprint().alpha_weights.keys())
    return list(build_us_quality_momentum_blueprint().alpha_weights.keys())


def _empty_state() -> Dict[str, Any]:
    return {"markets": {market.value: [] for market in _MARKETS}}


def _normalize_market(market: Market | str) -> Market:
    return market if isinstance(market, Market) else Market(str(market))


def _stringify_decimal_map(payload: Any) -> Dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    normalized: Dict[str, str] = {}
    for key, value in payload.items():
        try:
            normalized[str(key)] = str(Decimal(str(value)).quantize(Decimal("0.0001")))
        except Exception:
            continue
    return normalized


def _normalize_record(record: Any) -> Dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    return {
        "preset_id": str(record.get("preset_id") or "").strip(),
        "market": str(record.get("market") or "").strip().upper(),
        "display_name": str(record.get("display_name") or "").strip(),
        "family": str(record.get("family") or "实验候选").strip(),
        "description": str(record.get("description") or "").strip(),
        "top_n": int(record.get("top_n") or 4),
        "alpha_weights": _stringify_decimal_map(record.get("alpha_weights")),
        "policy_overrides": _stringify_decimal_map(record.get("policy_overrides")),
        "source_artifact_path": str(record.get("source_artifact_path") or "").strip() or None,
        "source_subject_id": str(record.get("source_subject_id") or "").strip() or None,
        "source_subject_name": str(record.get("source_subject_name") or "").strip() or None,
        "decision": str(record.get("decision") or "").strip() or None,
        "created_at": str(record.get("created_at") or "").strip() or None,
    }


def _normalize_state(payload: Any) -> Dict[str, Any]:
    normalized = _empty_state()
    if not isinstance(payload, dict):
        return normalized
    raw_markets = payload.get("markets")
    if not isinstance(raw_markets, dict):
        return normalized
    for market in _MARKETS:
        rows = raw_markets.get(market.value, [])
        if not isinstance(rows, list):
            continue
        normalized["markets"][market.value] = [row for row in (_normalize_record(item) for item in rows) if row.get("preset_id")]
    return normalized


def _candidate_digest(summary: Dict[str, Any]) -> str:
    subject_id = str(summary.get("subject_id") or "").strip()
    if ":" in subject_id:
        suffix = subject_id.rsplit(":", 1)[-1].strip()
        if re.fullmatch(r"[a-z0-9]{6,40}", suffix):
            return suffix[:16]
    match = re.search(r"([a-z0-9]{6,40})", subject_id.lower())
    if match:
        return match.group(1)[:16]
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")


def build_candidate_record_from_factor_backtest(
    payload: Dict[str, Any],
    *,
    artifact_path: str | None = None,
) -> Dict[str, Any]:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    market = Market(str(summary.get("market") or "US"))
    digest = _candidate_digest(summary)
    candidate_id = f"{market.value.lower()}_candidate_{digest}"
    alpha_weights = {name: "0.0000" for name in _baseline_alpha_keys(market)}
    for row in summary.get("selected_factor_rows", []):
        if not isinstance(row, dict):
            continue
        factor_name = str(row.get("factor_name") or "").strip()
        if factor_name not in alpha_weights:
            continue
        alpha_weights[factor_name] = str(Decimal(str(row.get("effective_weight") or "0")).quantize(Decimal("0.0001")))
    return {
        "preset_id": candidate_id,
        "market": market.value,
        "display_name": str(summary.get("subject_name") or f"{market.value} 实验候选策略").strip(),
        "family": "实验候选",
        "description": "由策略优化实验晋升而来的可执行候选策略。",
        "top_n": int(summary.get("top_n") or 4),
        "alpha_weights": alpha_weights,
        "policy_overrides": {},
        "source_artifact_path": artifact_path,
        "source_subject_id": str(summary.get("subject_id") or "").strip() or None,
        "source_subject_name": str(summary.get("subject_name") or "").strip() or None,
        "decision": str(summary.get("decision") or "REVIEW").strip() or "REVIEW",
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


class StrategyRegistryStore:
    def __init__(self, base_dir: str | Path, relative_path: str = DEFAULT_STRATEGY_REGISTRY_RELATIVE_PATH) -> None:
        self._base_dir = Path(base_dir)
        self._relative_path = relative_path

    def load_state(self) -> Dict[str, Any]:
        try:
            raw_state = read_json_artifact(self._base_dir, self._relative_path)
        except json.JSONDecodeError:
            return _empty_state()
        return _normalize_state(raw_state)

    def list_market_records(self, market: Market | str) -> List[Dict[str, Any]]:
        market_enum = _normalize_market(market)
        rows = self.load_state()["markets"].get(market_enum.value, [])
        return [dict(row) for row in rows if row.get("preset_id")]

    def list_market_presets(self, market: Market | str) -> List[Any]:
        return [self._strategy_preset_from_record(row) for row in self.list_market_records(market)]

    def lookup_record(self, market: Market | str, preset_id: str) -> Dict[str, Any]:
        for row in self.list_market_records(market):
            if str(row.get("preset_id")) == str(preset_id):
                return row
        raise KeyError(f"Unknown registered strategy for {_normalize_market(market).value}: {preset_id}")

    def lookup_strategy(self, market: Market | str, preset_id: str) -> Any:
        return self._strategy_preset_from_record(self.lookup_record(market, preset_id))

    def promote_factor_backtest_candidate(self, payload: Dict[str, Any], *, artifact_path: str | None = None) -> Dict[str, Any]:
        candidate = build_candidate_record_from_factor_backtest(payload, artifact_path=artifact_path)
        state = self.load_state()
        market_rows = list(state["markets"].get(candidate["market"], []))
        replaced = False
        for index, row in enumerate(market_rows):
            if str(row.get("preset_id")) == candidate["preset_id"]:
                market_rows[index] = candidate
                replaced = True
                break
        if not replaced:
            market_rows.append(candidate)
        market_rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        state["markets"][candidate["market"]] = market_rows
        write_json_artifact(self._base_dir, self._relative_path, state)
        return candidate

    def _strategy_preset_from_record(self, record: Dict[str, Any]) -> Any:
        from .strategy_catalog import StrategyPreset

        market = _normalize_market(record["market"])
        return StrategyPreset(
            preset_id=str(record["preset_id"]),
            market=market,
            display_name=str(record.get("display_name") or record["preset_id"]),
            family=str(record.get("family") or "实验候选"),
            description=str(record.get("description") or ""),
            alpha_weights={key: Decimal(value) for key, value in _stringify_decimal_map(record.get("alpha_weights")).items()},
            policy_overrides={key: Decimal(value) for key, value in _stringify_decimal_map(record.get("policy_overrides")).items()},
            top_n=int(record.get("top_n") or 4),
        )
