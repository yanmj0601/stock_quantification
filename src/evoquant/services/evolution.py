from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from types import MappingProxyType
from typing import Any, Mapping

from evoquant.domain import new_id
from evoquant.storage import SQLiteStore


@dataclass(frozen=True)
class StrategyTemplate:
    template_id: str
    parameter_space: dict[str, list[object]]


@dataclass(frozen=True)
class GeneratedCandidate:
    id: str
    template_id: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


class EvolutionService:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def generate_candidates(
        self,
        template: StrategyTemplate,
        max_candidates: int,
    ) -> list[GeneratedCandidate]:
        if max_candidates <= 0:
            raise ValueError("max_candidates must be positive")

        keys = list(template.parameter_space.keys())
        values = [template.parameter_space[key] for key in keys]
        candidates: list[GeneratedCandidate] = []
        for combination in product(*values):
            parameters = dict(zip(keys, combination))
            candidates.append(
                GeneratedCandidate(new_id("cand"), template.template_id, parameters)
            )
            if len(candidates) >= max_candidates:
                break
        return candidates
