from __future__ import annotations

import tempfile
from datetime import timedelta
from unittest import TestCase

from stock_quantification import ops as ops_module
from stock_quantification.ops import ProjectOpsStore
from stock_quantification.artifacts import write_json_artifact


class ProjectOpsStoreTests(TestCase):
    def test_begin_and_finish_job_persist_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProjectOpsStore(tmpdir)
            reservation = store.begin_job("strategy_run", metadata={"market": "US"})
            self.assertTrue(reservation["accepted"])
            job_id = reservation["job"]["job_id"]
            claimed = store.claim_next_queued_job()
            self.assertIsNotNone(claimed)
            state = store.load_state()
            self.assertEqual(state["active_job"]["job_id"], job_id)
            store.finish_job(job_id, "SUCCESS", detail="done", metadata={"count": 1})
            state = store.load_state()
            self.assertIsNone(state["active_job"])
            self.assertEqual(len(state["job_history"]), 1)
            self.assertEqual(state["job_history"][0]["status"], "SUCCESS")

    def test_begin_job_enqueues_when_another_job_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProjectOpsStore(tmpdir)
            first = store.begin_job("strategy_run")
            self.assertTrue(first["accepted"])
            claimed = store.claim_next_queued_job()
            self.assertIsNotNone(claimed)
            second = store.begin_job("factor_backtest")
            self.assertTrue(second["accepted"])
            state = store.load_state()
            self.assertEqual(state["active_job"]["kind"], "strategy_run")
            self.assertEqual(len(state["queued_jobs"]), 1)
            self.assertEqual(state["queued_jobs"][0]["kind"], "factor_backtest")

    def test_append_event_persists_audit_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProjectOpsStore(tmpdir)
            store.append_event("runtime", "strategy_run", "SUCCESS", "ok", {"market": "US"})
            state = store.load_state()
            self.assertEqual(len(state["audit_events"]), 1)
            self.assertEqual(state["audit_events"][0]["category"], "runtime")

    def test_release_active_job_moves_it_to_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProjectOpsStore(tmpdir)
            reservation = store.begin_job("factor_backtest")
            self.assertTrue(reservation["accepted"])
            store.claim_next_queued_job()
            state = store.release_active_job(detail="released")
            self.assertIsNone(state["active_job"])
            self.assertEqual(state["job_history"][-1]["status"], "MANUAL_RELEASED")

    def test_update_active_job_persists_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProjectOpsStore(tmpdir)
            reservation = store.begin_job("strategy_run", metadata={"market": "US"})
            job_id = reservation["job"]["job_id"]
            store.claim_next_queued_job()
            state = store.update_active_job(
                job_id,
                progress_pct=42,
                stage="RUNNING_MARKET",
                detail="running us market",
                metadata={"completed_markets": 1},
            )
            self.assertEqual(state["active_job"]["progress_pct"], 42)
            self.assertEqual(state["active_job"]["stage"], "RUNNING_MARKET")
            self.assertEqual(state["active_job"]["detail"], "running us market")
            self.assertEqual(state["active_job"]["metadata"]["completed_markets"], 1)

    def test_begin_job_recovers_legacy_active_job_from_previous_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_started_at = (ops_module._PROCESS_STARTED_AT - timedelta(seconds=5)).isoformat(timespec="seconds")
            write_json_artifact(
                tmpdir,
                "web/ops_state.json",
                {
                    "heartbeats": {},
                    "active_job": {
                        "job_id": "legacy-lock",
                        "kind": "strategy_run",
                        "status": "RUNNING",
                        "started_at": legacy_started_at,
                        "progress_pct": 45,
                        "stage": "RUNNING_MARKET",
                        "detail": "legacy lock from previous process",
                        "metadata": {"markets": ["US"]},
                    },
                    "job_history": [],
                    "audit_events": [],
                },
            )

            store = ProjectOpsStore(tmpdir)
            reservation = store.begin_job("factor_backtest")

            self.assertTrue(reservation["accepted"])
            state = store.load_state()
            self.assertEqual(state["job_history"][-1]["status"], "STALE")
            self.assertEqual(state["job_history"][-1]["job_id"], "legacy-lock")
            self.assertIsNone(state["active_job"])
            self.assertEqual(state["queued_jobs"][0]["kind"], "factor_backtest")
