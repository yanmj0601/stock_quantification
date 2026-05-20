from datetime import date, timedelta

import pytest

from evoquant.domain import Market, SignalSide
from evoquant.services.instruments import InstrumentMaster, InstrumentRecord
from evoquant.services.market_data import MarketBar
from evoquant.services.signals import SignalScanner
from evoquant.services.strategies import (
    CrossSectionalMomentumStrategy,
    PortfolioConstructor,
)
from evoquant.storage import SQLiteStore


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


def test_cross_sectional_momentum_buys_top_20_and_sells_outside_exit_rank():
    bars = _series("AAA", 10, 1.0) + _series("BBB", 10, 0.1) + _series("CCC", 30, -0.1)
    strategy = CrossSectionalMomentumStrategy(
        {
            "top_n": 1,
            "exit_rank": 2,
            "lookback_long": 120,
            "lookback_short": 20,
            "max_weight": 0.08,
            "min_amount": 1000,
            "max_volatility": 10,
            "max_drawdown": 1,
        }
    )

    signals = strategy.generate(
        Market.US, ["AAA", "BBB", "CCC"], bars, current_positions={"CCC": 100}
    )
    by_symbol = {signal.symbol: signal for signal in signals}

    assert by_symbol["AAA"].signal is SignalSide.BUY
    assert by_symbol["CCC"].signal is SignalSide.SELL
    assert "120日动量" in by_symbol["AAA"].reason


def test_score_weighted_portfolio_caps_single_name_weight():
    constructor = PortfolioConstructor(max_weight=0.08)

    weighted = constructor.assign_weights(
        [
            ("AAA", Market.US, 10.0),
            ("BBB", Market.US, 5.0),
        ]
    )

    assert weighted[("AAA", Market.US)] == pytest.approx(0.08)
    assert weighted[("BBB", Market.US)] <= 0.08


def test_insufficient_data_is_not_buyable():
    strategy = CrossSectionalMomentumStrategy(
        {
            "top_n": 1,
            "exit_rank": 2,
            "lookback_long": 120,
            "lookback_short": 20,
            "max_weight": 0.08,
            "min_amount": 1000,
            "max_volatility": 10,
            "max_drawdown": 1,
        }
    )

    signal = strategy.generate(
        Market.US,
        ["AAA"],
        _series("AAA", 10, 1.0, days=20),
        current_positions={},
    )[0]

    assert signal.signal is SignalSide.HOLD
    assert signal.target_weight == 0
    assert "insufficient_data" in signal.risk_flags


def test_signal_scanner_persists_scan_and_results(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    bars = _series("AAA", 10, 1.0) + _series("BBB", 10, 0.1)
    scanner = SignalScanner(store)

    scan = scanner.run_scan(
        strategy_template="cross_sectional_momentum",
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
        market_scope=[Market.US],
        universe={Market.US: ["AAA", "BBB"]},
        bars=bars,
        coverage={Market.US: 1.0},
        current_positions={},
    )
    results = scanner.list_results(scan.id)

    assert scan.status == "success"
    assert len(results) == 2
    assert results[0].rank == 1
    assert results[0].name_zh


def test_signal_scanner_enriches_results_from_instrument_master(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    InstrumentMaster(store).upsert_many(
        [
            InstrumentRecord(
                symbol="AAA",
                market=Market.US,
                name="Alpha Corp",
                name_zh="阿尔法公司",
                exchange="NASDAQ",
                currency="USD",
                sector="Technology",
                index_membership="SP500",
                tradable=True,
                lot_size=1,
            )
        ]
    )
    scanner = SignalScanner(store)

    scan = scanner.run_scan(
        strategy_template="cross_sectional_momentum",
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
        market_scope=[Market.US],
        universe={Market.US: ["AAA"]},
        bars=_series("AAA", 10, 1.0),
        coverage={Market.US: 1.0},
        current_positions={},
    )

    result = scanner.list_results(scan.id)[0]
    assert result.name == "Alpha Corp"
    assert result.name_zh == "阿尔法公司"


def test_signal_scanner_fails_market_below_coverage_threshold(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    bars = _series("AAA", 10, 1.0)
    scanner = SignalScanner(store)

    scan = scanner.run_scan(
        strategy_template="cross_sectional_momentum",
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
        market_scope=[Market.US],
        universe={Market.US: ["AAA"]},
        bars=bars,
        coverage={Market.US: 0.69},
        current_positions={},
    )

    assert scan.status == "failed"
    assert "coverage below 70%" in scan.error_message
    assert scanner.list_results(scan.id) == []
