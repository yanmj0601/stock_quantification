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
_TEMPLATE_ORDER = (
    "breakout_rotation",
    "defensive_balance",
    "concentration_focus",
    "liquidity_probe",
)
_TEMPLATE_LABELS = {
    "breakout_rotation": "突破确认轮换",
    "defensive_balance": "防守平衡",
    "concentration_focus": "集中度提升",
    "liquidity_probe": "流动性量能探测",
}
_REDUNDANT_MOMENTUM_PRUNE_ORDER = (
    "rel_ret_20",
    "momentum_acceleration",
    "trend",
    "ma_trend_alignment",
    "rel_ret_60",
    "base_breakout_score",
)


def derive_next_factor_backtest_payload(
    *,
    result: Dict[str, Any],
    current_payload: Dict[str, Any],
    current_job_id: str,
    lineage_summary: Optional[Dict[str, Any]] = None,
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

    current_metrics = summarize_generation_metrics(result)
    generations = list((lineage_summary or {}).get("generations", []) or [])
    previous_metrics = generations[-1] if generations else None
    comparison = compare_generation_metrics(current_metrics, previous_metrics)
    stagnation_count = int((lineage_summary or {}).get("stagnation_count", 0) or 0)
    if comparison["is_stagnating"]:
        stagnation_count += 1
    else:
        stagnation_count = 0

    preferred_template = _choose_preferred_template(result, current_metrics)
    last_template = str((lineage_summary or {}).get("last_mutation_template") or current_payload.get("mutation_template") or "").strip()
    mutation_template = preferred_template
    mutation_steps: List[str] = []

    if comparison["is_stagnating"] and stagnation_count >= 2:
        mutation_template = _rotate_template(last_template or preferred_template)
        mutation_steps.append(
            f"最近两代没有带来有效提升，派生模板从「{_template_label(last_template or preferred_template)}」切换到「{_template_label(mutation_template)}」。"
        )
    elif comparison["is_stagnating"] and last_template:
        mutation_template = last_template
        mutation_steps.append(
            f"上一代没有明显改善，但先继续沿用「{_template_label(mutation_template)}」做一次确认。"
        )
    elif last_template and preferred_template != last_template:
        mutation_steps.append(
            f"根据当前归因结果，派生模板从「{_template_label(last_template)}」调整为「{_template_label(preferred_template)}」。"
        )

    _apply_template(
        mutation_template,
        factor_tilts=factor_tilts,
        selected_factors=selected_factors,
        selected_set=selected_set,
        current_top_n=int(current_payload.get("top_n", current_metrics.get("top_n", 10)) or 10),
        mutation_steps=mutation_steps,
    )
    if comparison["is_stagnating"] and stagnation_count >= 2:
        removed_factors = _prune_redundant_factors(
            selected_factors=selected_factors,
            selected_set=selected_set,
            factor_tilts=factor_tilts,
            preferred_template=preferred_template,
            mutation_template=mutation_template,
        )
        if removed_factors:
            mutation_steps.append(f"连续停滞后，从拥挤家族中剔除冗余因子：{'、'.join(removed_factors)}。")

    next_top_n = _next_top_n(
        mutation_template=mutation_template,
        current_top_n=int(current_payload.get("top_n", current_metrics.get("top_n", 10)) or 10),
    )
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
            "mutation_template": mutation_template,
            "iteration_summary": mutation_steps,
        }
    )
    return {
        "payload": next_payload,
        "mutation_reason": mutation_reason,
        "mutation_template": mutation_template,
        "iteration_summary": mutation_steps,
        "comparison": comparison,
        "generation_metrics": current_metrics,
        "stagnation_count": stagnation_count,
    }


def summarize_generation_metrics(result: Dict[str, Any]) -> Dict[str, Any]:
    attribution = result.get("attribution", {}) if isinstance(result.get("attribution"), dict) else {}
    scorecard = attribution.get("scorecard", {}) if isinstance(attribution.get("scorecard"), dict) else {}
    regime_rows = attribution.get("regime_summary", []) if isinstance(attribution.get("regime_summary"), list) else []
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    return {
        "generation": int(summary.get("generation", 1) or 1),
        "score": _to_decimal(scorecard.get("score", "0")),
        "excess_return": _to_decimal(summary.get("rolling_excess_return", "0")),
        "max_drawdown": abs(_to_decimal(summary.get("max_drawdown", "0"))),
        "up_excess": _regime_excess(regime_rows, "UP"),
        "decision": str(scorecard.get("decision") or ""),
        "top_n": int(summary.get("top_n", 10) or 10),
    }


def compare_generation_metrics(
    current_metrics: Dict[str, Any],
    previous_metrics: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not previous_metrics:
        return {
            "score_delta": "0.0000",
            "excess_delta": "0.0000",
            "drawdown_delta": "0.0000",
            "up_excess_delta": "0.0000",
            "is_stagnating": False,
            "improved": False,
        }

    score_delta = _to_decimal(current_metrics.get("score", "0")) - _to_decimal(previous_metrics.get("score", "0"))
    excess_delta = _to_decimal(current_metrics.get("excess_return", "0")) - _to_decimal(previous_metrics.get("excess_return", "0"))
    drawdown_delta = _to_decimal(previous_metrics.get("max_drawdown", "0")) - _to_decimal(current_metrics.get("max_drawdown", "0"))
    up_excess_delta = _to_decimal(current_metrics.get("up_excess", "0")) - _to_decimal(previous_metrics.get("up_excess", "0"))
    improved = excess_delta > Decimal("0.0030") or score_delta > Decimal("0.2500")
    is_stagnating = excess_delta <= Decimal("0.0010") and score_delta <= Decimal("0.1000")
    return {
        "score_delta": str(score_delta.quantize(Decimal("0.0001"))),
        "excess_delta": str(excess_delta.quantize(Decimal("0.0001"))),
        "drawdown_delta": str(drawdown_delta.quantize(Decimal("0.0001"))),
        "up_excess_delta": str(up_excess_delta.quantize(Decimal("0.0001"))),
        "is_stagnating": is_stagnating,
        "improved": improved,
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


def _choose_preferred_template(result: Dict[str, Any], current_metrics: Dict[str, Any]) -> str:
    attribution = result.get("attribution", {}) if isinstance(result.get("attribution"), dict) else {}
    alpha_mix_rows = attribution.get("alpha_mix", []) if isinstance(attribution.get("alpha_mix"), list) else []
    momentum_share = _alpha_mix_share(alpha_mix_rows, "momentum")
    excess_return = _to_decimal(current_metrics.get("excess_return", "0"))
    up_excess = _to_decimal(current_metrics.get("up_excess", "0"))
    max_drawdown = _to_decimal(current_metrics.get("max_drawdown", "0"))
    rolling_summary = (
        result.get("rolling_backtest", {}).get("summary", {})
        if isinstance(result.get("rolling_backtest"), dict)
        and isinstance(result.get("rolling_backtest", {}).get("summary"), dict)
        else {}
    )
    risk_exit_count = int(rolling_summary.get("risk_exit_count", 0) or 0)

    if momentum_share >= Decimal("0.50") and up_excess <= Decimal("0"):
        return "breakout_rotation"
    if risk_exit_count >= 15 or max_drawdown >= Decimal("0.10"):
        return "defensive_balance"
    if excess_return <= Decimal("-0.0500"):
        return "concentration_focus"
    return "liquidity_probe"


def _apply_template(
    mutation_template: str,
    *,
    factor_tilts: Dict[str, Decimal],
    selected_factors: List[str],
    selected_set: set[str],
    current_top_n: int,
    mutation_steps: List[str],
) -> None:
    if mutation_template == "breakout_rotation":
        for name in ("rel_ret_20", "rel_ret_60", "trend", "momentum_acceleration"):
            if name in selected_set:
                factor_tilts[name] = max(Decimal("0.35"), factor_tilts.get(name, Decimal("1.0")) - Decimal("0.25"))
        for name in ("breakout_strength", "price_volume_confirmation", "pullback_resilience", "base_breakout_score"):
            _ensure_factor(selected_factors, selected_set, name)
            factor_tilts[name] = min(Decimal("2.8"), factor_tilts.get(name, Decimal("1.0")) + Decimal("0.25"))
        mutation_steps.append("上涨环境下仍跑输基准，降低拥挤动量，强化突破质量、量价确认与回调韧性。")
        return

    if mutation_template == "defensive_balance":
        for name in ("drawdown", "volatility_contraction", "volatility", "profitability"):
            _ensure_factor(selected_factors, selected_set, name)
        factor_tilts["drawdown"] = min(Decimal("2.8"), factor_tilts.get("drawdown", Decimal("0.8")) + Decimal("0.30"))
        factor_tilts["volatility_contraction"] = min(Decimal("2.8"), factor_tilts.get("volatility_contraction", Decimal("0.8")) + Decimal("0.30"))
        factor_tilts["volatility"] = min(Decimal("2.2"), factor_tilts.get("volatility", Decimal("0.6")) + Decimal("0.15"))
        factor_tilts["profitability"] = min(Decimal("2.0"), factor_tilts.get("profitability", Decimal("1.0")) + Decimal("0.10"))
        mutation_steps.append("风险退出和回撤偏高，先提高低波动、波动收缩和回撤约束，平衡进攻暴露。")
        return

    if mutation_template == "concentration_focus":
        for name in ("breakout_strength", "price_volume_confirmation", "pullback_resilience"):
            _ensure_factor(selected_factors, selected_set, name)
            factor_tilts[name] = min(Decimal("2.6"), factor_tilts.get(name, Decimal("1.0")) + Decimal("0.20"))
        for name in ("liquidity", "volume_expansion"):
            _ensure_factor(selected_factors, selected_set, name)
            factor_tilts[name] = min(Decimal("1.8"), factor_tilts.get(name, Decimal("1.0")) + Decimal("0.10"))
        mutation_steps.append(f"当前持仓数量 {current_top_n} 偏分散，尝试收缩到更集中的强势股篮子。")
        return

    for name in _LIQUIDITY_FACTORS:
        _ensure_factor(selected_factors, selected_set, name)
        factor_tilts[name] = min(Decimal("2.2"), factor_tilts.get(name, Decimal("0.9")) + Decimal("0.15"))
    if "breakout_strength" not in selected_set:
        _ensure_factor(selected_factors, selected_set, "breakout_strength")
    factor_tilts["breakout_strength"] = min(Decimal("2.4"), factor_tilts.get("breakout_strength", Decimal("1.0")) + Decimal("0.10"))
    mutation_steps.append("上一轮没有明显结构性突破，先小步提高流动性、量能和突破确认做探索。")


def _next_top_n(*, mutation_template: str, current_top_n: int) -> int:
    if mutation_template == "concentration_focus":
        return max(4, current_top_n - 2)
    if mutation_template == "defensive_balance":
        return min(10, current_top_n + 1)
    if mutation_template == "breakout_rotation":
        return max(5, current_top_n - 1)
    return current_top_n


def _rotate_template(last_template: str) -> str:
    normalized = last_template if last_template in _TEMPLATE_ORDER else _TEMPLATE_ORDER[0]
    index = _TEMPLATE_ORDER.index(normalized)
    return _TEMPLATE_ORDER[(index + 1) % len(_TEMPLATE_ORDER)]


def _template_label(template: str) -> str:
    return _TEMPLATE_LABELS.get(template, template or "默认局部探索")


def _ensure_factor(selected_factors: List[str], selected_set: set[str], factor_name: str) -> None:
    if factor_name not in selected_set:
        selected_factors.append(factor_name)
        selected_set.add(factor_name)


def _prune_redundant_factors(
    *,
    selected_factors: List[str],
    selected_set: set[str],
    factor_tilts: Dict[str, Decimal],
    preferred_template: str,
    mutation_template: str,
) -> List[str]:
    removed: List[str] = []
    if len(selected_factors) <= 6:
        return removed

    prune_budget = 1
    if mutation_template == "concentration_focus" or preferred_template == "breakout_rotation":
        prune_budget = 2

    for factor_name in _REDUNDANT_MOMENTUM_PRUNE_ORDER:
        if prune_budget <= 0:
            break
        if factor_name not in selected_set:
            continue
        if factor_name in {"breakout_strength", "price_volume_confirmation", "pullback_resilience"}:
            continue
        selected_set.remove(factor_name)
        selected_factors[:] = [name for name in selected_factors if name != factor_name]
        factor_tilts.pop(factor_name, None)
        removed.append(factor_name)
        prune_budget -= 1
        if len(selected_factors) <= 6:
            break
    return removed


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
