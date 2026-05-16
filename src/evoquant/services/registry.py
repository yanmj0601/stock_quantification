from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from evoquant.domain import Market, StrategyStatus, new_id, utc_now
from evoquant.storage import SQLiteStore, dumps, loads


@dataclass(frozen=True)
class AuditEvent:
    id: str
    entity_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class RegisteredStrategy:
    id: str
    name: str
    market: Market
    asset_class: str
    template_id: str
    parameters: dict[str, Any]
    status: StrategyStatus
    version: int
    metrics: dict[str, float] = field(default_factory=dict)


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
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO strategies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        with self.store.connect() as conn:
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

    def record_metrics(self, strategy_id: str, metrics: dict[str, float]) -> None:
        with self.store.connect() as conn:
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
        current = self.get_strategy(strategy_id)
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE strategies SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, utc_now().isoformat(), strategy_id),
            )
            self._append_event(
                conn,
                strategy_id,
                "strategy.status_changed",
                {"from": current.status.value, "to": status.value, "reason": reason},
            )
        return self.get_strategy(strategy_id)

    def list_events(self, entity_id: str) -> list[AuditEvent]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE entity_id = ? ORDER BY created_at ASC",
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
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
            (
                new_id("evt"),
                entity_id,
                event_type,
                dumps(payload),
                utc_now().isoformat(),
            ),
        )
