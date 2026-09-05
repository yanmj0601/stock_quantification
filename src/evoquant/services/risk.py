from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from evoquant.domain import RiskMode, new_id, utc_now
from evoquant.storage import PostgreSQLStore, dumps


_RISK_STATE_ID = "risk_state"


@dataclass(frozen=True)
class RiskState:
    mode: RiskMode
    live_enabled: bool
    updated_at: datetime


class RiskService:
    def __init__(self, store: PostgreSQLStore):
        self.store = store
        self._initialize_schema()

    def current(self) -> RiskState:
        return self._load_or_create_initial_state()

    def set_mode(self, mode: RiskMode, reason: str) -> RiskState:
        return self._persist_mode(mode, reason, live_enabled=False)

    def assert_paper_allowed(self) -> None:
        if self.current().mode is RiskMode.PAUSED:
            raise RuntimeError("paper trading is paused")

    def assert_live_disabled(self) -> None:
        if self.current().live_enabled:
            raise RuntimeError("live trading must remain disabled in v1")

    def _initialize_schema(self) -> None:
        with self.store.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_state (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    live_enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _load_or_create_initial_state(self) -> RiskState:
        with self.store.connection() as conn:
            row = conn.execute(
                """
                SELECT id, mode, live_enabled, updated_at
                FROM risk_state
                WHERE id = ?
                """,
                (_RISK_STATE_ID,),
            ).fetchone()
            if row is None:
                now = utc_now()
                conn.execute(
                    """
                    INSERT INTO risk_state (id, mode, live_enabled, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        _RISK_STATE_ID,
                        RiskMode.RESEARCH_ONLY.value,
                        0,
                        now.isoformat(),
                    ),
                )
                return RiskState(RiskMode.RESEARCH_ONLY, False, now)
        return self._state_from_row(row)

    def _persist_mode(
        self,
        mode: RiskMode,
        reason: str,
        live_enabled: bool,
    ) -> RiskState:
        current = self._load_or_create_initial_state()
        updated_at = utc_now()
        with self.store.connection() as conn:
            conn.execute(
                """
                UPDATE risk_state
                SET mode = ?, live_enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    mode.value,
                    int(live_enabled),
                    updated_at.isoformat(),
                    _RISK_STATE_ID,
                ),
            )
            self._append_event(
                conn,
                _RISK_STATE_ID,
                "risk.mode_changed",
                {
                    "from": current.mode.value,
                    "to": mode.value,
                    "reason": reason,
                    "live_enabled": live_enabled,
                },
            )
        return RiskState(mode, live_enabled, updated_at)

    def _append_event(
        self,
        conn,
        entity_id: str,
        event_type: str,
        payload: dict,
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

    def _state_from_row(self, row) -> RiskState:
        return RiskState(
            mode=RiskMode(row["mode"]),
            live_enabled=bool(row["live_enabled"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
