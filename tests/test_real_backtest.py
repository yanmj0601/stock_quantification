from datetime import date, timedelta

from evoquant.domain import Market
from evoquant.services.backtest import BacktestRunner
from evoquant.services.market_data import MarketBar


def _series(
    symbol: str, start_close: float, daily_step: float, days: int = 140
) -> list[MarketBar]:
    start = date(2025, 1, 1)
    bars = []
    for index in range(days):
        close = start_close + daily_step * index
        bars.append(
            MarketBar(
                symbol=symbol,
                market=Market.US,
                session=start + timedelta(days=index),
                open=close - 0.5,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
                amount=close * 1_000_000,
                adjusted=True,
                suspended=False,
                limit_up=False,
                limit_down=False,
                source="fixture",
            )
        )
    return bars


def test_real_backtest_runs_strategy_against_bars_and_returns_trades():
    bars = _series("AAA", 10, 1.0, days=160) + _series("BBB", 20, 0.2, days=160)

    result = BacktestRunner().run_signal_backtest(
        market=Market.US,
        universe=["AAA", "BBB"],
        bars=bars,
        parameters={
            "top_n": 1,
            "exit_rank": 2,
            "lookback_long": 120,
            "lookback_short": 20,
            "max_weight": 0.08,
            "min_amount": 1000,
            "max_volatility": 10,
            "max_drawdown": 1,
        },
        starting_cash=100_000,
    )

    assert result.metrics["total_return"] != 0
    assert result.trades
    assert result.equity_curve
    assert "avg_holding_days" in result.metrics
