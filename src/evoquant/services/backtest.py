from __future__ import annotations

from dataclasses import dataclass

from evoquant.metrics import calculate_performance


@dataclass(frozen=True)
class BacktestResult:
    metrics: dict[str, float]


class BacktestRunner:
    def run(self, equity: list[float], turnovers: list[float]) -> BacktestResult:
        metrics = calculate_performance(equity, turnovers)
        return BacktestResult(
            {
                "total_return": metrics.total_return,
                "cagr": metrics.cagr,
                "volatility": metrics.volatility,
                "sharpe": metrics.sharpe,
                "sortino": metrics.sortino,
                "max_drawdown": metrics.max_drawdown,
                "calmar": metrics.calmar,
                "turnover": round(metrics.turnover, 10),
            }
        )
