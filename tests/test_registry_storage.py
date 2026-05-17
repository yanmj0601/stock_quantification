import sqlite3

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
    parameters = {
        "lookback": 60,
        "risk": {"stop_loss": 0.08, "tiers": [0.25, {"trail": 0.03}]},
    }

    created = registry.create_strategy(
        name="us_momentum_breakout",
        market=Market.US,
        asset_class="equity",
        template_id="momentum_breakout",
        parameters=parameters,
    )
    parameters["lookback"] = 10
    parameters["risk"]["stop_loss"] = 0.2
    parameters["risk"]["tiers"].append(0.5)

    assert created.parameters["lookback"] == 60
    assert created.parameters["risk"]["stop_loss"] == 0.08
    assert created.parameters["risk"]["tiers"] == (0.25, {"trail": 0.03})
    with pytest.raises(TypeError):
        created.parameters["lookback"] = 20
    with pytest.raises(TypeError):
        created.parameters["risk"]["stop_loss"] = 0.2
    with pytest.raises(AttributeError):
        created.parameters["risk"]["tiers"].append(0.5)
    with pytest.raises(TypeError):
        created.parameters["risk"]["tiers"][1]["trail"] = 0.1

    registry.record_metrics(created.id, {"sharpe": 1.42, "risk": {"drawdowns": [-0.08]}})
    fetched = registry.get_strategy(created.id)

    with pytest.raises(TypeError):
        fetched.metrics["sharpe"] = 0.0
    with pytest.raises(TypeError):
        fetched.metrics["risk"]["drawdowns"] = []
    with pytest.raises(AttributeError):
        fetched.metrics["risk"]["drawdowns"].append(-0.12)


def test_audit_event_payload_is_immutable_and_copied(tmp_path):
    registry = StrategyRegistry(SQLiteStore(tmp_path / "state.db"))
    strategy = registry.create_strategy(
        name="us_momentum_breakout",
        market=Market.US,
        asset_class="equity",
        template_id="momentum_breakout",
        parameters={"lookback": 60},
    )
    registry.record_metrics(strategy.id, {"nested": {"values": [1, {"score": 2}]}})

    events = registry.list_events(entity_id=strategy.id)

    with pytest.raises(TypeError):
        events[0].payload["name"] = "changed"
    metrics_event = events[1]
    with pytest.raises(TypeError):
        metrics_event.payload["nested"]["values"][1]["score"] = 3
    with pytest.raises(AttributeError):
        metrics_event.payload["nested"]["values"].append(4)


def test_set_status_records_from_to_payload_and_missing_id_has_no_status_audit(tmp_path):
    registry = StrategyRegistry(SQLiteStore(tmp_path / "state.db"))
    strategy = registry.create_strategy(
        name="us_momentum_breakout",
        market=Market.US,
        asset_class="equity",
        template_id="momentum_breakout",
        parameters={"lookback": 60},
    )

    promoted = registry.set_status(
        strategy.id,
        StrategyStatus.CANDIDATE,
        reason="validation passed",
    )

    assert promoted.status is StrategyStatus.CANDIDATE
    events = registry.list_events(entity_id=strategy.id)
    assert events[-1].event_type == "strategy.status_changed"
    assert events[-1].payload == {
        "from": StrategyStatus.RESEARCH.value,
        "to": StrategyStatus.CANDIDATE.value,
        "reason": "validation passed",
    }

    with pytest.raises(KeyError):
        registry.set_status("str_missing", StrategyStatus.CANDIDATE, reason="missing")

    assert [
        event.event_type
        for event in registry.list_events(entity_id="str_missing")
        if event.event_type == "strategy.status_changed"
    ] == []


def test_audit_events_with_same_timestamp_return_in_insertion_order(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    entity_id = "str_same_timestamp"
    timestamp = "2026-05-17T00:00:00+00:00"
    with store.connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_events (id, entity_id, event_type, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("evt_1", entity_id, "first", dumps({}), timestamp),
        )
        conn.execute(
            """
            INSERT INTO audit_events (id, entity_id, event_type, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("evt_2", entity_id, "second", dumps({}), timestamp),
        )

    events = StrategyRegistry(store).list_events(entity_id=entity_id)

    assert [event.event_type for event in events] == ["first", "second"]


def test_store_connection_commits_and_closes(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")

    with store.connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_events (id, entity_id, event_type, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "evt_closed",
                "str_closed",
                "closed",
                dumps({}),
                "2026-05-17T00:00:00+00:00",
            ),
        )

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")

    events = StrategyRegistry(store).list_events(entity_id="str_closed")
    assert [event.event_type for event in events] == ["closed"]
