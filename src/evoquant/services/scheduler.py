from __future__ import annotations

from dataclasses import dataclass

from evoquant.domain import Market, new_id, utc_now
from evoquant.storage import SQLiteStore


@dataclass(frozen=True)
class ScheduleConfig:
    id: str
    market: Market
    enabled: bool
    timezone: str
    run_time: str
    updated_at: str


class SchedulerService:
    def __init__(self, store: SQLiteStore):
        self.store = store
        self._ensure_defaults()

    def list_configs(self) -> list[ScheduleConfig]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, market, enabled, timezone, run_time, updated_at
                FROM schedule_configs
                ORDER BY market ASC
                """
            ).fetchall()
        return [
            ScheduleConfig(
                id=row["id"],
                market=Market(row["market"]),
                enabled=bool(row["enabled"]),
                timezone=row["timezone"],
                run_time=row["run_time"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def set_enabled(self, market: Market, enabled: bool) -> ScheduleConfig:
        self._ensure_defaults()
        now = utc_now().isoformat()
        with self.store.connection() as conn:
            conn.execute(
                """
                UPDATE schedule_configs
                SET enabled = ?, updated_at = ?
                WHERE market = ?
                """,
                (1 if enabled else 0, now, market.value),
            )
        return next(config for config in self.list_configs() if config.market is market)

    def _ensure_defaults(self) -> None:
        now = utc_now().isoformat()
        defaults = [
            (new_id("sched"), Market.CN.value, 1, "Asia/Shanghai", "15:30", now),
            (new_id("sched"), Market.US.value, 1, "America/New_York", "16:30", now),
        ]
        with self.store.connection() as conn:
            for row in defaults:
                exists = conn.execute(
                    "SELECT 1 FROM schedule_configs WHERE market = ?", (row[1],)
                ).fetchone()
                if exists is None:
                    conn.execute(
                        """
                        INSERT INTO schedule_configs (
                            id, market, enabled, timezone, run_time, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        row,
                    )
