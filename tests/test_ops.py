from __future__ import annotations

import tempfile
from unittest import TestCase

from stock_quantification.ops import ProjectOpsStore


class ProjectOpsStoreTests(TestCase):
    def test_begin_and_finish_job_persist_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProjectOpsStore(tmpdir)
            reservation = store.begin_job("strategy_run", metadata={"market": "US"})
            self.assertTrue(reservation["accepted"])
            job_id = reservation["job"]["job_id"]
            state = store.load_state()
            self.assertEqual(state["active_job"]["job_id"], job_id)
            store.finish_job(job_id, "SUCCESS", detail="done", metadata={"count": 1})
            state = store.load_state()
            self.assertIsNone(state["active_job"])
            self.assertEqual(len(state["job_history"]), 1)
            self.assertEqual(state["job_history"][0]["status"], "SUCCESS")

    def test_begin_job_blocks_when_active_job_is_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProjectOpsStore(tmpdir)
            first = store.begin_job("strategy_run")
            self.assertTrue(first["accepted"])
            second = store.begin_job("factor_backtest")
            self.assertFalse(second["accepted"])
            self.assertEqual(second["active_job"]["kind"], "strategy_run")

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
            state = store.release_active_job(detail="released")
            self.assertIsNone(state["active_job"])
            self.assertEqual(state["job_history"][-1]["status"], "MANUAL_RELEASED")

    def test_update_active_job_persists_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProjectOpsStore(tmpdir)
            reservation = store.begin_job("strategy_run", metadata={"market": "US"})
            job_id = reservation["job"]["job_id"]
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
