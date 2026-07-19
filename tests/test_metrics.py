import pytest

from evoquant.metrics import calculate_performance


def test_calculate_performance_includes_return_risk_and_turnover():
    equity = [100_000, 102_000, 101_000, 106_000]
    turnovers = [0.2, 0.4, 0.1]

    metrics = calculate_performance(equity, turnovers, periods_per_year=252)

    assert round(metrics.total_return, 4) == 0.0600
    assert metrics.cagr > 0
    assert metrics.sharpe > 0
    assert metrics.max_drawdown < 0
    assert metrics.calmar > 0
    assert round(metrics.turnover, 4) == 0.7


@pytest.mark.parametrize("periods_per_year", [0, -252])
def test_calculate_performance_rejects_non_positive_periods_per_year(periods_per_year):
    with pytest.raises(ValueError, match="periods_per_year must be positive"):
        calculate_performance([100_000, 101_000], periods_per_year=periods_per_year)


def test_calculate_performance_rejects_non_positive_equity_values():
    with pytest.raises(ValueError, match="equity values must be positive"):
        calculate_performance([100_000, 0])


def test_calculate_performance_returns_zero_risk_for_flat_equity():
    metrics = calculate_performance([100_000, 100_000, 100_000])

    assert metrics.total_return == 0.0
    assert metrics.cagr == 0.0
    assert metrics.volatility == 0.0
    assert metrics.sharpe == 0.0
    assert metrics.sortino == 0.0
    assert metrics.max_drawdown == 0.0
    assert metrics.calmar == 0.0



