from __future__ import annotations

"""Legacy-compatible agent wrappers around the unified execution pipeline.

The current production path converges on ``pipeline.py`` for strategy
computation and ``execution_flow.py`` for orchestration. The lightweight agent
types in this module are kept only for compatibility with older call sites and
focused unit tests; they are no longer the primary architecture boundary.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from .interfaces import ExecutionPlanner, PortfolioConstructor, StateStore, StrategyDefinition, StrategyRunner
from .models import (
    AccountState,
    FactorSnapshot,
    ResearchReport,
    ReviewReport,
    ReviewVerdict,
    SignalSnapshot,
    StrategyProposal,
)
from .serialization_utils import to_decimal


@dataclass(frozen=True)
class StrategyAnalysis:
    research_report: ResearchReport
    signals: List[SignalSnapshot]
    factors: List[FactorSnapshot]
    targets: List = field(default_factory=list)
    portfolio_diagnostics: Dict[str, object] = field(default_factory=dict)
    rankings: List[Dict[str, object]] = field(default_factory=list)


class ResearchAgent:
    def __init__(self, strategy_runner: StrategyRunner) -> None:
        self._strategy_runner = strategy_runner

    def analyze(self, strategy: StrategyDefinition, as_of, account_states: Optional[Iterable[AccountState]] = None) -> StrategyAnalysis:
        result = self._strategy_runner.run(strategy, as_of, account_states=account_states)
        top_signals = result["signals"][:3]
        highlights = [
            "top_candidates=%s" % ",".join(signal.instrument_id for signal in top_signals) if top_signals else "no_candidates",
            "signal_count=%s" % len(result["signals"]),
        ]
        report = ResearchReport(
            market=strategy.market,
            as_of=as_of,
            highlights=highlights,
            candidate_instruments=[signal.instrument_id for signal in top_signals],
        )
        return StrategyAnalysis(
            research_report=report,
            signals=result["signals"],
            factors=result["factors"],
            targets=result.get("targets", []),
            portfolio_diagnostics=result.get("portfolio_diagnostics", {}),
            rankings=result.get("rankings", []),
        )

    def run(self, strategy: StrategyDefinition, as_of, account_states: Optional[Iterable[AccountState]] = None):
        return self.analyze(strategy, as_of, account_states=account_states).research_report


class StrategyAgent:
    def __init__(
        self,
        strategy_runner: StrategyRunner,
        portfolio_constructor: PortfolioConstructor,
        execution_planner: ExecutionPlanner,
        state_store: StateStore,
    ) -> None:
        self._strategy_runner = strategy_runner
        self._portfolio_constructor = portfolio_constructor
        self._execution_planner = execution_planner
        self._state_store = state_store

    def run(
        self,
        strategy: StrategyDefinition,
        research_report: ResearchReport,
        as_of,
        account_states: Iterable[AccountState],
        analysis: Optional[StrategyAnalysis] = None,
    ) -> StrategyProposal:
        if analysis is None:
            result = self._strategy_runner.run(strategy, as_of, account_states=account_states)
            analysis = StrategyAnalysis(
                research_report=research_report,
                signals=result["signals"],
                factors=result["factors"],
                targets=result.get("targets", []),
                portfolio_diagnostics=result.get("portfolio_diagnostics", {}),
                rankings=result.get("rankings", []),
            )
        targets = analysis.targets or self._portfolio_constructor.build_targets(strategy.strategy_id, strategy.market, as_of, analysis.signals)
        suggestions = self._execution_planner.build_trade_suggestions(account_states, targets, as_of, strategy.strategy_id)
        deduped_suggestions = self._state_store.upsert_trade_suggestions(suggestions)
        return StrategyProposal(
            research_report=research_report,
            signals=analysis.signals,
            factors=analysis.factors,
            targets=targets,
            trade_suggestions=deduped_suggestions,
            portfolio_diagnostics=analysis.portfolio_diagnostics,
            research_rankings=analysis.rankings,
        )


class ReviewAgent:
    def run(self, proposal: StrategyProposal, account_states: Optional[Iterable[AccountState]] = None) -> ReviewReport:
        comments: List[str] = []
        if not proposal.signals:
            comments.append("no_signals_generated")
            verdict = ReviewVerdict.FAIL
        else:
            comments.extend(self._score_metrics(proposal))
            comments.extend(self._portfolio_metrics(proposal))
            comments.extend(self._execution_metrics(proposal))
            comments.extend(self._account_metrics(account_states))
            verdict = self._verdict_for(proposal, comments)
        return ReviewReport(verdict=verdict, comments=comments)

    def _score_metrics(self, proposal: StrategyProposal) -> List[str]:
        scores = [signal.score for signal in proposal.signals]
        max_score = max(scores)
        min_score = min(scores)
        avg_score = sum(scores, Decimal("0")) / to_decimal(len(scores))
        return [
            "signal_count=%s" % len(scores),
            "signal_spread=%s" % _format_decimal(max_score - min_score),
            "signal_average=%s" % _format_decimal(avg_score),
            "top_candidate=%s" % proposal.signals[0].instrument_id,
        ]

    def _portfolio_metrics(self, proposal: StrategyProposal) -> List[str]:
        if not proposal.targets:
            return ["target_count=0", "target_hhi=0.0000", "max_target_weight=0.0000"]
        weights = [target.target_weight for target in proposal.targets]
        hhi = sum(weight * weight for weight in weights)
        max_weight = max(weights)
        comments = [
            "target_count=%s" % len(weights),
            "target_hhi=%s" % _format_decimal(hhi),
            "max_target_weight=%s" % _format_decimal(max_weight),
        ]
        if proposal.portfolio_diagnostics:
            turnover = proposal.portfolio_diagnostics.get("turnover")
            selected_count = proposal.portfolio_diagnostics.get("selected_count")
            if turnover is not None:
                comments.append("planned_turnover=%s" % turnover)
            if selected_count is not None:
                comments.append("planned_selected_count=%s" % selected_count)
        return comments

    def _execution_metrics(self, proposal: StrategyProposal) -> List[str]:
        total_trade_qty = sum(suggestion.suggested_qty for suggestion in proposal.trade_suggestions)
        total_target_qty = sum(max(suggestion.target_qty, 0) for suggestion in proposal.trade_suggestions)
        drift_ratio = Decimal("0") if total_target_qty == 0 else to_decimal(total_trade_qty) / to_decimal(total_target_qty)
        return [
            "trade_suggestion_count=%s" % len(proposal.trade_suggestions),
            "rebalance_qty=%s" % total_trade_qty,
            "rebalance_ratio=%s" % _format_decimal(drift_ratio),
            "drift_ratio=%s" % _format_decimal(drift_ratio),
        ]

    def _account_metrics(self, account_states: Optional[Iterable[AccountState]]) -> List[str]:
        if account_states is None:
            return ["account_count=0", "position_count=0"]
        accounts = list(account_states)
        position_count = sum(len(account.positions) for account in accounts)
        return [
            "account_count=%s" % len(accounts),
            "position_count=%s" % position_count,
        ]

    def _verdict_for(self, proposal: StrategyProposal, comments: List[str]) -> ReviewVerdict:
        if not proposal.signals:
            return ReviewVerdict.FAIL
        metric_map = {item.split("=", 1)[0]: item.split("=", 1)[1] for item in comments if "=" in item}
        target_hhi = Decimal(metric_map.get("target_hhi", "1"))
        max_target_weight = Decimal(metric_map.get("max_target_weight", "1"))
        rebalance_ratio = Decimal(metric_map.get("drift_ratio", metric_map.get("rebalance_ratio", "1")))
        if target_hhi >= Decimal("0.90") or max_target_weight >= Decimal("0.80"):
            return ReviewVerdict.WARN
        if rebalance_ratio >= Decimal("1.20"):
            return ReviewVerdict.WARN
        return ReviewVerdict.PASS


def _format_decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001")))
