from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    name: str
    description: str


@dataclass(frozen=True)
class FactorVersion:
    factor_id: str
    version: str
    definition: FactorDefinition


@dataclass(frozen=True)
class ExperimentRun:
    run_id: str
    strategy_id: str
    score: float
    created_at: datetime
    factor_versions: Tuple[FactorVersion, ...] = field(default_factory=tuple)


class InMemoryFactorRegistry:
    def __init__(self) -> None:
        self._factor_definitions: Dict[str, FactorDefinition] = {}
        self._factor_versions: Dict[Tuple[str, str], FactorVersion] = {}
        self._experiment_runs: Dict[str, ExperimentRun] = {}

    def register_factor_definition(self, definition: FactorDefinition) -> FactorDefinition:
        existing = self._factor_definitions.get(definition.factor_id)
        if existing is not None and existing != definition:
            raise ValueError("factor definition already registered with different metadata")
        self._factor_definitions[definition.factor_id] = definition
        return definition

    def register_factor_version(self, version: FactorVersion) -> FactorVersion:
        if version.factor_id != version.definition.factor_id:
            raise ValueError("factor version factor_id must match definition.factor_id")
        key = (version.factor_id, version.version)
        if key in self._factor_versions:
            raise ValueError("factor version already registered")
        self.register_factor_definition(version.definition)
        self._factor_versions[key] = version
        return version

    def record_experiment_run(self, run: ExperimentRun) -> ExperimentRun:
        if run.run_id in self._experiment_runs:
            raise ValueError("experiment run already recorded")
        for version in run.factor_versions:
            key = (version.factor_id, version.version)
            if self._factor_versions.get(key) != version:
                raise ValueError("experiment run references unregistered factor version")
        self._experiment_runs[run.run_id] = run
        return run

    def list_experiments(self) -> List[ExperimentRun]:
        runs = list(self._experiment_runs.values())
        runs.sort(key=lambda run: run.run_id)
        runs.sort(key=lambda run: run.created_at, reverse=True)
        return runs

    def rank_experiments(self) -> List[ExperimentRun]:
        runs = list(self._experiment_runs.values())
        runs.sort(key=lambda run: run.run_id)
        runs.sort(key=lambda run: run.created_at, reverse=True)
        runs.sort(key=lambda run: run.score, reverse=True)
        return runs
