import pytest

from evoquant.domain import RiskMode
from evoquant.services.evolution import EvolutionService, GeneratedCandidate, StrategyTemplate
from evoquant.services.risk import RiskService
from evoquant.storage import SQLiteStore, loads


def test_risk_service_starts_with_live_disabled(tmp_path):
    service = RiskService(SQLiteStore(tmp_path / "state.db"))

    state = service.current()

    assert state.mode is RiskMode.RESEARCH_ONLY
    assert state.live_enabled is False


def test_evolution_expands_template_parameter_space(tmp_path):
    service = EvolutionService(SQLiteStore(tmp_path / "state.db"))
    template = StrategyTemplate("momentum", {"lookback": [20, 60], "threshold": [0.01, 0.03]})

    candidates = service.generate_candidates(template, max_candidates=3)

    assert len(candidates) == 3
    assert candidates[0].parameters["lookback"] in [20, 60]


def test_paused_risk_mode_blocks_paper_trading(tmp_path):
    service = RiskService(SQLiteStore(tmp_path / "state.db"))
    service.set_mode(RiskMode.PAUSED, reason="market halt")

    with pytest.raises(RuntimeError, match="paper trading is paused"):
        service.assert_paper_allowed()


def test_live_disabled_assertion_never_fails_in_v1(tmp_path):
    service = RiskService(SQLiteStore(tmp_path / "state.db"))
    service.set_mode(RiskMode.PAPER_ONLY, reason="paper test")

    service.assert_live_disabled()


def test_set_mode_persists_reason_and_audit_event(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    service = RiskService(store)

    state = service.set_mode(RiskMode.PAPER_ONLY, reason="paper validation")

    assert state.mode is RiskMode.PAPER_ONLY
    assert RiskService(store).current().mode is RiskMode.PAPER_ONLY
    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT event_type, payload
            FROM audit_events
            WHERE entity_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            ("risk_state",),
        ).fetchall()

    assert rows[-1]["event_type"] == "risk.mode_changed"
    assert loads(rows[-1]["payload"]) == {
        "from": RiskMode.RESEARCH_ONLY.value,
        "to": RiskMode.PAPER_ONLY.value,
        "reason": "paper validation",
        "live_enabled": False,
    }


def test_generate_candidates_rejects_non_positive_max_candidates(tmp_path):
    service = EvolutionService(SQLiteStore(tmp_path / "state.db"))
    template = StrategyTemplate("momentum", {"lookback": [20]})

    with pytest.raises(ValueError, match="max_candidates must be positive"):
        service.generate_candidates(template, max_candidates=0)


def test_generated_candidate_parameters_are_deterministic_and_immutable(tmp_path):
    service = EvolutionService(SQLiteStore(tmp_path / "state.db"))
    parameters = {"lookback": [20, 60], "threshold": [0.01, 0.03]}
    template = StrategyTemplate("momentum", parameters)

    candidates = service.generate_candidates(template, max_candidates=4)
    parameters["lookback"].append(120)

    assert [candidate.parameters for candidate in candidates] == [
        {"lookback": 20, "threshold": 0.01},
        {"lookback": 20, "threshold": 0.03},
        {"lookback": 60, "threshold": 0.01},
        {"lookback": 60, "threshold": 0.03},
    ]
    with pytest.raises(TypeError):
        candidates[0].parameters["lookback"] = 120


def test_generated_candidate_nested_parameters_are_immutable():
    candidate = GeneratedCandidate(
        "cand_test",
        "momentum",
        {
            "filters": {"windows": [20, 60], "enabled": True},
            "weights": [0.4, {"risk": 0.6}],
        },
    )

    with pytest.raises(TypeError):
        candidate.parameters["filters"]["windows"] += (120,)
    with pytest.raises(TypeError):
        candidate.parameters["filters"]["enabled"] = False
    with pytest.raises(TypeError):
        candidate.parameters["weights"][1]["risk"] = 0.7


def test_generated_candidate_copies_nested_template_values(tmp_path):
    service = EvolutionService(SQLiteStore(tmp_path / "state.db"))
    filter_config = {"windows": [20, 60], "enabled": True}
    template = StrategyTemplate("momentum", {"filters": [filter_config]})

    candidate = service.generate_candidates(template, max_candidates=1)[0]
    filter_config["windows"].append(120)
    filter_config["enabled"] = False

    assert candidate.parameters["filters"] == {
        "windows": (20, 60),
        "enabled": True,
    }
