import pytest

from evoquant.domain import Market, StrategyStatus
from evoquant.services.registry import StrategyRegistry
from evoquant.storage import SQLiteStore, dumps


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


def test_registered_strategy_mappings_are_immutable_and_copied(tmp_path):
    registry = StrategyRegistry(SQLiteStore(tmp_path / "state.db"))
    parameters = {"lookback": 60}

    created = registry.create_strategy(
        name="us_momentum_breakout",
        market=Market.US,
        asset_class="equity",
        template_id="momentum_breakout",
        parameters=parameters,
    )
    parameters["lookback"] = 10

    assert created.parameters["lookback"] == 60
    with pytest.raises(TypeError):
        created.parameters["lookback"] = 20

    registry.record_metrics(created.id, {"sharpe": 1.42})
    fetched = registry.get_strategy(created.id)

    with pytest.raises(TypeError):
        fetched.metrics["sharpe"] = 0.0


def test_audit_event_payload_is_immutable_and_copied(tmp_path):
    registry = StrategyRegistry(SQLiteStore(tmp_path / "state.db"))
    strategy = registry.create_strategy(
        name="us_momentum_breakout",
        market=Market.US,
        asset_class="equity",
        template_id="momentum_breakout",
        parameters={"lookback": 60},
    )

    events = registry.list_events(entity_id=strategy.id)

    with pytest.raises(TypeError):
        events[0].payload["name"] = "changed"


def test_set_status_does_not_append_audit_event_when_update_touches_zero_rows(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    registry = StrategyRegistry(store)
    strategy = registry.create_strategy(
        name="us_momentum_breakout",
        market=Market.US,
        asset_class="equity",
        template_id="momentum_breakout",
        parameters={"lookback": 60},
    )

    original_connect = store.connect
    calls = 0

    def delete_before_update():
        nonlocal calls
        calls += 1
        if calls == 2:
            with original_connect() as conn:
                conn.execute("DELETE FROM strategies WHERE id = ?", (strategy.id,))
        return original_connect()

    store.connect = delete_before_update

    with pytest.raises(KeyError) as error:
        registry.set_status(strategy.id, StrategyStatus.CANDIDATE, reason="missing")

    assert error.value.args == (strategy.id,)
    assert [event.event_type for event in registry.list_events(strategy.id)] == [
        "strategy.created"
    ]


def test_audit_events_with_same_timestamp_return_in_insertion_order(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    entity_id = "str_same_timestamp"
    timestamp = "2026-05-17T00:00:00+00:00"
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
            ("evt_1", entity_id, "first", dumps({}), timestamp),
        )
        conn.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
            ("evt_2", entity_id, "second", dumps({}), timestamp),
        )

    events = StrategyRegistry(store).list_events(entity_id=entity_id)

    assert [event.event_type for event in events] == ["first", "second"]
