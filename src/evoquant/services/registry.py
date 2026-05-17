from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from evoquant.domain import Market, StrategyStatus, new_id, utc_now
from evoquant.storage import SQLiteStore, dumps, loads


@dataclass(frozen=True)
class AuditEvent:
    id: str
    entity_id: str
    event_type: str
    payload: Mapping[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _deep_freeze(self.payload))


@dataclass(frozen=True)
class RegisteredStrategy:
    id: str
    name: str
    market: Market
    asset_class: str
    template_id: str
    parameters: Mapping[str, Any]
    status: StrategyStatus
    version: int
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _deep_freeze(self.parameters))
        object.__setattr__(self, "metrics", _deep_freeze(self.metrics))


class StrategyRegistry:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def create_strategy(
        self,
        name: str,
        market: Market,
        asset_class: str,
        template_id: str,
        parameters: dict[str, Any],
    ) -> RegisteredStrategy:
        now = utc_now()
        strategy = RegisteredStrategy(
            id=new_id("str"),
            name=name,
            market=market,
            asset_class=asset_class,
            template_id=template_id,
            parameters=parameters,
            status=StrategyStatus.RESEARCH,
            version=1,
        )
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO strategies (
                    id, name, market, asset_class, template_id, parameters, status,
                    version, metrics, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy.id,
                    strategy.name,
                    strategy.market.value,
                    strategy.asset_class,
                    strategy.template_id,
                    dumps(strategy.parameters),
                    strategy.status.value,
                    strategy.version,
                    dumps(strategy.metrics),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self._append_event(conn, strategy.id, "strategy.created", {"name": name})
        return strategy

    def get_strategy(self, strategy_id: str) -> RegisteredStrategy:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
        if row is None:
            raise KeyError(strategy_id)
        return RegisteredStrategy(
            id=row["id"],
            name=row["name"],
            market=Market(row["market"]),
            asset_class=row["asset_class"],
            template_id=row["template_id"],
            parameters=loads(row["parameters"]),
            status=StrategyStatus(row["status"]),
            version=row["version"],
            metrics=loads(row["metrics"]),
        )

    def record_metrics(self, strategy_id: str, metrics: dict[str, Any]) -> None:
        with self.store.connection() as conn:
            result = conn.execute(
                "UPDATE strategies SET metrics = ?, updated_at = ? WHERE id = ?",
                (dumps(metrics), utc_now().isoformat(), strategy_id),
            )
            if result.rowcount == 0:
                raise KeyError(strategy_id)
            self._append_event(conn, strategy_id, "strategy.metrics_recorded", metrics)

    def set_status(
        self,
        strategy_id: str,
        status: StrategyStatus,
        reason: str,
    ) -> RegisteredStrategy:
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM strategies WHERE id = ?", (strategy_id,)
            ).fetchone()
            if row is None:
                raise KeyError(strategy_id)
            current_status = StrategyStatus(row["status"])
            result = conn.execute(
                "UPDATE strategies SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, utc_now().isoformat(), strategy_id),
            )
            if result.rowcount == 0:
                raise KeyError(strategy_id)
            self._append_event(
                conn,
                strategy_id,
                "strategy.status_changed",
                {"from": current_status.value, "to": status.value, "reason": reason},
            )
        return self.get_strategy(strategy_id)

    def list_events(self, entity_id: str) -> list[AuditEvent]:
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE entity_id = ? ORDER BY created_at ASC, rowid ASC",
                (entity_id,),
            ).fetchall()
        return [
            AuditEvent(
                row["id"],
                row["entity_id"],
                row["event_type"],
                loads(row["payload"]),
                datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def _append_event(
        self,
        conn,
        entity_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_events (id, entity_id, event_type, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                new_id("evt"),
                entity_id,
                event_type,
                dumps(payload),
                utc_now().isoformat(),
            ),
        )


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _deep_freeze(nested) for key, nested in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(nested) for nested in value)
    return value
