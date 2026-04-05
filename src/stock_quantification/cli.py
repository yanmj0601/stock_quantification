from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List

from .analytics import compute_return_beta
from .agents import Orchestrator, ResearchAgent, ReviewAgent, StrategyAgent
from .artifacts import write_json_artifact, write_text_artifact
from .engine import (
    AStockSelectionStrategy,
    EqualWeightPortfolioConstructor,
    StandardExecutionPlanner,
    StandardRiskEngine,
    StandardStrategyRunner,
    USStockSelectionStrategy,
)
from .backtest import build_forward_return_report, serialize_backtest_report
from .markets import ChinaMarketRules, USMarketRules
from .models import (
    AccountConstraints,
    AccountState,
    BacktestContext,
    ExecutionMode,
    LiveContext,
    Market,
    PaperContext,
    RuntimeMode,
)
from .real_data import MarketSnapshot, build_market_snapshot
from .research_data import ResearchDataBundle
from .reporting import build_beta_extremes, build_candidate_buckets, build_markdown_report, build_ranked_candidates
from .reporting import build_recommended_stocks
from .runtime import RuntimeEngine
from .state import InMemoryStateStore


def _instrument_name(instrument) -> str:
    return str(
        instrument.attributes.get("name")
        or instrument.attributes.get("company_name")
        or instrument.attributes.get("display_name")
        or instrument.symbol
    )


def _instrument_names(snapshot: MarketSnapshot, market: Market) -> Dict[str, str]:
    return {
        instrument.instrument_id: _instrument_name(instrument)
        for instrument in snapshot.data_provider.list_instruments(market)
    }


def _build_orchestrator(
    snapshot: MarketSnapshot,
    market: Market,
    account_id: str,
    cash: Decimal,
    top_n: int,
) -> Orchestrator:
    strategy_runner = StandardStrategyRunner(snapshot.data_provider, snapshot.universe_provider, snapshot.calendar_provider)
    execution_planner = StandardExecutionPlanner(snapshot.data_provider)
    state_store = InMemoryStateStore()
    state_store.save_account_state(
        AccountState(
            account_id=account_id,
            market=market,
            broker_id="paper-%s" % market.value.lower(),
            cash=cash,
            buying_power=cash,
            constraints=AccountConstraints(max_position_weight=Decimal("0.60"), max_single_order_value=cash),
        )
    )
    return Orchestrator(
        research_agent=ResearchAgent(strategy_runner),
        strategy_agent=StrategyAgent(
            strategy_runner,
            EqualWeightPortfolioConstructor(top_n=top_n),
            execution_planner,
            state_store,
        ),
        review_agent=ReviewAgent(),
        execution_planner=execution_planner,
        risk_engine=StandardRiskEngine(snapshot.data_provider, {Market.CN: ChinaMarketRules(), Market.US: USMarketRules()}),
        state_store=state_store,
        runtime_engine=RuntimeEngine(snapshot.data_provider, snapshot.calendar_provider),
    )


def _strategy_for_market(
    market: Market,
    bundle: ResearchDataBundle,
    as_of,
    benchmark_instrument_id: str | None,
    top_n: int,
):
    available_ids = {
        instrument.instrument_id
        for instrument in bundle.market_data_provider.list_instruments(market)
    }
    benchmark_weights = {
        instrument_id: weight
        for instrument_id, weight in bundle.benchmark_weights(market, as_of.date()).items()
        if instrument_id in available_ids
    }
    if market == Market.CN:
        return AStockSelectionStrategy(
            top_n=top_n,
            benchmark_instrument_id=benchmark_instrument_id,
            benchmark_weights=benchmark_weights,
        )
    return USStockSelectionStrategy(
        top_n=top_n,
        benchmark_instrument_id=benchmark_instrument_id,
        benchmark_weights=benchmark_weights,
    )


def _symbols_for_market(market: Market, raw_symbols: str | None) -> List[str]:
    del market
    if raw_symbols:
        return [item.strip().upper() for item in raw_symbols.split(",") if item.strip()]
    return []


def _build_context(runtime_mode: RuntimeMode, as_of):
    if runtime_mode == RuntimeMode.BACKTEST:
        return BacktestContext(as_of=as_of)
    if runtime_mode == RuntimeMode.PAPER:
        return PaperContext(as_of=as_of)
    return LiveContext(as_of=as_of)


def _period_returns(closes: List[Decimal]) -> List[Decimal]:
    returns: List[Decimal] = []
    for index in range(1, len(closes)):
        previous = closes[index - 1]
        current = closes[index]
        if previous != 0:
            returns.append((current / previous) - Decimal("1"))
    return returns


def _beta_map(snapshot: MarketSnapshot, instrument_ids: List[str], beta_window: int) -> Dict[str, Dict[str, str]]:
    if not snapshot.benchmark_instrument_id:
        return {}
    try:
        benchmark_history = snapshot.data_provider.get_price_history(
            snapshot.benchmark_instrument_id,
            snapshot.as_of,
            beta_window + 1,
        )
    except Exception:
        return {}
    benchmark_returns = _period_returns([bar.close for bar in benchmark_history])
    if len(benchmark_returns) < 2:
        return {}
    betas: Dict[str, Dict[str, str]] = {}
    for instrument_id in instrument_ids:
        try:
            history = snapshot.data_provider.get_price_history(instrument_id, snapshot.as_of, beta_window + 1)
        except Exception:
            continue
        asset_returns = _period_returns([bar.close for bar in history])
        sample = min(len(asset_returns), len(benchmark_returns))
        if sample < 2:
            continue
        metrics = compute_return_beta(asset_returns[-sample:], benchmark_returns[-sample:])
        betas[instrument_id] = {
            "beta": str(metrics.beta.quantize(Decimal("0.0001"))),
            "correlation": str(metrics.correlation.quantize(Decimal("0.0001"))),
            "sample_size": str(metrics.sample_size),
        }
    return betas


def _artifact_prefix(market: Market, trade_date: datetime, universe_scope: str) -> str:
    return f"{trade_date.date().isoformat()}/{market.value.lower()}_{universe_scope.lower()}"


def run_market(
    market: Market,
    symbols: List[str],
    execution_mode: ExecutionMode,
    runtime_mode: RuntimeMode,
    cash: Decimal,
    detail_limit: int,
    history_limit: int,
    beta_window: int,
    top_n: int,
    as_of_date: date | None = None,
    forward_days: int = 0,
) -> Dict[str, object]:
    universe_scope = "CUSTOM" if symbols else "FULL"
    snapshot = build_market_snapshot(
        market,
        symbols,
        detail_limit=detail_limit,
        history_limit=history_limit,
        as_of_date=as_of_date,
    )
    account_id = "%s-default" % market.value.lower()
    orchestrator = _build_orchestrator(snapshot, market, account_id, cash, top_n)
    strategy = _strategy_for_market(
        market,
        snapshot.research_data_bundle,
        snapshot.as_of,
        snapshot.benchmark_instrument_id,
        top_n,
    )
    context = _build_context(runtime_mode, snapshot.as_of)
    result = orchestrator.run(context, strategy, [account_id], execution_mode)
    benchmark_id = snapshot.research_data_bundle.default_benchmark_id(market)
    benchmark_weights = snapshot.research_data_bundle.benchmark_weights(market, snapshot.as_of.date())
    matched_benchmark_weights = {
        instrument_id: weight
        for instrument_id, weight in benchmark_weights.items()
        if instrument_id in {
            instrument.instrument_id
            for instrument in snapshot.data_provider.list_instruments(market)
        }
    }
    fundamental_coverage = _fundamental_coverage(snapshot.research_data_bundle, market, snapshot.as_of)
    all_ranked_instruments = [
        str(row["instrument_id"])
        for row in result.proposal.research_rankings
    ]
    beta_by_instrument = _beta_map(
        snapshot,
        all_ranked_instruments,
        beta_window,
    )
    instrument_names = _instrument_names(snapshot, market)
    selected_betas = {
        signal.instrument_id: beta_by_instrument.get(signal.instrument_id)
        for signal in result.proposal.signals
    }
    ranked_candidates = build_ranked_candidates(
        result.proposal.research_rankings,
        beta_by_instrument,
        instrument_names=instrument_names,
        limit=20,
    )
    candidate_buckets = build_candidate_buckets(
        result.proposal.research_rankings,
        beta_by_instrument,
        instrument_names=instrument_names,
        top_n=5,
    )
    beta_extremes = build_beta_extremes(beta_by_instrument, instrument_names=instrument_names, limit=5)
    signals = [
        {
            "instrument_id": signal.instrument_id,
            "name": instrument_names.get(signal.instrument_id, signal.instrument_id),
            "score": str(signal.score),
            "reason": signal.reason,
            "beta": selected_betas.get(signal.instrument_id),
        }
        for signal in result.proposal.signals
    ]
    trade_suggestions = [
        {
            "account_id": suggestion.account_id,
            "instrument_id": suggestion.instrument_id,
            "name": instrument_names.get(suggestion.instrument_id, suggestion.instrument_id),
            "side": suggestion.side.value,
            "qty": suggestion.suggested_qty,
            "rationale": suggestion.rationale,
        }
        for suggestion in result.proposal.trade_suggestions
    ]
    execution_results = [
        {
            "account_id": execution_result.output_account_state.account_id,
            "fills": [
                {
                    "instrument_id": fill.instrument_id,
                    "status": fill.status.value,
                    "requested_qty": fill.requested_qty,
                    "filled_qty": fill.filled_qty,
                    "estimated_price": str(fill.estimated_price),
                    "cash_delta": str(fill.cash_delta),
                    "estimated_cash_delta": str(fill.estimated_cash_delta),
                }
                for fill in execution_result.fills
            ],
        }
        for execution_result in result.execution_results
    ]
    execution_fills = [
        fill
        for execution_result in execution_results
        for fill in execution_result["fills"]
    ]
    recommended_stocks = build_recommended_stocks(signals, ranked_candidates, trade_suggestions, execution_fills)
    backtest_report = None
    if forward_days > 0:
        backtest_report = serialize_backtest_report(
            build_forward_return_report(
                market,
                snapshot.as_of.date(),
                recommended_stocks,
                ranked_candidates,
                holding_sessions=forward_days,
            )
        )
    return {
        "market": market.value,
        "requested_as_of_date": as_of_date.isoformat() if as_of_date is not None else None,
        "trade_date": snapshot.as_of.date().isoformat(),
        "runtime_mode": runtime_mode.value,
        "universe_scope": universe_scope,
        "symbols": symbols,
        "resolved_symbol_count": len(
            [instrument for instrument in snapshot.data_provider.list_instruments(market)]
        ),
        "benchmark": {
            "benchmark_id": benchmark_id,
            "constituent_count": len(benchmark_weights),
            "matched_symbol_count": len(matched_benchmark_weights),
        },
        "data_coverage": {
            "fundamental_coverage": fundamental_coverage,
        },
        "strategy_id": strategy.strategy_id,
        "research_highlights": result.proposal.research_report.highlights,
        "portfolio_diagnostics": result.proposal.portfolio_diagnostics,
        "recommended_stocks": recommended_stocks,
        "backtest_report": backtest_report,
        "ranked_candidates": ranked_candidates,
        "candidate_buckets": candidate_buckets,
        "beta_extremes": beta_extremes,
        "signals": signals,
        "trade_suggestions": trade_suggestions,
        "approved_order_intents": [
            {
                "instrument_id": intent.instrument_id,
                "name": instrument_names.get(intent.instrument_id, intent.instrument_id),
                "side": intent.side.value,
                "qty": intent.qty,
                "manual": intent.requires_manual_approval,
            }
            for intent in result.order_intents
        ],
        "risk_results": [
            {"order_intent_id": risk.order_intent_id, "passed": risk.passed, "violations": risk.violations}
            for risk in result.risk_results
        ],
        "execution_results": execution_results,
        "review": {"verdict": result.review.verdict.value, "comments": result.review.comments},
    }


def _fundamental_coverage(bundle: ResearchDataBundle, market: Market, as_of) -> str:
    instruments = bundle.market_data_provider.list_instruments(market)
    if not instruments:
        return "0/0"
    covered = 0
    for instrument in instruments:
        if bundle.fundamental_provider.get_snapshot(instrument.instrument_id, as_of.date()) is not None:
            covered += 1
    return f"{covered}/{len(instruments)}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the quant platform against the latest valid market session.")
    parser.add_argument("--market", choices=["CN", "US", "ALL"], default="ALL")
    parser.add_argument("--as-of-date", help="Historical date to reconstruct, for example 2026-03-15")
    parser.add_argument("--symbols-cn", help="Comma-separated A-share symbols")
    parser.add_argument("--symbols-us", help="Comma-separated U.S. symbols")
    parser.add_argument("--detail-limit", type=int, default=80, help="Detailed-history symbol cap in full-market mode")
    parser.add_argument("--history-limit", type=int, default=90, help="History bars requested for benchmark/beta calculations")
    parser.add_argument("--beta-window", type=int, default=20, help="Rolling return window for beta estimation")
    parser.add_argument("--top-n", type=int, default=10, help="Number of candidate stocks to keep")
    parser.add_argument("--artifact-dir", default="artifacts", help="Directory for persisted research reports")
    parser.add_argument("--cash", default="100000")
    parser.add_argument("--execution-mode", choices=["ADVISORY", "AUTO"], default="ADVISORY")
    parser.add_argument("--runtime-mode", choices=["BACKTEST", "PAPER", "LIVE"], default="PAPER")
    parser.add_argument("--forward-days", type=int, default=0, help="Forward holding sessions for post-selection backtest")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    markets = [Market.CN, Market.US] if args.market == "ALL" else [Market(args.market)]
    cash = Decimal(args.cash)
    execution_mode = ExecutionMode(args.execution_mode)
    runtime_mode = RuntimeMode(args.runtime_mode)
    as_of_date = date.fromisoformat(args.as_of_date) if args.as_of_date else None
    output = []
    for market in markets:
        symbols = _symbols_for_market(market, args.symbols_cn if market == Market.CN else args.symbols_us)
        market_output = run_market(
                market,
                symbols,
                execution_mode,
                runtime_mode,
                cash,
                args.detail_limit,
                args.history_limit,
                args.beta_window,
                args.top_n,
                as_of_date=as_of_date,
                forward_days=args.forward_days,
            )
        artifact_prefix = _artifact_prefix(
            market,
            datetime.fromisoformat(market_output["trade_date"]),
            str(market_output["universe_scope"]),
        )
        markdown = build_markdown_report(
            market=market_output["market"],
            trade_date=market_output["trade_date"],
            strategy_id=market_output["strategy_id"],
            scope=market_output["universe_scope"],
            recommended_stocks=market_output["recommended_stocks"],
            ranked_candidates=market_output["ranked_candidates"],
            candidate_buckets=market_output["candidate_buckets"],
            beta_extremes=market_output["beta_extremes"],
            backtest_report=market_output["backtest_report"],
        )
        json_path = write_json_artifact(args.artifact_dir, f"{artifact_prefix}.json", market_output)
        md_path = write_text_artifact(args.artifact_dir, f"{artifact_prefix}.md", markdown)
        market_output["artifacts"] = {"json": json_path, "markdown": md_path}
        output.append(market_output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
