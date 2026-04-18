from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

from .artifacts import read_json_artifact, write_json_artifact


OPS_STATE_RELATIVE_PATH = "web/ops_state.json"


def _now() -> datetime:
    return datetime.utcnow()


def _parse_datetime(value: object) -> Optional[datetime]:
    raw = str(value or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class ProjectOpsStore:
    def __init__(self, base_dir: str | Path, relative_path: str = OPS_STATE_RELATIVE_PATH) -> None:
        self._base_dir = Path(base_dir)
        self._relative_path = relative_path

    def load_state(self) -> Dict[str, Any]:
        payload = read_json_artifact(self._base_dir, self._relative_path)
        state = self._default_state()
        if not isinstance(payload, dict):
            return state
        for key in ("heartbeats", "audit_events", "job_history"):
            value = payload.get(key)
            if isinstance(value, dict) and key == "heartbeats":
                state[key] = value
            elif isinstance(value, list):
                state[key] = value
        if isinstance(payload.get("active_job"), dict):
            state["active_job"] = payload["active_job"]
        if payload.get("updated_at"):
            state["updated_at"] = payload["updated_at"]
        return state

    def heartbeat(self, component: str) -> Dict[str, Any]:
        state = self.load_state()
        state["heartbeats"][component] = _now().isoformat(timespec="seconds")
        self._save_state(state)
        return state

    def begin_job(
        self,
        kind: str,
        metadata: Optional[Dict[str, Any]] = None,
        stale_after_minutes: int = 30,
    ) -> Dict[str, Any]:
        state = self.load_state()
        active_job = state.get("active_job")
        now = _now()
        if isinstance(active_job, dict):
            started_at = _parse_datetime(active_job.get("started_at"))
            if started_at is not None and now - started_at > timedelta(minutes=stale_after_minutes):
                state["job_history"].append(
                    {
                        **active_job,
                        "finished_at": now.isoformat(timespec="seconds"),
                        "duration_seconds": int((now - started_at).total_seconds()),
                        "status": "STALE",
                        "detail": "Recovered stale active job lock.",
                    }
                )
                state["active_job"] = None
            else:
                return {"accepted": False, "active_job": active_job}

        job_id = hashlib.sha1(f"{kind}|{now.isoformat()}|{metadata}".encode("utf-8")).hexdigest()[:12]
        job = {
            "job_id": job_id,
            "kind": kind,
            "status": "RUNNING",
            "started_at": now.isoformat(timespec="seconds"),
            "progress_pct": 0,
            "stage": "QUEUED",
            "detail": "Task accepted and waiting to start.",
            "metadata": metadata or {},
        }
        state["active_job"] = job
        self._save_state(state)
        return {"accepted": True, "job": job}

    def finish_job(
        self,
        job_id: str,
        status: str,
        detail: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = self.load_state()
        active_job = state.get("active_job")
        now = _now()
        if not isinstance(active_job, dict) or active_job.get("job_id") != job_id:
            return state
        started_at = _parse_datetime(active_job.get("started_at")) or now
        state["job_history"].append(
            {
                **active_job,
                "finished_at": now.isoformat(timespec="seconds"),
                "duration_seconds": int((now - started_at).total_seconds()),
                "status": status,
                "detail": detail,
                "result_metadata": metadata or {},
            }
        )
        state["job_history"] = state["job_history"][-200:]
        state["active_job"] = None
        self._save_state(state)
        return state

    def append_event(
        self,
        category: str,
        action: str,
        status: str,
        detail: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = self.load_state()
        state["audit_events"].append(
            {
                "created_at": _now().isoformat(timespec="seconds"),
                "category": category,
                "action": action,
                "status": status,
                "detail": detail,
                "metadata": metadata or {},
            }
        )
        state["audit_events"] = state["audit_events"][-400:]
        self._save_state(state)
        return state

    def release_active_job(
        self,
        detail: str = "Released active job manually.",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = self.load_state()
        active_job = state.get("active_job")
        now = _now()
        if not isinstance(active_job, dict):
            return state
        started_at = _parse_datetime(active_job.get("started_at")) or now
        state["job_history"].append(
            {
                **active_job,
                "finished_at": now.isoformat(timespec="seconds"),
                "duration_seconds": int((now - started_at).total_seconds()),
                "status": "MANUAL_RELEASED",
                "detail": detail,
                "result_metadata": metadata or {},
            }
        )
        state["job_history"] = state["job_history"][-200:]
        state["active_job"] = None
        self._save_state(state)
        return state

    def update_active_job(
        self,
        job_id: str,
        *,
        progress_pct: Optional[int] = None,
        stage: Optional[str] = None,
        detail: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = self.load_state()
        active_job = state.get("active_job")
        if not isinstance(active_job, dict) or active_job.get("job_id") != job_id:
            return state
        updated = dict(active_job)
        if progress_pct is not None:
            updated["progress_pct"] = max(0, min(100, int(progress_pct)))
        if stage is not None:
            updated["stage"] = stage
        if detail is not None:
            updated["detail"] = detail
        merged_metadata = dict(updated.get("metadata", {}))
        if metadata:
            merged_metadata.update(metadata)
        updated["metadata"] = merged_metadata
        state["active_job"] = updated
        self._save_state(state)
        return state

    def _save_state(self, payload: Dict[str, Any]) -> str:
        payload = dict(payload)
        payload["updated_at"] = _now().isoformat(timespec="seconds")
        return write_json_artifact(self._base_dir, self._relative_path, payload)

    def _default_state(self) -> Dict[str, Any]:
        return {
            "updated_at": _now().isoformat(timespec="seconds"),
            "heartbeats": {},
            "active_job": None,
            "job_history": [],
            "audit_events": [],
        }
