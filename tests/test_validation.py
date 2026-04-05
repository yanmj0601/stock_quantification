from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest import TestCase

from stock_quantification.validation import (
    WalkForwardWindowResult,
    build_parameter_stability_report,
    build_train_validate_test_split,
    build_walk_forward_report,
    build_walk_forward_windows,
    serialize_parameter_stability_report,
    serialize_train_validate_test_split,
    serialize_walk_forward_report,
)


class ValidationTests(TestCase):
    def setUp(self) -> None:
        start = date(2025, 1, 1)
        self.trading_dates = [start + timedelta(days=index) for index in range(20)]

    def test_build_train_validate_test_split(self) -> None:
        split = build_train_validate_test_split(self.trading_dates, train_ratio=Decimal("0.50"), validate_ratio=Decimal("0.25"))
        serialized = serialize_train_validate_test_split(split)

        self.assertEqual(split.train.session_count, 10)
        self.assertEqual(split.validate.session_count, 5)
        self.assertEqual(split.test.session_count, 5)
        self.assertEqual(serialized["train"]["start_date"], self.trading_dates[0].isoformat())
        self.assertEqual(serialized["test"]["end_date"], self.trading_dates[-1].isoformat())

    def test_build_walk_forward_windows(self) -> None:
        windows = build_walk_forward_windows(
            self.trading_dates,
            train_sessions=8,
            validate_sessions=4,
            test_sessions=4,
            step_sessions=4,
        )
        report = build_walk_forward_report(
            windows,
            [
                WalkForwardWindowResult(
                    window_index=window.window_index,
                    scenario_name="baseline",
                    train_return=Decimal("0.01"),
                    validate_return=Decimal("0.02"),
                    test_return=Decimal("0.03"),
                    test_excess_return=Decimal("0.01"),
                    test_win_rate=Decimal("0.60"),
                )
                for window in windows
            ],
        )
        serialized = serialize_walk_forward_report(report)

        self.assertEqual(len(windows), 2)
        self.assertEqual(serialized["windows"][0]["train"]["session_count"], 8)
        self.assertEqual(serialized["windows"][0]["train"]["start_date"], self.trading_dates[0].isoformat())
        self.assertEqual(serialized["scenario_summaries"][0]["average_test_return"], "0.0300")

    def test_build_parameter_stability_report(self) -> None:
        report = build_parameter_stability_report(
            [
                WalkForwardWindowResult(
                    window_index=1,
                    scenario_name="stable",
                    train_return=Decimal("0.03"),
                    validate_return=Decimal("0.02"),
                    test_return=Decimal("0.018"),
                    validate_excess_return=Decimal("0.01"),
                    test_excess_return=Decimal("0.008"),
                    test_win_rate=Decimal("0.60"),
                ),
                WalkForwardWindowResult(
                    window_index=2,
                    scenario_name="stable",
                    train_return=Decimal("0.025"),
                    validate_return=Decimal("0.018"),
                    test_return=Decimal("0.017"),
                    validate_excess_return=Decimal("0.009"),
                    test_excess_return=Decimal("0.007"),
                    test_win_rate=Decimal("0.55"),
                ),
                WalkForwardWindowResult(
                    window_index=1,
                    scenario_name="fragile",
                    train_return=Decimal("0.08"),
                    validate_return=Decimal("0.06"),
                    test_return=Decimal("-0.01"),
                    validate_excess_return=Decimal("0.03"),
                    test_excess_return=Decimal("-0.01"),
                    test_win_rate=Decimal("0.30"),
                ),
                WalkForwardWindowResult(
                    window_index=2,
                    scenario_name="fragile",
                    train_return=Decimal("0.07"),
                    validate_return=Decimal("0.05"),
                    test_return=Decimal("0.00"),
                    validate_excess_return=Decimal("0.02"),
                    test_excess_return=Decimal("0.00"),
                    test_win_rate=Decimal("0.35"),
                ),
            ]
        )
        serialized = serialize_parameter_stability_report(report)

        self.assertEqual(report.recommended_scenario, "stable")
        self.assertEqual(serialized["recommended_scenario"], "stable")
        self.assertEqual(serialized["scenarios"][0]["scenario_name"], "stable")
