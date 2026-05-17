from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from evoquant.metrics import calculate_performance


@dataclass(frozen=True)
class BacktestResult:
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


class BacktestRunner:
    def run(self, equity: list[float], turnovers: list[float]) -> BacktestResult:
        metrics = calculate_performance(equity, turnovers)
        result_metrics = {
            "total_return": metrics.total_return,
            "cagr": metrics.cagr,
            "volatility": metrics.volatility,
            "sharpe": metrics.sharpe,
            "sortino": metrics.sortino,
            "max_drawdown": metrics.max_drawdown,
            "calmar": metrics.calmar,
            "turnover": metrics.turnover,
        }
        return BacktestResult(MappingProxyType(result_metrics.copy()))
