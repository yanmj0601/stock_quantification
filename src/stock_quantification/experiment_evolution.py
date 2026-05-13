from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional


_MOMENTUM_FACTORS = (
    "rel_ret_20",
    "rel_ret_60",
    "trend",
    "ma_trend_alignment",
    "breakout_strength",
    "base_breakout_score",
    "price_volume_confirmation",
    "momentum_acceleration",
    "pullback_resilience",
)
_RISK_FACTORS = ("volatility", "drawdown", "volatility_contraction")
_LIQUIDITY_FACTORS = ("liquidity", "volume_expansion")


def derive_next_factor_backtest_payload(
    *,
    result: Dict[str, Any],
    current_payload: Dict[str, Any],
    current_job_id: str,
) -> Optional[Dict[str, Any]]:
    if not bool(current_payload.get("auto_iterate")):
        return None
    generation = max(1, int(current_payload.get("generation", 1) or 1))
    max_generations = max(generation, int(current_payload.get("max_generations", generation) or generation))
    if generation >= max_generations:
        return None

    attribution = result.get("attribution", {}) if isinstance(result.get("attribution"), dict) else {}
    scorecard = attribution.get("scorecard", {}) if isinstance(attribution.get("scorecard"), dict) else {}
    if str(scorecard.get("decision") or "").upper() == "DROP":
        return None

    next_payload = dict(current_payload)
    factor_tilts = {
        str(name): _to_decimal(value)
        for name, value in (current_payload.get("factor_tilts", {}) or {}).items()
    }
    selected_factors = [str(name) for name in current_payload.get("selected_factors", []) if str(name)]
    selected_set = set(selected_factors)
    mutation_steps: List[str] = []

    regime_rows = attribution.get("regime_summary", []) if isinstance(attribution.get("regime_summary"), list) else []
    alpha_mix_rows = attribution.get("alpha_mix", []) if isinstance(attribution.get("alpha_mix"), list) else []
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    rolling_summary = (
        result.get("rolling_backtest", {}).get("summary", {})
        if isinstance(result.get("rolling_backtest"), dict)
        and isinstance(result.get("rolling_backtest", {}).get("summary"), dict)
        else {}
    )

    momentum_share = _alpha_mix_share(alpha_mix_rows, "momentum")
    up_excess = _regime_excess(regime_rows, "UP")
    average_excess = _to_decimal(summary.get("average_excess_return", "0"))
    max_drawdown = abs(_to_decimal(summary.get("max_drawdown", "0")))
    risk_exit_count = int(rolling_summary.get("risk_exit_count", summary.get("risk_exit_count", 0)) or 0)
    trend_exit_count = int(rolling_summary.get("trend_exit_count", summary.get("trend_exit_count", 0)) or 0)

    if momentum_share >= Decimal("0.55") and up_excess <= Decimal("0"):
        for name in ("rel_ret_20", "rel_ret_60", "trend", "momentum_acceleration"):
            if name in selected_set:
                factor_tilts[name] = max(Decimal("0.4"), factor_tilts.get(name, Decimal("1.0")) - Decimal("0.2"))
        for name in ("breakout_strength", "price_volume_confirmation", "pullback_resilience"):
            if name not in selected_set:
                selected_factors.append(name)
                selected_set.add(name)
            factor_tilts[name] = min(Decimal("2.5"), factor_tilts.get(name, Decimal("1.0")) + Decimal("0.2"))
        mutation_steps.append("上涨状态下跑输基准，降低拥挤动量，转向突破确认与回调修复。")

    if risk_exit_count > 0 or max_drawdown >= Decimal("0.08"):
        for name in ("drawdown", "volatility_contraction"):
            if name not in selected_set:
                selected_factors.append(name)
                selected_set.add(name)
            factor_tilts[name] = min(Decimal("2.5"), factor_tilts.get(name, Decimal("0.6")) + Decimal("0.2"))
        if "volatility" not in selected_set:
            selected_factors.append("volatility")
            selected_set.add("volatility")
        factor_tilts["volatility"] = min(Decimal("2.5"), factor_tilts.get("volatility", Decimal("0.5")) + Decimal("0.1"))
        mutation_steps.append("回撤或风险退出偏高，增强回撤、波动收缩和低波动约束。")

    if average_excess <= Decimal("0"):
        for name in _LIQUIDITY_FACTORS:
            if name not in selected_set:
                selected_factors.append(name)
                selected_set.add(name)
            factor_tilts[name] = min(Decimal("2.5"), factor_tilts.get(name, Decimal("0.8")) + Decimal("0.1"))
        mutation_steps.append("单期超额偏弱，补强流动性与量能确认。")

    if not mutation_steps:
        fallback = "breakout_strength"
        if fallback not in selected_set:
            selected_factors.append(fallback)
            selected_set.add(fallback)
        factor_tilts[fallback] = min(Decimal("2.5"), factor_tilts.get(fallback, Decimal("1.0")) + Decimal("0.1"))
        mutation_steps.append("上一轮没有明显结构性问题，先小幅提高突破强度做局部探索。")

    next_top_n = int(current_payload.get("top_n", summary.get("top_n", 10)) or 10)
    if up_excess <= Decimal("0") and next_top_n > 6:
        next_top_n = max(6, next_top_n - 2)
        mutation_steps.append("上涨状态下吃不到收益，适度收缩持仓数量，提高集中度。")

    next_generation = generation + 1
    mutation_reason = " ".join(mutation_steps)
    next_payload.update(
        {
            "selected_factors": selected_factors,
            "factor_tilts": {
                name: str(value.quantize(Decimal("0.0001")))
                for name, value in sorted(factor_tilts.items())
            },
            "top_n": next_top_n,
            "generation": next_generation,
            "parent_job_id": current_job_id,
            "mutation_reason": mutation_reason,
            "iteration_summary": mutation_steps,
        }
    )
    return {
        "payload": next_payload,
        "mutation_reason": mutation_reason,
        "iteration_summary": mutation_steps,
    }


def describe_factor_backtest_stop_reason(
    *,
    result: Dict[str, Any],
    current_payload: Dict[str, Any],
) -> str:
    if not bool(current_payload.get("auto_iterate")):
        return "未启用自动续跑实验。"
    generation = max(1, int(current_payload.get("generation", 1) or 1))
    max_generations = max(generation, int(current_payload.get("max_generations", generation) or generation))
    if generation >= max_generations:
        return f"已达到最大代次 {max_generations}。"
    attribution = result.get("attribution", {}) if isinstance(result.get("attribution"), dict) else {}
    scorecard = attribution.get("scorecard", {}) if isinstance(attribution.get("scorecard"), dict) else {}
    if str(scorecard.get("decision") or "").upper() == "DROP":
        return "本轮结论为 DROP，停止继续派生。"
    return "当前没有生成有效的下一轮参数。"


def _alpha_mix_share(rows: List[Dict[str, Any]], family: str) -> Decimal:
    for row in rows:
        if str(row.get("family") or "").strip().lower() == family.lower():
            return _to_decimal(row.get("share_of_gross", "0"))
    return Decimal("0")


def _regime_excess(rows: List[Dict[str, Any]], regime: str) -> Decimal:
    for row in rows:
        if str(row.get("regime") or "").strip().upper() == regime.upper():
            return _to_decimal(row.get("average_excess_period_return", "0"))
    return Decimal("0")


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or "0"))
