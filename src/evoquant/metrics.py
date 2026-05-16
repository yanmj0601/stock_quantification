from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    turnover: float


def calculate_performance(
    equity: list[float], turnovers: list[float] | None = None, periods_per_year: int = 252
) -> PerformanceMetrics:
    if len(equity) < 2:
        raise ValueError("equity series must contain at least two points")
    if any(value <= 0 for value in equity):
        raise ValueError("equity values must be positive")
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")

    returns = [(equity[i] / equity[i - 1]) - 1 for i in range(1, len(equity))]
    total_return = equity[-1] / equity[0] - 1
    years = max(len(returns) / periods_per_year, 1 / periods_per_year)
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1
    mean_return = sum(returns) / len(returns)
    variance = sum((ret - mean_return) ** 2 for ret in returns) / len(returns)
    volatility = sqrt(variance) * sqrt(periods_per_year)
    sharpe = 0.0 if volatility == 0 else mean_return / sqrt(variance) * sqrt(periods_per_year)
    downside = [min(0.0, ret) for ret in returns]
    downside_variance = sum(ret * ret for ret in downside) / len(downside)
    sortino = 0.0 if downside_variance == 0 else mean_return / sqrt(downside_variance) * sqrt(periods_per_year)
    peak = equity[0]
    max_drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1)
    calmar = 0.0 if max_drawdown == 0 else cagr / abs(max_drawdown)
    turnover = sum(turnovers or [])
    return PerformanceMetrics(total_return, cagr, volatility, sharpe, sortino, max_drawdown, calmar, turnover)


def paper_decay(backtest_cagr: float, paper_cagr: float) -> float:
    if backtest_cagr == 0:
        return 0.0
    return round((paper_cagr - backtest_cagr) / abs(backtest_cagr), 4)
