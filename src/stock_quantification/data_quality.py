from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Sequence


_SEVERITY_RANK = {"OK": 0, "WARN": 1, "CRITICAL": 2}


def _severity_for_age(age: timedelta | None, stale_after: timedelta) -> str:
    if age is None:
        return "CRITICAL"
    return "WARN" if age >= stale_after else "OK"


def _normalize_age(age: timedelta | None) -> int | None:
    if age is None:
        return None
    if age.total_seconds() < 0:
        return 0
    return int(age.total_seconds() // 60)


@dataclass(frozen=True)
class DatasetSnapshot:
    dataset_name: str
    row_count: int
    updated_at: datetime | None = None

    def age(self, as_of: datetime) -> timedelta | None:
        if self.updated_at is None:
            return None
        age = as_of - self.updated_at
        return age if age.total_seconds() >= 0 else timedelta(0)

    def summarize(self, as_of: datetime, stale_after: timedelta = timedelta(hours=1)) -> Dict[str, object]:
        age = self.age(as_of)
        return {
            "dataset_name": self.dataset_name,
            "row_count": self.row_count,
            "updated_at": self.updated_at.isoformat() if self.updated_at is not None else None,
            "freshness_minutes": _normalize_age(age),
            "freshness_status": "UNKNOWN" if age is None else ("STALE" if age >= stale_after else "FRESH"),
        }


@dataclass(frozen=True)
class DataQualityFinding:
    dataset_name: str
    code: str
    severity: str
    message: str

    @property
    def status(self) -> str:
        return self.severity


@dataclass(frozen=True)
class DataQualityReport:
    snapshots: List[DatasetSnapshot]
    findings: List[DataQualityFinding]

    @classmethod
    def from_snapshots(
        cls,
        snapshots: Iterable[DatasetSnapshot],
        missing_dataset_names: Sequence[str] = (),
        as_of: datetime | None = None,
        stale_after: timedelta = timedelta(hours=1),
    ) -> "DataQualityReport":
        materialized_snapshots = list(snapshots)
        findings = build_dataset_quality_findings(
            snapshots=materialized_snapshots,
            missing_dataset_names=missing_dataset_names,
            as_of=as_of,
            stale_after=stale_after,
        )
        return cls(snapshots=materialized_snapshots, findings=findings)

    def worst_severity(self) -> str:
        if not self.findings:
            return "OK"
        return max(self.findings, key=lambda finding: _SEVERITY_RANK[finding.severity]).severity

    def summary(self) -> Dict[str, object]:
        worst = self.worst_severity()
        return {
            "overall_status": worst,
            "overall_severity": worst,
            "snapshot_count": len(self.snapshots),
            "finding_count": len(self.findings),
        }


def build_missing_dataset_finding(dataset_name: str) -> DataQualityFinding:
    return DataQualityFinding(
        dataset_name=dataset_name,
        code="MISSING_DATASET",
        severity="CRITICAL",
        message=f"Dataset {dataset_name} is missing.",
    )


def build_zero_row_dataset_finding(snapshot: DatasetSnapshot) -> DataQualityFinding:
    return DataQualityFinding(
        dataset_name=snapshot.dataset_name,
        code="ZERO_ROW_DATASET",
        severity="CRITICAL",
        message=f"Dataset {snapshot.dataset_name} has zero rows.",
    )


def build_stale_dataset_finding(
    snapshot: DatasetSnapshot,
    as_of: datetime,
    stale_after: timedelta = timedelta(hours=1),
) -> DataQualityFinding:
    age = snapshot.age(as_of)
    severity = _severity_for_age(age, stale_after)
    age_minutes = _normalize_age(age)
    if age_minutes is None:
        message = f"Dataset {snapshot.dataset_name} has no freshness timestamp."
    else:
        message = f"Dataset {snapshot.dataset_name} is stale by {age_minutes} minute(s)."
    return DataQualityFinding(
        dataset_name=snapshot.dataset_name,
        code="STALE_DATASET",
        severity=severity,
        message=message,
    )


def build_dataset_quality_findings(
    snapshots: Iterable[DatasetSnapshot],
    missing_dataset_names: Sequence[str] = (),
    as_of: datetime | None = None,
    stale_after: timedelta = timedelta(hours=1),
) -> List[DataQualityFinding]:
    findings: List[DataQualityFinding] = []
    for dataset_name in missing_dataset_names:
        findings.append(build_missing_dataset_finding(dataset_name))
    for snapshot in snapshots:
        if snapshot.row_count <= 0:
            findings.append(build_zero_row_dataset_finding(snapshot))
        if as_of is None:
            continue
        if snapshot.updated_at is None:
            findings.append(build_stale_dataset_finding(snapshot, as_of, stale_after))
            continue
        if snapshot.age(as_of) is not None and snapshot.age(as_of) >= stale_after:
            findings.append(build_stale_dataset_finding(snapshot, as_of, stale_after))
    return findings
