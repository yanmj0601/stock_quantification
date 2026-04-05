from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from math import floor, sqrt
from typing import Dict, Iterable, List, Mapping, Sequence


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _std(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / Decimal(len(values) - 1)
    return Decimal(str(sqrt(float(variance))))


@dataclass(frozen=True)
class DateSlice:
    label: str
    start_date: date
    end_date: date
    session_count: int


@dataclass(frozen=True)
class TrainValidateTestSplit:
    train: DateSlice
    validate: DateSlice
    test: DateSlice


@dataclass(frozen=True)
class WalkForwardWindow:
    window_index: int
    train: DateSlice
    validate: DateSlice
    test: DateSlice


@dataclass(frozen=True)
class WalkForwardWindowResult:
    window_index: int
    scenario_name: str
    train_return: Decimal
    validate_return: Decimal
    test_return: Decimal
    train_excess_return: Decimal = Decimal("0")
    validate_excess_return: Decimal = Decimal("0")
    test_excess_return: Decimal = Decimal("0")
    train_win_rate: Decimal = Decimal("0")
    validate_win_rate: Decimal = Decimal("0")
    test_win_rate: Decimal = Decimal("0")
    train_observations: int = 0
    validate_observations: int = 0
    test_observations: int = 0


@dataclass(frozen=True)
class WalkForwardScenarioSummary:
    scenario_name: str
    window_count: int
    average_train_return: Decimal
    average_validate_return: Decimal
    average_test_return: Decimal
    average_train_excess_return: Decimal
    average_validate_excess_return: Decimal
    average_test_excess_return: Decimal
    average_train_win_rate: Decimal
    average_validate_win_rate: Decimal
    average_test_win_rate: Decimal
    test_return_std: Decimal
    validate_test_gap: Decimal


@dataclass(frozen=True)
class WalkForwardReport:
    windows: List[WalkForwardWindow]
    scenario_summaries: List[WalkForwardScenarioSummary]


@dataclass(frozen=True)
class ParameterStabilityScenario:
    scenario_name: str
    average_validate_return: Decimal
    average_test_return: Decimal
    average_validate_excess_return: Decimal
    average_test_excess_return: Decimal
    validate_test_gap: Decimal
    test_return_std: Decimal
    average_test_win_rate: Decimal
    positive_test_windows: int
    total_windows: int
    stability_score: Decimal


@dataclass(frozen=True)
class ParameterStabilityReport:
    recommended_scenario: str
    scenarios: List[ParameterStabilityScenario]


def build_train_validate_test_split(
    trading_dates: Sequence[date],
    train_ratio: Decimal | float = Decimal("0.60"),
    validate_ratio: Decimal | float = Decimal("0.20"),
) -> TrainValidateTestSplit:
    if len(trading_dates) < 3:
        raise ValueError("Need at least 3 trading dates")
    train_ratio_decimal = _to_decimal(train_ratio)
    validate_ratio_decimal = _to_decimal(validate_ratio)
    if train_ratio_decimal <= 0 or validate_ratio_decimal <= 0:
        raise ValueError("Ratios must be positive")
    if train_ratio_decimal + validate_ratio_decimal >= 1:
        raise ValueError("train_ratio + validate_ratio must be less than 1")

    total = len(trading_dates)
    train_count = max(1, int(floor(total * float(train_ratio_decimal))))
    validate_count = max(1, int(floor(total * float(validate_ratio_decimal))))
    remaining = total - train_count - validate_count
    if remaining <= 0:
        validate_count = max(1, validate_count - 1)
        remaining = total - train_count - validate_count
    if remaining <= 0:
        train_count = max(1, train_count - 1)
        remaining = total - train_count - validate_count
    if remaining <= 0:
        raise ValueError("Not enough dates to form test split")

    train_dates = list(trading_dates[:train_count])
    validate_dates = list(trading_dates[train_count : train_count + validate_count])
    test_dates = list(trading_dates[train_count + validate_count :])
    return TrainValidateTestSplit(
        train=_slice("train", train_dates),
        validate=_slice("validate", validate_dates),
        test=_slice("test", test_dates),
    )


def build_walk_forward_windows(
    trading_dates: Sequence[date],
    train_sessions: int,
    validate_sessions: int,
    test_sessions: int,
    step_sessions: int | None = None,
) -> List[WalkForwardWindow]:
    if min(train_sessions, validate_sessions, test_sessions) <= 0:
        raise ValueError("Window sizes must be positive")
    if step_sessions is None:
        step_sessions = test_sessions
    if step_sessions <= 0:
        raise ValueError("step_sessions must be positive")

    windows: List[WalkForwardWindow] = []
    total = len(trading_dates)
    start_index = 0
    window_index = 1
    while start_index + train_sessions + validate_sessions + test_sessions <= total:
        train_dates = list(trading_dates[start_index : start_index + train_sessions])
        validate_start = start_index + train_sessions
        validate_dates = list(trading_dates[validate_start : validate_start + validate_sessions])
        test_start = validate_start + validate_sessions
        test_dates = list(trading_dates[test_start : test_start + test_sessions])
        windows.append(
            WalkForwardWindow(
                window_index=window_index,
                train=_slice("train", train_dates),
                validate=_slice("validate", validate_dates),
                test=_slice("test", test_dates),
            )
        )
        start_index += step_sessions
        window_index += 1
    return windows


def build_walk_forward_report(
    windows: Sequence[WalkForwardWindow],
    results: Sequence[WalkForwardWindowResult],
) -> WalkForwardReport:
    grouped: Dict[str, List[WalkForwardWindowResult]] = {}
    for result in results:
        grouped.setdefault(result.scenario_name, []).append(result)

    summaries = [
        WalkForwardScenarioSummary(
            scenario_name=scenario_name,
            window_count=len(rows),
            average_train_return=_mean([row.train_return for row in rows]),
            average_validate_return=_mean([row.validate_return for row in rows]),
            average_test_return=_mean([row.test_return for row in rows]),
            average_train_excess_return=_mean([row.train_excess_return for row in rows]),
            average_validate_excess_return=_mean([row.validate_excess_return for row in rows]),
            average_test_excess_return=_mean([row.test_excess_return for row in rows]),
            average_train_win_rate=_mean([row.train_win_rate for row in rows]),
            average_validate_win_rate=_mean([row.validate_win_rate for row in rows]),
            average_test_win_rate=_mean([row.test_win_rate for row in rows]),
            test_return_std=_std([row.test_return for row in rows]),
            validate_test_gap=_mean([row.validate_return - row.test_return for row in rows]),
        )
        for scenario_name, rows in grouped.items()
    ]
    summaries.sort(key=lambda item: item.average_test_return, reverse=True)
    return WalkForwardReport(windows=list(windows), scenario_summaries=summaries)


def build_parameter_stability_report(
    results: Sequence[WalkForwardWindowResult],
) -> ParameterStabilityReport:
    grouped: Dict[str, List[WalkForwardWindowResult]] = {}
    for result in results:
        grouped.setdefault(result.scenario_name, []).append(result)
    scenarios: List[ParameterStabilityScenario] = []
    for scenario_name, rows in grouped.items():
        avg_validate = _mean([row.validate_return for row in rows])
        avg_test = _mean([row.test_return for row in rows])
        avg_validate_excess = _mean([row.validate_excess_return for row in rows])
        avg_test_excess = _mean([row.test_excess_return for row in rows])
        avg_test_win_rate = _mean([row.test_win_rate for row in rows])
        gap = avg_validate - avg_test
        test_std = _std([row.test_return for row in rows])
        positive_test_windows = sum(1 for row in rows if row.test_return > 0)
        stability_score = avg_test - abs(gap) - (test_std / Decimal("2")) + (avg_test_win_rate / Decimal("10"))
        scenarios.append(
            ParameterStabilityScenario(
                scenario_name=scenario_name,
                average_validate_return=avg_validate,
                average_test_return=avg_test,
                average_validate_excess_return=avg_validate_excess,
                average_test_excess_return=avg_test_excess,
                validate_test_gap=gap,
                test_return_std=test_std,
                average_test_win_rate=avg_test_win_rate,
                positive_test_windows=positive_test_windows,
                total_windows=len(rows),
                stability_score=stability_score,
            )
        )
    scenarios.sort(key=lambda item: item.stability_score, reverse=True)
    recommended = scenarios[0].scenario_name if scenarios else ""
    return ParameterStabilityReport(recommended_scenario=recommended, scenarios=scenarios)


def serialize_train_validate_test_split(split: TrainValidateTestSplit) -> Dict[str, object]:
    return {
        "train": _serialize_date_slice(split.train),
        "validate": _serialize_date_slice(split.validate),
        "test": _serialize_date_slice(split.test),
    }


def serialize_walk_forward_report(report: WalkForwardReport) -> Dict[str, object]:
    return {
        "windows": [
            {
                "window_index": window.window_index,
                "train": _serialize_date_slice(window.train),
                "validate": _serialize_date_slice(window.validate),
                "test": _serialize_date_slice(window.test),
            }
            for window in report.windows
        ],
        "scenario_summaries": [_serialize_dataclass(row) for row in report.scenario_summaries],
    }


def serialize_parameter_stability_report(report: ParameterStabilityReport) -> Dict[str, object]:
    return {
        "recommended_scenario": report.recommended_scenario,
        "scenarios": [_serialize_dataclass(item) for item in report.scenarios],
    }


def _serialize_dataclass(item) -> Dict[str, object]:
    payload = asdict(item)
    for key, value in payload.items():
        if isinstance(value, Decimal):
            payload[key] = str(value.quantize(Decimal("0.0001")))
        elif isinstance(value, date):
            payload[key] = value.isoformat()
    return payload


def _serialize_date_slice(item: DateSlice) -> Dict[str, object]:
    return {
        "label": item.label,
        "start_date": item.start_date.isoformat(),
        "end_date": item.end_date.isoformat(),
        "session_count": item.session_count,
    }


def _slice(label: str, dates: Sequence[date]) -> DateSlice:
    if not dates:
        raise ValueError("Date slice cannot be empty")
    return DateSlice(
        label=label,
        start_date=dates[0],
        end_date=dates[-1],
        session_count=len(dates),
    )
