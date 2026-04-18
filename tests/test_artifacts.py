from __future__ import annotations

import json
import threading
import tempfile
from unittest import TestCase
from unittest.mock import patch

from stock_quantification import artifacts as artifacts_module
from stock_quantification.artifacts import read_json_artifact, write_json_artifact, write_text_artifact
from stock_quantification.result_index import list_results, normalize_local_paper_run_summary, record_result


class ArtifactTests(TestCase):
    def test_write_and_read_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_json_artifact(tmpdir, "reports/test.json", {"alpha": 1})
            self.assertTrue(path.endswith("reports/test.json"))
            payload = read_json_artifact(tmpdir, "reports/test.json")
            self.assertEqual(payload["alpha"], 1)

    def test_write_text_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_text_artifact(tmpdir, "reports/test.md", "# hello\n")
            self.assertTrue(path.endswith("reports/test.md"))

    def test_record_result_upserts_and_lists_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            record_result(
                tmpdir,
                {
                    "result_id": "validation:cn:2026-03-31",
                    "artifact_kind": "validation_study",
                    "market": "CN",
                    "sort_date": "2026-03-31",
                    "summary": {"decision": "KEEP"},
                },
            )
            updated = record_result(
                tmpdir,
                {
                    "result_id": "validation:cn:2026-03-31",
                    "artifact_kind": "validation_study",
                    "market": "CN",
                    "sort_date": "2026-03-31",
                    "summary": {"decision": "REVIEW"},
                },
            )
            record_result(
                tmpdir,
                {
                    "result_id": "suite:us:2026-04-02",
                    "artifact_kind": "strategy_suite",
                    "market": "US",
                    "sort_date": "2026-04-02",
                    "summary": {"decision": "KEEP"},
                },
            )

            rows = list_results(tmpdir)

            self.assertEqual(updated["summary"]["decision"], "REVIEW")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["result_id"], "suite:us:2026-04-02")
            self.assertEqual(rows[1]["summary"]["decision"], "REVIEW")

    def test_list_results_supports_kind_and_market_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            record_result(
                tmpdir,
                {
                    "result_id": "validation:us:2026-03-31",
                    "artifact_kind": "validation_study",
                    "market": "US",
                    "sort_date": "2026-03-31",
                    "summary": {},
                },
            )
            record_result(
                tmpdir,
                {
                    "result_id": "suite:us:2026-03-31",
                    "artifact_kind": "strategy_suite",
                    "market": "US",
                    "sort_date": "2026-03-31",
                    "summary": {},
                },
            )
            record_result(
                tmpdir,
                {
                    "result_id": "suite:cn:2026-03-31",
                    "artifact_kind": "strategy_suite",
                    "market": "CN",
                    "sort_date": "2026-03-31",
                    "summary": {},
                },
            )

            us_suites = list_results(tmpdir, artifact_kind="strategy_suite", market="US")

            self.assertEqual(len(us_suites), 1)
            self.assertEqual(us_suites[0]["result_id"], "suite:us:2026-03-31")

    def test_list_results_skips_malformed_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_json_artifact(
                tmpdir,
                "web/result_index.json",
                {
                    "records": [
                        {"result_id": "good:1", "artifact_kind": "strategy_suite", "market": "US", "sort_date": "2026-03-31"},
                        "bad-row",
                        {"artifact_kind": "missing_id"},
                    ]
                },
            )

            rows = list_results(tmpdir)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["result_id"], "good:1")

    def test_normalize_local_paper_run_summary_uses_account_and_strategy_fields(self) -> None:
        payload = {
            "summary": {
                "account_id": "web-paper-us",
                "market": "US",
                "strategy_id": "us_quality_momentum",
                "trade_count": 3,
                "position_count": 5,
                "cash": "88000",
                "buying_power": "88000",
                "as_of": "2026-04-18T10:00:00",
            }
        }

        summary = normalize_local_paper_run_summary(payload)

        self.assertEqual(summary["subject_id"], "web-paper-us:us_quality_momentum")
        self.assertEqual(summary["subject_name"], "web-paper-us / us_quality_momentum")
        self.assertEqual(summary["decision"], "RECORDED")
        self.assertEqual(summary["score"], 3)
        self.assertEqual(summary["return"], "88000")
        self.assertIn("3 trades", summary["rationale"])

    def test_write_json_artifact_is_safe_under_competing_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first_dump_ready = threading.Event()
            second_replace_done = threading.Event()
            errors = []
            original_dump = json.dump
            original_replace = artifacts_module.Path.replace

            def controlled_dump(payload, handle, *args, **kwargs):
                payload_id = payload.get("id")
                if payload_id == 1:
                    original_dump(payload, handle, *args, **kwargs)
                    handle.flush()
                    first_dump_ready.set()
                    self.assertTrue(second_replace_done.wait(timeout=2))
                    return
                if payload_id == 2:
                    self.assertTrue(first_dump_ready.wait(timeout=2))
                original_dump(payload, handle, *args, **kwargs)

            def observed_replace(path_obj, target):
                content = path_obj.read_text(encoding="utf-8") if path_obj.exists() else ""
                result = original_replace(path_obj, target)
                if '"id": 2' in content:
                    second_replace_done.set()
                return result

            def writer(payload_id: int) -> None:
                try:
                    write_json_artifact(tmpdir, "reports/shared.json", {"id": payload_id})
                except Exception as exc:  # pragma: no cover - exercised by the pre-fix failure path
                    errors.append(exc)

            with patch("stock_quantification.artifacts.json.dump", side_effect=controlled_dump):
                with patch("pathlib.Path.replace", new=observed_replace):
                    thread_one = threading.Thread(target=writer, args=(1,))
                    thread_two = threading.Thread(target=writer, args=(2,))
                    thread_one.start()
                    thread_two.start()
                    thread_one.join(timeout=2)
                    thread_two.join(timeout=2)

            self.assertFalse(thread_one.is_alive())
            self.assertFalse(thread_two.is_alive())
            self.assertEqual(errors, [])
            payload = read_json_artifact(tmpdir, "reports/shared.json")
            self.assertIn(payload["id"], {1, 2})
