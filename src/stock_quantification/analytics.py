from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import sqrt
from typing import Dict, Iterable, List, Mapping, Sequence


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _std(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / Decimal(len(values) - 1)
    return Decimal(str(sqrt(float(variance))))


def _covariance(x_values: Sequence[Decimal], y_values: Sequence[Decimal]) -> Decimal:
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return Decimal("0")
    x_avg = _mean(x_values)
    y_avg = _mean(y_values)
    numerator = sum((x - x_avg) * (y - y_avg) for x, y in zip(x_values, y_values))
    return numerator / Decimal(len(x_values) - 1)


def _correlation(x_values: Sequence[Decimal], y_values: Sequence[Decimal]) -> Decimal:
    x_std = _std(x_values)
    y_std = _std(y_values)
    if x_std == 0 or y_std == 0:
        return Decimal("0")
    return _covariance(x_values, y_values) / (x_std * y_std)


def _rank(values: Sequence[Decimal]) -> List[Decimal]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [Decimal("0")] * len(values)
    for rank_index, (original_index, _) in enumerate(ordered, start=1):
        ranks[original_index] = Decimal(rank_index)
    return ranks


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal
    max_drawdown: Decimal
    sharpe_ratio: Decimal
    turnover_average: Decimal


@dataclass(frozen=True)
class InformationCoefficientMetrics:
    ic: Decimal
    rank_ic: Decimal
    sample_size: int


@dataclass(frozen=True)
class BetaMetrics:
    beta: Decimal
    correlation: Decimal
    asset_volatility: Decimal
    benchmark_volatility: Decimal
    sample_size: int


def compute_performance_metrics(
    period_returns: Sequence[Decimal],
    turnovers: Sequence[Decimal] | None = None,
    periods_per_year: int = 252,
) -> PerformanceMetrics:
    cumulative = Decimal("1")
    peak = Decimal("1")
    max_drawdown = Decimal("0")
    for period_return in period_returns:
        cumulative *= Decimal("1") + period_return
        peak = max(peak, cumulative)
        drawdown = (cumulative / peak) - Decimal("1")
        if drawdown < max_drawdown:
            max_drawdown = drawdown
    total_return = cumulative - Decimal("1")
    average_return = _mean(period_returns)
    volatility = _std(period_returns)
    annualized_return = (Decimal("1") + average_return) ** periods_per_year - Decimal("1") if period_returns else Decimal("0")
    annualized_volatility = volatility * Decimal(str(sqrt(periods_per_year))) if volatility > 0 else Decimal("0")
    sharpe_ratio = Decimal("0") if annualized_volatility == 0 else annualized_return / annualized_volatility
    turnover_average = _mean(list(turnovers or []))
    return PerformanceMetrics(
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        turnover_average=turnover_average,
    )


def compute_information_coefficient(
    factor_values: Mapping[str, Decimal],
    future_returns: Mapping[str, Decimal],
) -> InformationCoefficientMetrics:
    shared = [instrument_id for instrument_id in factor_values if instrument_id in future_returns]
    if len(shared) < 2:
        return InformationCoefficientMetrics(ic=Decimal("0"), rank_ic=Decimal("0"), sample_size=len(shared))
    factor_series = [factor_values[instrument_id] for instrument_id in shared]
    return_series = [future_returns[instrument_id] for instrument_id in shared]
    ic = _correlation(factor_series, return_series)
    rank_ic = _correlation(_rank(factor_series), _rank(return_series))
    return InformationCoefficientMetrics(ic=ic, rank_ic=rank_ic, sample_size=len(shared))


def compute_sector_exposures(
    weights: Mapping[str, Decimal],
    sectors: Mapping[str, str],
) -> Dict[str, Decimal]:
    exposures: Dict[str, Decimal] = {}
    for instrument_id, weight in weights.items():
        sector = sectors.get(instrument_id, "UNKNOWN")
        exposures[sector] = exposures.get(sector, Decimal("0")) + weight
    return exposures


def compute_factor_exposure(
    weights: Mapping[str, Decimal],
    factor_values: Mapping[str, Decimal],
) -> Decimal:
    return sum(weights.get(instrument_id, Decimal("0")) * factor_values.get(instrument_id, Decimal("0")) for instrument_id in weights)


def compute_return_beta(
    asset_returns: Sequence[Decimal],
    benchmark_returns: Sequence[Decimal],
) -> BetaMetrics:
    paired = list(zip(asset_returns, benchmark_returns))
    if len(paired) < 2:
        return BetaMetrics(
            beta=Decimal("0"),
            correlation=Decimal("0"),
            asset_volatility=Decimal("0"),
            benchmark_volatility=Decimal("0"),
            sample_size=len(paired),
        )
    asset_series = [item[0] for item in paired]
    benchmark_series = [item[1] for item in paired]
    benchmark_variance = _std(benchmark_series) ** 2
    beta = Decimal("0") if benchmark_variance == 0 else _covariance(asset_series, benchmark_series) / benchmark_variance
    return BetaMetrics(
        beta=beta,
        correlation=_correlation(asset_series, benchmark_series),
        asset_volatility=_std(asset_series),
        benchmark_volatility=_std(benchmark_series),
        sample_size=len(paired),
    )
