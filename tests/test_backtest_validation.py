import pytest

from evoquant.services.backtest import BacktestRunner
from evoquant.services.validation import RobustnessGate


def test_backtest_runner_returns_required_metrics():
    runner = BacktestRunner()

    result = runner.run(
        equity=[100_000, 101_000, 103_000, 102_000, 108_000],
        turnovers=[0.1, 0.2, 0.2, 0.1],
    )

    assert result.metrics["cagr"] > 0
    assert "sharpe" in result.metrics
    assert "max_drawdown" in result.metrics
    assert "calmar" in result.metrics
    assert result.metrics["turnover"] == pytest.approx(0.6)


def test_backtest_result_metrics_are_immutable():
    runner = BacktestRunner()

    result = runner.run(equity=[100_000, 101_000, 103_000], turnovers=[0.1, 0.2])

    with pytest.raises(TypeError):
        result.metrics["cagr"] = 0.0


def test_robustness_gate_blocks_weak_or_fragile_strategy():
    gate = RobustnessGate(min_sharpe=1.0, max_drawdown_floor=-0.20, min_cagr=0.01)

    assert gate.evaluate({"cagr": 0.12, "sharpe": 1.3, "max_drawdown": -0.08}).passed is True
    assert gate.evaluate({"cagr": 0.12, "sharpe": 0.4, "max_drawdown": -0.08}).passed is False


def test_robustness_gate_blocks_excessive_drawdown_with_reason():
    gate = RobustnessGate(min_sharpe=1.0, max_drawdown_floor=-0.20, min_cagr=0.01)

    result = gate.evaluate({"cagr": 0.12, "sharpe": 1.3, "max_drawdown": -0.21})

    assert result.passed is False
    assert "drawdown below floor" in result.reasons


def test_robustness_gate_blocks_low_cagr_with_reason():
    gate = RobustnessGate(min_sharpe=1.0, max_drawdown_floor=-0.20, min_cagr=0.01)

    result = gate.evaluate({"cagr": 0.009, "sharpe": 1.3, "max_drawdown": -0.08})

    assert result.passed is False
    assert "cagr below threshold" in result.reasons


def test_robustness_gate_fails_closed_for_missing_required_metrics():
    gate = RobustnessGate(min_sharpe=1.0, max_drawdown_floor=-0.20, min_cagr=0.01)

    result = gate.evaluate({})

    assert result.passed is False
    assert result.reasons == ("missing sharpe", "missing max_drawdown", "missing cagr")


def test_robustness_gate_threshold_equality_passes():
    gate = RobustnessGate(min_sharpe=1.0, max_drawdown_floor=-0.20, min_cagr=0.01)

    result = gate.evaluate({"cagr": 0.01, "sharpe": 1.0, "max_drawdown": -0.20})

    assert result.passed is True
    assert result.reasons == ()


def test_gate_result_reasons_are_immutable():
    gate = RobustnessGate(min_sharpe=1.0, max_drawdown_floor=-0.20, min_cagr=0.01)

    result = gate.evaluate({"cagr": 0.12, "sharpe": 0.4, "max_drawdown": -0.08})

    with pytest.raises(AttributeError):
        result.reasons.append("extra reason")
