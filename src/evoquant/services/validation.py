from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]


class RobustnessGate:
    def __init__(self, min_sharpe: float, max_drawdown_floor: float, min_cagr: float):
        self.min_sharpe = min_sharpe
        self.max_drawdown_floor = max_drawdown_floor
        self.min_cagr = min_cagr

    def evaluate(self, metrics: Mapping[str, float]) -> GateResult:
        reasons: list[str] = []
        required_metrics = ("sharpe", "max_drawdown", "cagr")
        missing_reasons = [f"missing {metric}" for metric in required_metrics if metric not in metrics]
        if missing_reasons:
            return GateResult(passed=False, reasons=tuple(missing_reasons))

        if metrics["sharpe"] < self.min_sharpe:
            reasons.append("sharpe below threshold")
        if metrics["max_drawdown"] < self.max_drawdown_floor:
            reasons.append("drawdown below floor")
        if metrics["cagr"] < self.min_cagr:
            reasons.append("cagr below threshold")
        return GateResult(passed=not reasons, reasons=tuple(reasons))
