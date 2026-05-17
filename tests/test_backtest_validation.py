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
    assert result.metrics["turnover"] == 0.6


def test_robustness_gate_blocks_weak_or_fragile_strategy():
    gate = RobustnessGate(min_sharpe=1.0, max_drawdown_floor=-0.20, min_cagr=0.01)

    assert gate.evaluate({"cagr": 0.12, "sharpe": 1.3, "max_drawdown": -0.08}).passed is True
    assert gate.evaluate({"cagr": 0.12, "sharpe": 0.4, "max_drawdown": -0.08}).passed is False
