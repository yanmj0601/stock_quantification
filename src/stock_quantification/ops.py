from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .sqlite_state import SQLiteStateStore


_PROCESS_PID = os.getpid()
_PROCESS_STARTED_AT = datetime.utcnow()


def _now() -> datetime:
    return datetime.utcnow()


class ProjectOpsStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._state = SQLiteStateStore(base_dir)
        self._state.mark_previous_running_jobs_stale(
            owner_pid=_PROCESS_PID,
            owner_started_at=_PROCESS_STARTED_AT.isoformat(timespec="seconds"),
        )

    def load_state(self) -> Dict[str, Any]:
        return {
            "updated_at": _now().isoformat(timespec="seconds"),
            "heartbeats": self._state.load_heartbeats(),
            "active_job": self._state.get_active_job(),
            "queued_jobs": self._state.list_queued_jobs(limit=200),
            "job_history": self._state.list_recent_jobs(limit=200),
            "audit_events": self._state.list_events(limit=400),
        }

    def heartbeat(self, component: str) -> Dict[str, Any]:
        self._state.save_heartbeat(component, _now().isoformat(timespec="seconds"))
        return self.load_state()

    @property
    def sqlite(self) -> SQLiteStateStore:
        return self._state

    def begin_job(
        self,
        kind: str,
        metadata: Optional[Dict[str, Any]] = None,
        stale_after_minutes: int = 30,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        del stale_after_minutes
        job = self._state.enqueue_job(kind, metadata=metadata, payload=payload)
        return {"accepted": True, "job": job}

    def claim_next_queued_job(self) -> Optional[Dict[str, Any]]:
        return self._state.claim_next_job(
            owner_pid=_PROCESS_PID,
            owner_started_at=_PROCESS_STARTED_AT.isoformat(timespec="seconds"),
        )

    def finish_job(
        self,
        job_id: str,
        status: str,
        detail: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._state.finish_job(job_id, status=status, detail=detail, metadata=metadata)
        return self.load_state()

    def append_event(
        self,
        category: str,
        action: str,
        status: str,
        detail: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._state.append_event(
            category=category,
            action=action,
            status=status,
            detail=detail,
            metadata=metadata,
        )
        return self.load_state()

    def list_events(self, limit: int = 400) -> list[Dict[str, Any]]:
        return self._state.list_events(limit=limit)

    def append_run_history(self, records: list[Dict[str, Any]]) -> None:
        self._state.append_run_history(records)

    def list_run_history(self, limit: int = 200) -> list[Dict[str, Any]]:
        return self._state.list_run_history(limit=limit)

    def release_active_job(
        self,
        detail: str = "Released active job manually.",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        active_job = self._state.get_active_job()
        if not active_job:
            return self.load_state()
        self._state.finish_job(
            active_job["job_id"],
            status="MANUAL_RELEASED",
            detail=detail,
            metadata=metadata,
        )
        return self.load_state()

    def update_active_job(
        self,
        job_id: str,
        *,
        progress_pct: Optional[int] = None,
        stage: Optional[str] = None,
        detail: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._state.update_job(
            job_id,
            progress_pct=progress_pct,
            stage=stage,
            detail=detail,
            metadata=metadata,
        )
        return self.load_state()
