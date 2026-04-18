from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Sequence

from .backtest import RollingBacktestReport
from .models import Market
from .strategy_catalog import StrategyPreset


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or "0"))


@dataclass(frozen=True)
class RegimeBucketSummary:
    regime: str
    observations: int
    average_period_return: Decimal
    average_benchmark_period_return: Decimal
    average_excess_period_return: Decimal
    win_rate: Decimal


@dataclass(frozen=True)
class AlphaMixRow:
    family: str
    net_weight: Decimal
    gross_weight: Decimal
    share_of_gross: Decimal


@dataclass(frozen=True)
class StrategyScorecard:
    preset_id: str
    market: str
    score: Decimal
    decision: str
    strengths: List[str]
    warnings: List[str]
    rationale: str


def summarize_regimes(
    report: RollingBacktestReport,
    up_threshold: Decimal = Decimal("0.003"),
    down_threshold: Decimal = Decimal("-0.003"),
) -> List[RegimeBucketSummary]:
    buckets: Dict[str, List[object]] = {"UP": [], "RANGE": [], "DOWN": []}
    for day in report.daily:
        benchmark_period = day.benchmark_period_return
        if benchmark_period is None:
            regime = "RANGE"
        elif benchmark_period >= up_threshold:
            regime = "UP"
        elif benchmark_period <= down_threshold:
            regime = "DOWN"
        else:
            regime = "RANGE"
        buckets[regime].append(day)

    summaries: List[RegimeBucketSummary] = []
    for regime, rows in buckets.items():
        if not rows:
            continue
        period_returns = [_to_decimal(row.period_return) for row in rows]
        benchmark_returns = [
            _to_decimal(row.benchmark_period_return) for row in rows if row.benchmark_period_return is not None
        ]
        excess_returns = [
            _to_decimal(row.excess_period_return) for row in rows if row.excess_period_return is not None
        ]
        positive = sum(1 for item in period_returns if item > 0)
        observations = len(rows)
        summaries.append(
            RegimeBucketSummary(
                regime=regime,
                observations=observations,
                average_period_return=sum(period_returns, Decimal("0")) / Decimal(observations),
                average_benchmark_period_return=(
                    sum(benchmark_returns, Decimal("0")) / Decimal(len(benchmark_returns))
                    if benchmark_returns
                    else Decimal("0")
                ),
                average_excess_period_return=(
                    sum(excess_returns, Decimal("0")) / Decimal(len(excess_returns))
                    if excess_returns
                    else Decimal("0")
                ),
                win_rate=Decimal(positive) / Decimal(observations),
            )
        )
    return summaries


def summarize_alpha_mix(preset: StrategyPreset) -> List[AlphaMixRow]:
    groups = _factor_groups(preset.market)
    gross_total = sum(abs(weight) for weight in preset.alpha_weights.values())
    rows: List[AlphaMixRow] = []
    for family, factors in groups.items():
        net_weight = sum((preset.alpha_weights.get(factor, Decimal("0")) for factor in factors), Decimal("0"))
        gross_weight = sum((abs(preset.alpha_weights.get(factor, Decimal("0"))) for factor in factors), Decimal("0"))
        share = Decimal("0") if gross_total == 0 else gross_weight / gross_total
        rows.append(
            AlphaMixRow(
                family=family,
                net_weight=net_weight,
                gross_weight=gross_weight,
                share_of_gross=share,
            )
        )
    rows.sort(key=lambda item: item.gross_weight, reverse=True)
    return rows


def build_strategy_scorecard(
    preset: StrategyPreset,
    report: RollingBacktestReport,
    regime_summaries: Sequence[RegimeBucketSummary],
) -> StrategyScorecard:
    summary = report.summary
    score = Decimal("0")
    strengths: List[str] = []
    warnings: List[str] = []

    score += summary.total_return * Decimal("4")
    score += _to_decimal(summary.excess_return or Decimal("0")) * Decimal("6")
    score += summary.sharpe_ratio * Decimal("2")
    score += summary.annualized_return
    score -= abs(summary.max_drawdown) * Decimal("3")
    score -= summary.average_turnover * Decimal("2")
    score -= summary.fee_drag * Decimal("2")

    positive_regimes = 0
    for regime in regime_summaries:
        if regime.average_excess_period_return > 0:
            positive_regimes += 1
    if positive_regimes >= 2:
        score += Decimal("0.10")
        strengths.append("跨市场状态保持正超额")
    elif positive_regimes == 0 and regime_summaries:
        score -= Decimal("0.10")
        warnings.append("不同市场状态下都没有拿到正超额")

    if summary.total_return > 0:
        strengths.append("净收益为正")
    else:
        warnings.append("净收益仍为负或接近零")
    if summary.excess_return is not None and summary.excess_return > 0:
        strengths.append("相对基准有正超额")
    elif summary.excess_return is not None:
        warnings.append("相对基准没有稳定超额")
    if abs(summary.max_drawdown) > Decimal("0.15"):
        warnings.append("最大回撤偏大")
    if summary.average_turnover > Decimal("0.20"):
        warnings.append("平均换手偏高，容易吞噬 alpha")
    if summary.fee_drag > Decimal("0.01"):
        warnings.append("费用拖累明显")

    decision = "KEEP"
    if summary.total_return <= 0 or (summary.excess_return is not None and summary.excess_return <= 0):
        decision = "REVIEW"
    if (
        summary.total_return <= 0
        and (summary.excess_return is None or summary.excess_return <= 0)
        and abs(summary.max_drawdown) >= Decimal("0.12")
    ):
        decision = "DROP"

    rationale = (
        f"net={summary.total_return.quantize(Decimal('0.0001'))} "
        f"excess={_to_decimal(summary.excess_return or Decimal('0')).quantize(Decimal('0.0001'))} "
        f"sharpe={summary.sharpe_ratio.quantize(Decimal('0.0001'))} "
        f"drawdown={summary.max_drawdown.quantize(Decimal('0.0001'))}"
    )
    return StrategyScorecard(
        preset_id=preset.preset_id,
        market=summary.market,
        score=score,
        decision=decision,
        strengths=strengths,
        warnings=warnings,
        rationale=rationale,
    )


def serialize_regime_summaries(rows: Iterable[RegimeBucketSummary]) -> List[Dict[str, object]]:
    return [_serialize_dataclass(row) for row in rows]


def serialize_alpha_mix(rows: Iterable[AlphaMixRow]) -> List[Dict[str, object]]:
    return [_serialize_dataclass(row) for row in rows]


def serialize_strategy_scorecard(scorecard: StrategyScorecard) -> Dict[str, object]:
    return _serialize_dataclass(scorecard)


def _serialize_dataclass(item) -> Dict[str, object]:
    payload = asdict(item)
    for key, value in payload.items():
        if isinstance(value, Decimal):
            payload[key] = str(value.quantize(Decimal("0.0001")))
    return payload


def _factor_groups(market: Market) -> Dict[str, List[str]]:
    if market == Market.CN:
        return {
            "momentum": ["rel_ret_20", "rel_ret_60", "trend"],
            "quality": ["profitability"],
            "risk_control": ["volatility", "drawdown"],
            "liquidity": ["liquidity"],
        }
    return {
        "momentum": ["rel_ret_20", "rel_ret_60", "trend"],
        "quality": ["profitability", "quality"],
        "risk_control": ["volatility", "drawdown"],
        "liquidity": ["liquidity"],
    }
