from datetime import date

import pytest

from evoquant.domain import (
    Bar,
    Instrument,
    Market,
    RiskMode,
    StrategyCandidate,
    StrategyStatus,
)


def test_instrument_supports_multi_market_metadata():
    instrument = Instrument(
        symbol="AAPL",
        market=Market.US,
        asset_class="equity",
        currency="USD",
        exchange="NASDAQ",
        lot_size=1,
        tradable=True,
    )

    assert instrument.symbol == "AAPL"
    assert instrument.market is Market.US
    assert instrument.lot_size == 1


def test_bar_carries_source_and_adjustment_metadata():
    bar = Bar(
        symbol="600519",
        market=Market.CN,
        session=date(2026, 1, 5),
        open=100.0,
        high=110.0,
        low=99.0,
        close=108.0,
        volume=123456,
        adjusted=True,
        source="fixture",
    )

    assert bar.adjusted is True
    assert bar.source == "fixture"


def test_safety_enums_match_spec():
    assert StrategyStatus.PAPER.value == "paper"
    assert StrategyStatus.PRODUCTION_READY.value == "production-ready"
    assert RiskMode.RESEARCH_ONLY.value == "research-only"


def test_strategy_candidate_parameters_are_immutable_and_copied():
    parameters = {"lookback": 20}
    candidate = StrategyCandidate(
        id="strategy_123",
        name="Breakout",
        market=Market.US,
        asset_class="equity",
        template_id="breakout_v1",
        parameters=parameters,
    )

    with pytest.raises(TypeError):
        candidate.parameters["lookback"] = 30

    parameters["lookback"] = 50

    assert candidate.parameters["lookback"] == 20
