from __future__ import annotations

from datetime import datetime
from unittest import TestCase

from stock_quantification.factor_registry import (
    ExperimentRun,
    FactorDefinition,
    FactorVersion,
    InMemoryFactorRegistry,
)


class FactorRegistryTests(TestCase):
    def test_register_factor_definition_and_version(self) -> None:
        registry = InMemoryFactorRegistry()
        definition = FactorDefinition(
            factor_id="momentum",
            name="Momentum",
            description="Price trend factor",
        )
        version = FactorVersion(
            factor_id="momentum",
            version="v1",
            definition=definition,
        )

        self.assertEqual(registry.register_factor_definition(definition), definition)
        self.assertEqual(registry.register_factor_version(version), version)

    def test_duplicate_factor_version_rejected(self) -> None:
        registry = InMemoryFactorRegistry()
        definition = FactorDefinition(factor_id="quality", name="Quality", description="Profitability factor")
        version = FactorVersion(factor_id="quality", version="v1", definition=definition)

        registry.register_factor_version(version)

        with self.assertRaises(ValueError):
            registry.register_factor_version(version)

    def test_rejects_factor_version_definition_mismatch(self) -> None:
        registry = InMemoryFactorRegistry()
        definition = FactorDefinition(factor_id="quality", name="Quality", description="Profitability factor")
        version = FactorVersion(factor_id="value", version="v1", definition=definition)

        with self.assertRaises(ValueError):
            registry.register_factor_version(version)

    def test_duplicate_factor_definition_with_different_metadata_rejected(self) -> None:
        registry = InMemoryFactorRegistry()
        first = FactorDefinition(factor_id="momentum", name="Momentum", description="Price trend factor")
        second = FactorDefinition(factor_id="momentum", name="Momentum+", description="Different metadata")

        self.assertEqual(registry.register_factor_definition(first), first)

        with self.assertRaises(ValueError):
            registry.register_factor_definition(second)

    def test_record_experiment_run_keeps_referenced_factor_versions(self) -> None:
        registry = InMemoryFactorRegistry()
        definition = FactorDefinition(factor_id="value", name="Value", description="Cheapness factor")
        version = FactorVersion(factor_id="value", version="v2", definition=definition)
        registry.register_factor_version(version)
        run = ExperimentRun(
            run_id="run-001",
            strategy_id="strategy-a",
            score=0.73,
            created_at=datetime(2026, 4, 18, 9, 0, 0),
            factor_versions=(version,),
        )

        self.assertEqual(registry.record_experiment_run(run), run)
        self.assertEqual(registry.list_experiments(), [run])

    def test_record_experiment_run_rejects_unregistered_factor_versions(self) -> None:
        registry = InMemoryFactorRegistry()
        definition = FactorDefinition(factor_id="value", name="Value", description="Cheapness factor")
        version = FactorVersion(factor_id="value", version="v1", definition=definition)
        run = ExperimentRun(
            run_id="run-001",
            strategy_id="strategy-a",
            score=0.73,
            created_at=datetime(2026, 4, 18, 9, 0, 0),
            factor_versions=(version,),
        )

        with self.assertRaises(ValueError):
            registry.record_experiment_run(run)

    def test_duplicate_experiment_run_id_rejected(self) -> None:
        registry = InMemoryFactorRegistry()
        definition = FactorDefinition(factor_id="value", name="Value", description="Cheapness factor")
        version = FactorVersion(factor_id="value", version="v1", definition=definition)
        registry.register_factor_version(version)
        first = ExperimentRun(
            run_id="run-001",
            strategy_id="strategy-a",
            score=0.73,
            created_at=datetime(2026, 4, 18, 9, 0, 0),
            factor_versions=(version,),
        )
        second = ExperimentRun(
            run_id="run-001",
            strategy_id="strategy-b",
            score=0.91,
            created_at=datetime(2026, 4, 18, 10, 0, 0),
            factor_versions=(version,),
        )

        registry.record_experiment_run(first)

        with self.assertRaises(ValueError):
            registry.record_experiment_run(second)

    def test_empty_registry_lists_no_experiments(self) -> None:
        registry = InMemoryFactorRegistry()

        self.assertEqual(registry.list_experiments(), [])
        self.assertEqual(registry.rank_experiments(), [])

    def test_list_and_rank_experiments_use_deterministic_sorting(self) -> None:
        registry = InMemoryFactorRegistry()
        definition = FactorDefinition(factor_id="momentum", name="Momentum", description="Price trend factor")
        version = FactorVersion(factor_id="momentum", version="v1", definition=definition)
        registry.register_factor_version(version)
        older = ExperimentRun(
            run_id="run-old",
            strategy_id="strategy-a",
            score=0.81,
            created_at=datetime(2026, 4, 18, 9, 0, 0),
            factor_versions=(version,),
        )
        newer = ExperimentRun(
            run_id="run-new",
            strategy_id="strategy-a",
            score=0.65,
            created_at=datetime(2026, 4, 18, 10, 0, 0),
            factor_versions=(version,),
        )
        best = ExperimentRun(
            run_id="run-best",
            strategy_id="strategy-b",
            score=0.92,
            created_at=datetime(2026, 4, 18, 8, 0, 0),
            factor_versions=(version,),
        )

        for run in (older, newer, best):
            registry.record_experiment_run(run)

        self.assertEqual(registry.list_experiments(), [newer, older, best])
        self.assertEqual(registry.rank_experiments(), [best, older, newer])

    def test_tie_cases_use_deterministic_secondary_ordering(self) -> None:
        registry = InMemoryFactorRegistry()
        definition = FactorDefinition(factor_id="momentum", name="Momentum", description="Price trend factor")
        version = FactorVersion(factor_id="momentum", version="v1", definition=definition)
        registry.register_factor_version(version)
        list_alpha = ExperimentRun(
            run_id="run-alpha",
            strategy_id="strategy-a",
            score=0.40,
            created_at=datetime(2026, 4, 18, 9, 0, 0),
            factor_versions=(version,),
        )
        list_beta = ExperimentRun(
            run_id="run-beta",
            strategy_id="strategy-b",
            score=0.50,
            created_at=datetime(2026, 4, 18, 9, 0, 0),
            factor_versions=(version,),
        )
        rank_older = ExperimentRun(
            run_id="run-older",
            strategy_id="strategy-c",
            score=0.90,
            created_at=datetime(2026, 4, 18, 8, 0, 0),
            factor_versions=(version,),
        )
        rank_newer = ExperimentRun(
            run_id="run-newer",
            strategy_id="strategy-d",
            score=0.90,
            created_at=datetime(2026, 4, 18, 10, 0, 0),
            factor_versions=(version,),
        )

        for run in (list_beta, rank_older, list_alpha, rank_newer):
            registry.record_experiment_run(run)

        self.assertEqual(
            registry.list_experiments(),
            [rank_newer, list_alpha, list_beta, rank_older],
        )
        self.assertEqual(
            registry.rank_experiments(),
            [rank_newer, rank_older, list_beta, list_alpha],
        )
