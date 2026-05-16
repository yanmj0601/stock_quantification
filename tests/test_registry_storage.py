import pytest

from evoquant.domain import Market, StrategyStatus
from evoquant.services.registry import StrategyRegistry
from evoquant.storage import SQLiteStore


def test_strategy_registry_persists_versions_metrics_and_audit(tmp_path):
    registry = StrategyRegistry(SQLiteStore(tmp_path / "state.db"))

    strategy = registry.create_strategy(
        name="us_momentum_breakout",
        market=Market.US,
        asset_class="equity",
        template_id="momentum_breakout",
        parameters={"lookback": 60},
    )
    registry.record_metrics(
        strategy.id,
        {"cagr": 0.18, "sharpe": 1.42, "max_drawdown": -0.08},
    )
    promoted = registry.set_status(
        strategy.id,
        StrategyStatus.CANDIDATE,
        reason="validation passed",
    )

    assert promoted.status is StrategyStatus.CANDIDATE
    assert registry.get_strategy(strategy.id).metrics["sharpe"] == 1.42
    events = registry.list_events(entity_id=strategy.id)
    assert [event.event_type for event in events] == [
        "strategy.created",
        "strategy.metrics_recorded",
        "strategy.status_changed",
    ]


def test_record_metrics_rejects_missing_strategy_id(tmp_path):
    registry = StrategyRegistry(SQLiteStore(tmp_path / "state.db"))

    with pytest.raises(KeyError) as error:
        registry.record_metrics("str_missing", {"sharpe": 0.0})

    assert error.value.args == ("str_missing",)
    assert registry.list_events(entity_id="str_missing") == []
