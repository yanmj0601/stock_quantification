from __future__ import annotations

import tempfile
from unittest import TestCase

from stock_quantification.artifacts import read_json_artifact, write_json_artifact, write_text_artifact
from stock_quantification.result_index import list_results, record_result


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
