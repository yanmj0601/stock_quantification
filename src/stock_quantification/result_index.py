from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .artifacts import read_json_artifact, write_json_artifact


RESULT_INDEX_RELATIVE_PATH = "web/result_index.json"


def record_result(
    base_dir: str | Path,
    record: Dict[str, Any],
    *,
    relative_path: str = RESULT_INDEX_RELATIVE_PATH,
) -> Dict[str, Any]:
    if not isinstance(record, dict):
        raise TypeError("record must be a dict")
    result_id = str(record.get("result_id") or "").strip()
    if not result_id:
        raise ValueError("record.result_id is required")

    normalized = dict(record)
    normalized["result_id"] = result_id
    normalized["recorded_at"] = datetime.utcnow().isoformat(timespec="seconds")

    payload = _load_index(base_dir, relative_path)
    rows = payload["records"]
    replaced = False
    for index, existing in enumerate(rows):
        if existing["result_id"] == result_id:
            rows[index] = normalized
            replaced = True
            break
    if not replaced:
        rows.append(normalized)
    rows.sort(key=_sort_key, reverse=True)
    write_json_artifact(base_dir, relative_path, payload)
    return normalized


def list_results(
    base_dir: str | Path,
    *,
    artifact_kind: str | None = None,
    market: str | None = None,
    limit: int | None = None,
    relative_path: str = RESULT_INDEX_RELATIVE_PATH,
) -> List[Dict[str, Any]]:
    payload = _load_index(base_dir, relative_path)
    rows = payload["records"]
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        if artifact_kind is not None and str(row.get("artifact_kind")) != artifact_kind:
            continue
        if market is not None and str(row.get("market")) != market:
            continue
        filtered.append(dict(row))
    if limit is not None:
        return filtered[: max(0, int(limit))]
    return filtered


def normalize_validation_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    parameter_stability = payload.get("parameter_stability", {})
    recommended_scenario = str(parameter_stability.get("recommended_scenario") or "")
    scenarios = parameter_stability.get("scenarios", [])
    recommended = next(
        (
            row
            for row in scenarios
            if isinstance(row, dict) and str(row.get("scenario_name")) == recommended_scenario
        ),
        {},
    )
    return {
        "subject_id": recommended_scenario or None,
        "subject_name": recommended_scenario or None,
        "decision": recommended.get("decision"),
        "rationale": recommended.get("rationale"),
        "score": recommended.get("stability_score"),
        "return": recommended.get("average_test_return"),
        "excess_return": recommended.get("average_test_excess_return"),
        "max_drawdown": None,
        "regime_summary": [],
        "alpha_mix": [],
    }


def normalize_strategy_suite_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    strategies = payload.get("strategies", [])
    top_row = strategies[0] if strategies and isinstance(strategies[0], dict) else {}
    scorecard = top_row.get("scorecard", {}) if isinstance(top_row, dict) else {}
    return {
        "subject_id": top_row.get("preset_id"),
        "subject_name": top_row.get("display_name"),
        "decision": scorecard.get("decision"),
        "rationale": scorecard.get("rationale"),
        "score": scorecard.get("score"),
        "return": top_row.get("total_return"),
        "excess_return": top_row.get("excess_return"),
        "max_drawdown": top_row.get("max_drawdown"),
        "regime_summary": top_row.get("regime_summary", []),
        "alpha_mix": top_row.get("alpha_mix", []),
    }


def normalize_rolling_backtest_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    summary = payload.get("summary", {})
    return {
        "subject_id": summary.get("preset_id"),
        "subject_name": summary.get("display_name"),
        "decision": None,
        "rationale": None,
        "score": None,
        "return": summary.get("total_return"),
        "excess_return": summary.get("excess_return"),
        "max_drawdown": summary.get("max_drawdown"),
        "regime_summary": [],
        "alpha_mix": [],
    }


def normalize_local_paper_run_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    summary = payload.get("summary", {})
    account_id = summary.get("account_id")
    strategy_id = summary.get("strategy_id")
    trade_count = summary.get("trade_count")
    position_count = summary.get("position_count")
    cash = summary.get("cash")
    buying_power = summary.get("buying_power")
    return {
        "subject_id": f"{account_id}:{strategy_id}" if account_id and strategy_id else account_id or strategy_id,
        "subject_name": " / ".join(str(item) for item in (account_id, strategy_id) if item),
        "decision": "RECORDED",
        "rationale": f"{trade_count} trades routed into local paper ledger with {position_count} open positions",
        "score": trade_count,
        "return": cash,
        "excess_return": buying_power,
        "max_drawdown": None,
        "regime_summary": [],
        "alpha_mix": [],
    }


def _load_index(base_dir: str | Path, relative_path: str) -> Dict[str, List[Dict[str, Any]]]:
    payload = read_json_artifact(base_dir, relative_path)
    rows = payload.get("records", []) if isinstance(payload, dict) else []
    valid_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result_id = str(row.get("result_id") or "").strip()
        if not result_id:
            continue
        valid_rows.append(dict(row))
    valid_rows.sort(key=_sort_key, reverse=True)
    return {"records": valid_rows}


def _sort_key(row: Dict[str, Any]) -> str:
    return str(
        row.get("sort_date")
        or row.get("end_date")
        or row.get("trade_date")
        or row.get("as_of")
        or row.get("recorded_at")
        or ""
    )
