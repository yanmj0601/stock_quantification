from __future__ import annotations

from datetime import datetime, timedelta
from unittest import TestCase

from stock_quantification.data_quality import (
    DataQualityReport,
    DatasetSnapshot,
    build_dataset_quality_findings,
    build_missing_dataset_finding,
    build_stale_dataset_finding,
    build_zero_row_dataset_finding,
)


class DataQualityTests(TestCase):
    def test_dataset_snapshot_summary_includes_row_count_and_freshness(self) -> None:
        snapshot = DatasetSnapshot(
            dataset_name="daily_prices",
            row_count=120,
            updated_at=datetime(2026, 4, 18, 8, 0, 0),
        )

        summary = snapshot.summarize(
            as_of=datetime(2026, 4, 18, 9, 30, 0),
            stale_after=timedelta(minutes=60),
        )

        self.assertEqual(summary["dataset_name"], "daily_prices")
        self.assertEqual(summary["row_count"], 120)
        self.assertEqual(summary["freshness_minutes"], 90)
        self.assertEqual(summary["freshness_status"], "STALE")

    def test_dataset_snapshot_summary_treats_exact_stale_boundary_as_stale(self) -> None:
        snapshot = DatasetSnapshot(
            dataset_name="daily_prices",
            row_count=120,
            updated_at=datetime(2026, 4, 18, 8, 30, 0),
        )

        summary = snapshot.summarize(
            as_of=datetime(2026, 4, 18, 9, 30, 0),
            stale_after=timedelta(minutes=60),
        )

        self.assertEqual(summary["freshness_minutes"], 60)
        self.assertEqual(summary["freshness_status"], "STALE")

    def test_builders_cover_missing_zero_row_and_stale_datasets(self) -> None:
        snapshot = DatasetSnapshot(
            dataset_name="universe",
            row_count=0,
            updated_at=datetime(2026, 4, 18, 6, 0, 0),
        )

        missing = build_missing_dataset_finding("benchmark")
        zero_row = build_zero_row_dataset_finding(snapshot)
        stale = build_stale_dataset_finding(
            snapshot,
            as_of=datetime(2026, 4, 18, 9, 30, 0),
            stale_after=timedelta(minutes=60),
        )

        self.assertEqual(missing.severity, "CRITICAL")
        self.assertEqual(zero_row.code, "ZERO_ROW_DATASET")
        self.assertEqual(stale.severity, "WARN")

    def test_report_summary_returns_worst_overall_status(self) -> None:
        fresh = DatasetSnapshot(
            dataset_name="prices",
            row_count=25,
            updated_at=datetime(2026, 4, 18, 9, 20, 0),
        )
        stale = DatasetSnapshot(
            dataset_name="signals",
            row_count=10,
            updated_at=datetime(2026, 4, 18, 7, 0, 0),
        )

        report = DataQualityReport.from_snapshots(
            snapshots=[fresh, stale],
            missing_dataset_names=("benchmark",),
            as_of=datetime(2026, 4, 18, 9, 30, 0),
            stale_after=timedelta(minutes=60),
        )
        summary = report.summary()

        self.assertEqual(report.worst_severity(), "CRITICAL")
        self.assertEqual(summary["overall_status"], "CRITICAL")
        self.assertEqual(summary["overall_severity"], "CRITICAL")
        self.assertEqual(summary["snapshot_count"], 2)
        self.assertEqual(summary["finding_count"], 2)
        self.assertNotIn("findings", summary)

    def test_report_without_findings_is_ok(self) -> None:
        report = DataQualityReport(snapshots=[], findings=[])

        self.assertEqual(report.worst_severity(), "OK")
        self.assertEqual(report.summary()["overall_status"], "OK")

    def test_findings_without_as_of_skip_freshness_checks_deterministically(self) -> None:
        snapshot = DatasetSnapshot(
            dataset_name="signals",
            row_count=10,
            updated_at=datetime(2026, 4, 18, 7, 0, 0),
        )

        findings = build_dataset_quality_findings(
            snapshots=[snapshot],
            missing_dataset_names=("benchmark",),
        )

        self.assertEqual([finding.code for finding in findings], ["MISSING_DATASET"])

    def test_report_from_snapshots_without_as_of_is_deterministic(self) -> None:
        snapshot = DatasetSnapshot(
            dataset_name="signals",
            row_count=0,
            updated_at=None,
        )

        report = DataQualityReport.from_snapshots(
            snapshots=[snapshot],
            missing_dataset_names=("benchmark",),
        )

        self.assertEqual([finding.code for finding in report.findings], ["MISSING_DATASET", "ZERO_ROW_DATASET"])
        self.assertEqual(report.summary()["finding_count"], 2)

    def test_build_dataset_quality_findings_orders_missing_before_snapshot_issues(self) -> None:
        snapshot = DatasetSnapshot(
            dataset_name="turnover",
            row_count=0,
            updated_at=datetime(2026, 4, 18, 5, 0, 0),
        )

        findings = build_dataset_quality_findings(
            snapshots=[snapshot],
            missing_dataset_names=("benchmark",),
            as_of=datetime(2026, 4, 18, 9, 30, 0),
            stale_after=timedelta(minutes=60),
        )

        self.assertEqual([finding.code for finding in findings], ["MISSING_DATASET", "ZERO_ROW_DATASET", "STALE_DATASET"])

    def test_report_from_snapshots_materializes_generator_once(self) -> None:
        def snapshot_stream():
            yield DatasetSnapshot(
                dataset_name="prices",
                row_count=10,
                updated_at=datetime(2026, 4, 18, 9, 0, 0),
            )
            yield DatasetSnapshot(
                dataset_name="signals",
                row_count=0,
                updated_at=datetime(2026, 4, 18, 8, 0, 0),
            )

        report = DataQualityReport.from_snapshots(
            snapshots=snapshot_stream(),
            missing_dataset_names=("benchmark",),
            as_of=datetime(2026, 4, 18, 9, 30, 0),
            stale_after=timedelta(minutes=60),
        )

        self.assertEqual([snapshot.dataset_name for snapshot in report.snapshots], ["prices", "signals"])
        self.assertEqual([finding.code for finding in report.findings], ["MISSING_DATASET", "ZERO_ROW_DATASET", "STALE_DATASET"])
