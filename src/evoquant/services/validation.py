from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str]


class RobustnessGate:
    def __init__(self, min_sharpe: float, max_drawdown_floor: float, min_cagr: float):
        self.min_sharpe = min_sharpe
        self.max_drawdown_floor = max_drawdown_floor
        self.min_cagr = min_cagr

    def evaluate(self, metrics: dict[str, float]) -> GateResult:
        reasons: list[str] = []
        if metrics.get("sharpe", 0.0) < self.min_sharpe:
            reasons.append("sharpe below threshold")
        if metrics.get("max_drawdown", -1.0) < self.max_drawdown_floor:
            reasons.append("drawdown below floor")
        if metrics.get("cagr", 0.0) < self.min_cagr:
            reasons.append("cagr below threshold")
        return GateResult(passed=not reasons, reasons=reasons)
