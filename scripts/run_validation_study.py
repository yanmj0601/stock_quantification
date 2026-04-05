from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Tuple

from stock_quantification.agents import Orchestrator, ResearchAgent, ReviewAgent, StrategyAgent
from stock_quantification.artifacts import write_json_artifact, write_text_artifact
from stock_quantification.backtest import build_forward_return_report, serialize_backtest_report
from stock_quantification.engine import (
    AStockSelectionStrategy,
    EqualWeightPortfolioConstructor,
    StandardExecutionPlanner,
    StandardRiskEngine,
    StandardStrategyRunner,
    USStockSelectionStrategy,
)
from stock_quantification.markets import ChinaMarketRules, USMarketRules
from stock_quantification.models import AccountConstraints, AccountState, ExecutionMode, Market, PaperContext
from stock_quantification.real_data import (
    build_market_snapshot,
    fetch_cn_benchmark_history,
    fetch_us_benchmark_history,
)
from stock_quantification.runtime import RuntimeEngine
from stock_quantification.state import InMemoryStateStore
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

ARTIFACT_DIR = "artifacts"


def _baseline_alpha_weights(market: Market) -> Dict[str, Decimal]:
    if market == Market.CN:
        return {
            "rel_ret_20": Decimal("0.18"),
            "rel_ret_60": Decimal("0.24"),
            "trend": Decimal("0.08"),
            "liquidity": Decimal("0.05"),
            "profitability": Decimal("0.25"),
            "volatility": Decimal("-0.10"),
            "drawdown": Decimal("-0.15"),
        }
    return {
        "rel_ret_20": Decimal("0.15"),
        "rel_ret_60": Decimal("0.20"),
        "liquidity": Decimal("0.05"),
        "profitability": Decimal("0.25"),
        "quality": Decimal("0.15"),
        "trend": Decimal("0.10"),
        "volatility": Decimal("-0.10"),
        "drawdown": Decimal("-0.15"),
    }


def _factor_groups(market: Market) -> Dict[str, List[str]]:
    if market == Market.CN:
        return {
            "momentum": ["rel_ret_20", "rel_ret_60", "trend"],
            "quality": ["profitability"],
            "risk": ["volatility", "drawdown"],
            "liquidity": ["liquidity"],
        }
    return {
        "momentum": ["rel_ret_20", "rel_ret_60", "trend"],
        "quality": ["profitability", "quality"],
        "risk": ["volatility", "drawdown"],
        "liquidity": ["liquidity"],
    }


def _instrument_name(instrument) -> str:
    return str(
        instrument.attributes.get("name")
        or instrument.attributes.get("company_name")
        or instrument.attributes.get("display_name")
        or instrument.symbol
    )


def _standard_scenario_catalog(market: Market) -> List[Dict[str, object]]:
    if market == Market.CN:
        return [
            {"name": "baseline", "top_n": 4, "alpha": {}, "policy": {}},
            {
                "name": "quality_defensive",
                "top_n": 4,
                "alpha": {
                    "rel_ret_20": Decimal("0.12"),
                    "rel_ret_60": Decimal("0.22"),
                    "profitability": Decimal("0.30"),
                    "volatility": Decimal("-0.12"),
                    "drawdown": Decimal("-0.18"),
                },
                "policy": {
                    "turnover_cap": Decimal("0.14"),
                    "rebalance_buffer": Decimal("0.06"),
                },
            },
            {
                "name": "balanced_rotation",
                "top_n": 5,
                "alpha": {
                    "rel_ret_20": Decimal("0.16"),
                    "rel_ret_60": Decimal("0.20"),
                    "trend": Decimal("0.10"),
                    "profitability": Decimal("0.24"),
                    "volatility": Decimal("-0.08"),
                    "drawdown": Decimal("-0.14"),
                },
                "policy": {
                    "turnover_cap": Decimal("0.16"),
                    "rebalance_buffer": Decimal("0.05"),
                },
            },
        ]
    return [
        {"name": "baseline", "top_n": 4, "alpha": {}, "policy": {}},
        {
            "name": "quality_defensive",
            "top_n": 4,
            "alpha": {
                "rel_ret_20": Decimal("0.12"),
                "rel_ret_60": Decimal("0.18"),
                "profitability": Decimal("0.26"),
                "quality": Decimal("0.18"),
                "volatility": Decimal("-0.14"),
                "drawdown": Decimal("-0.18"),
            },
            "policy": {
                "turnover_cap": Decimal("0.10"),
                "rebalance_buffer": Decimal("0.08"),
            },
        },
        {
            "name": "balanced_quality_momentum",
            "top_n": 5,
            "alpha": {
                "rel_ret_20": Decimal("0.14"),
                "rel_ret_60": Decimal("0.20"),
                "profitability": Decimal("0.22"),
                "quality": Decimal("0.18"),
                "trend": Decimal("0.10"),
                "volatility": Decimal("-0.10"),
                "drawdown": Decimal("-0.14"),
            },
            "policy": {
                "turnover_cap": Decimal("0.12"),
                "rebalance_buffer": Decimal("0.07"),
            },
        },
    ]


def _ablation_scenario_catalog(market: Market) -> List[Dict[str, object]]:
    base_weights = _baseline_alpha_weights(market)
    scenarios: List[Dict[str, object]] = [
        {"name": "baseline", "top_n": 4, "alpha": {}, "policy": {}},
    ]
    for factor_name in base_weights:
        scenarios.append(
            {
                "name": f"drop_{factor_name}",
                "top_n": 4,
                "alpha": {factor_name: Decimal("0")},
                "policy": {},
            }
        )
    for group_name, factors in _factor_groups(market).items():
        alpha_overrides = {factor_name: Decimal("0") for factor_name in base_weights}
        for factor_name in factors:
            alpha_overrides[factor_name] = base_weights[factor_name]
        scenarios.append(
            {
                "name": f"group_{group_name}_only",
                "top_n": 4,
                "alpha": alpha_overrides,
                "policy": {},
            }
        )
    return scenarios


def _scenario_catalog(market: Market, scenario_set: str = "standard") -> List[Dict[str, object]]:
    if scenario_set == "ablation":
        return _ablation_scenario_catalog(market)
    return _standard_scenario_catalog(market)


def _strategy_for_scenario(
    market: Market,
    benchmark_instrument_id: str | None,
    benchmark_weights: Mapping[str, Decimal],
    scenario: Mapping[str, object],
):
    common_kwargs = {
        "top_n": int(scenario["top_n"]),
        "benchmark_instrument_id": benchmark_instrument_id,
        "benchmark_weights": dict(benchmark_weights),
        "alpha_weights_override": dict(scenario.get("alpha", {})),
        "portfolio_policy_override": dict(scenario.get("policy", {})),
    }
    if market == Market.CN:
        return AStockSelectionStrategy(**common_kwargs)
    return USStockSelectionStrategy(**common_kwargs)


def _trading_dates_for_market(market: Market, start_date: date, end_date: date) -> List[date]:
    calendar_span = max(30, (end_date - start_date).days + 30)
    history_limit = max(120, min(1000, calendar_span * 2))
    if market == Market.CN:
        _, bars = fetch_cn_benchmark_history(limit=history_limit)
    else:
        _, bars = fetch_us_benchmark_history(lookback_days=calendar_span, limit=history_limit)
    return [
        bar.timestamp.date()
        for bar in bars
        if start_date <= bar.timestamp.date() <= end_date
    ]


def _aggregate_segment_reports(reports: Iterable[Mapping[str, object]]) -> Dict[str, Decimal]:
    rows = list(reports)
    if not rows:
        return {
            "return": Decimal("0"),
            "excess_return": Decimal("0"),
            "win_rate": Decimal("0"),
            "observations": Decimal("0"),
        }
    return {
        "return": sum(Decimal(str(row["equal_weight_return"])) for row in rows) / Decimal(len(rows)),
        "excess_return": sum(Decimal(str(row["excess_return"])) for row in rows) / Decimal(len(rows)),
        "win_rate": sum(Decimal(str(row["win_rate"])) for row in rows) / Decimal(len(rows)),
        "observations": Decimal(len(rows)),
    }


def _evaluate_snapshot(
    snapshot,
    market: Market,
    scenario: Mapping[str, object],
    holding_sessions: int,
):
    strategy_runner = StandardStrategyRunner(snapshot.data_provider, snapshot.universe_provider, snapshot.calendar_provider)
    execution_planner = StandardExecutionPlanner(snapshot.data_provider)
    state_store = InMemoryStateStore()
    account_id = f"{market.value.lower()}-validation"
    state_store.save_account_state(
        AccountState(
            account_id=account_id,
            market=market,
            broker_id=f"paper-{market.value.lower()}",
            cash=Decimal("100000"),
            buying_power=Decimal("100000"),
            constraints=AccountConstraints(max_position_weight=Decimal("0.60"), max_single_order_value=Decimal("100000")),
        )
    )
    available_ids = {
        instrument.instrument_id
        for instrument in snapshot.research_data_bundle.market_data_provider.list_instruments(market)
    }
    benchmark_weights = {
        instrument_id: weight
        for instrument_id, weight in snapshot.research_data_bundle.benchmark_weights(market, snapshot.as_of.date()).items()
        if instrument_id in available_ids
    }
    strategy = _strategy_for_scenario(
        market,
        snapshot.benchmark_instrument_id,
        benchmark_weights,
        scenario,
    )
    orchestrator = Orchestrator(
        research_agent=ResearchAgent(strategy_runner),
        strategy_agent=StrategyAgent(
            strategy_runner,
            EqualWeightPortfolioConstructor(top_n=int(scenario["top_n"])),
            execution_planner,
            state_store,
        ),
        review_agent=ReviewAgent(),
        execution_planner=execution_planner,
        risk_engine=StandardRiskEngine(snapshot.data_provider, {Market.CN: ChinaMarketRules(), Market.US: USMarketRules()}),
        state_store=state_store,
        runtime_engine=RuntimeEngine(snapshot.data_provider, snapshot.calendar_provider),
    )
    result = orchestrator.run(PaperContext(as_of=snapshot.as_of), strategy, [account_id], ExecutionMode.ADVISORY)
    instrument_lookup = {
        instrument.instrument_id: instrument
        for instrument in snapshot.data_provider.list_instruments(market)
    }
    ranking_map = {
        str(row["instrument_id"]): row
        for row in result.proposal.research_rankings
    }
    recommended_stocks = [
        {
            "instrument_id": signal.instrument_id,
            "name": _instrument_name(instrument_lookup[signal.instrument_id]),
            "sector": ranking_map.get(signal.instrument_id, {}).get("sector", "UNKNOWN"),
            "score": signal.score,
            "target_weight": ranking_map.get(signal.instrument_id, {}).get("target_weight", Decimal("0")),
            "qty": 0,
            "buy_price": None,
            "reason": signal.reason,
        }
        for signal in result.proposal.signals
        if signal.instrument_id in instrument_lookup
    ]
    ranked_candidates = [
        {
            "instrument_id": row["instrument_id"],
            "score": row["score"],
        }
        for row in result.proposal.research_rankings
    ]
    if not recommended_stocks:
        return None
    report = build_forward_return_report(
        market,
        snapshot.as_of.date(),
        recommended_stocks,
        ranked_candidates,
        holding_sessions=holding_sessions,
    )
    return serialize_backtest_report(report)


def run_study(
    market: Market,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
    holding_sessions: int,
    scenario_set: str = "standard",
) -> Dict[str, object]:
    trading_dates = _trading_dates_for_market(market, start_date, end_date)
    split = build_train_validate_test_split(trading_dates)
    train_validate_test_payload = serialize_train_validate_test_split(split)

    train_sessions = max(20, min(40, split.train.session_count))
    validate_sessions = max(5, min(10, split.validate.session_count))
    test_sessions = max(5, min(10, split.test.session_count, validate_sessions))
    walk_forward_windows = build_walk_forward_windows(
        trading_dates,
        train_sessions=train_sessions,
        validate_sessions=validate_sessions,
        test_sessions=test_sessions,
        step_sessions=test_sessions,
    )

    scenarios = _scenario_catalog(market, scenario_set=scenario_set)
    segment_dates = {
        "train": [day for day in trading_dates if split.train.start_date <= day <= split.train.end_date],
        "validate": [day for day in trading_dates if split.validate.start_date <= day <= split.validate.end_date],
        "test": [day for day in trading_dates if split.test.start_date <= day <= split.test.end_date],
    }

    scenario_segment_reports: Dict[str, Dict[str, List[Dict[str, object]]]] = {
        scenario["name"]: {"train": [], "validate": [], "test": []}
        for scenario in scenarios
    }
    walk_forward_results: List[WalkForwardWindowResult] = []
    evaluation_cache: Dict[Tuple[str, date], Dict[str, object] | None] = {}
    snapshot_cache: Dict[date, object | None] = {}

    def load_snapshot(trade_date: date):
        if trade_date not in snapshot_cache:
            snapshot_history_limit = max(
                history_limit,
                min(1000, max(120, (date.today() - trade_date).days + 40)),
            )
            snapshot = build_market_snapshot(
                market,
                symbols=[],
                detail_limit=detail_limit,
                history_limit=snapshot_history_limit,
                as_of_date=trade_date,
            )
            snapshot_cache[trade_date] = snapshot if snapshot.as_of.date() == trade_date else None
        return snapshot_cache[trade_date]

    def load_report(scenario: Mapping[str, object], trade_date: date) -> Dict[str, object] | None:
        cache_key = (str(scenario["name"]), trade_date)
        if cache_key not in evaluation_cache:
            snapshot = load_snapshot(trade_date)
            evaluation_cache[cache_key] = (
                None if snapshot is None else _evaluate_snapshot(snapshot, market, scenario, holding_sessions=holding_sessions)
            )
        return evaluation_cache[cache_key]

    for scenario in scenarios:
        for segment_name, dates in segment_dates.items():
            for trade_date in dates:
                report = load_report(scenario, trade_date)
                if report is not None:
                    scenario_segment_reports[scenario["name"]][segment_name].append(report["summary"])

        for window in walk_forward_windows:
            window_segment_reports = {"train": [], "validate": [], "test": []}
            for label, date_slice in (("train", window.train), ("validate", window.validate), ("test", window.test)):
                window_dates = [day for day in trading_dates if date_slice.start_date <= day <= date_slice.end_date]
                for trade_date in window_dates:
                    report = load_report(scenario, trade_date)
                    if report is not None:
                        window_segment_reports[label].append(report["summary"])
            train_summary = _aggregate_segment_reports(window_segment_reports["train"])
            validate_summary = _aggregate_segment_reports(window_segment_reports["validate"])
            test_summary = _aggregate_segment_reports(window_segment_reports["test"])
            walk_forward_results.append(
                WalkForwardWindowResult(
                    window_index=window.window_index,
                    scenario_name=str(scenario["name"]),
                    train_return=train_summary["return"],
                    validate_return=validate_summary["return"],
                    test_return=test_summary["return"],
                    train_excess_return=train_summary["excess_return"],
                    validate_excess_return=validate_summary["excess_return"],
                    test_excess_return=test_summary["excess_return"],
                    train_win_rate=train_summary["win_rate"],
                    validate_win_rate=validate_summary["win_rate"],
                    test_win_rate=test_summary["win_rate"],
                    train_observations=int(train_summary["observations"]),
                    validate_observations=int(validate_summary["observations"]),
                    test_observations=int(test_summary["observations"]),
                )
            )

    walk_forward_report = build_walk_forward_report(walk_forward_windows, walk_forward_results)
    stability_report = build_parameter_stability_report(walk_forward_results)
    segment_summaries = {
        scenario_name: {
            segment_name: {
                "average_return": str(_aggregate_segment_reports(reports)["return"].quantize(Decimal("0.0001"))),
                "average_excess_return": str(_aggregate_segment_reports(reports)["excess_return"].quantize(Decimal("0.0001"))),
                "average_win_rate": str(_aggregate_segment_reports(reports)["win_rate"].quantize(Decimal("0.0001"))),
                "observations": int(_aggregate_segment_reports(reports)["observations"]),
            }
            for segment_name, reports in segments.items()
        }
        for scenario_name, segments in scenario_segment_reports.items()
    }

    payload = {
        "market": market.value,
        "scenario_set": scenario_set,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "holding_sessions": holding_sessions,
        "split": train_validate_test_payload,
        "walk_forward": serialize_walk_forward_report(walk_forward_report),
        "parameter_stability": serialize_parameter_stability_report(stability_report),
        "segment_summaries": segment_summaries,
    }
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run train/validate/test, walk-forward, and parameter stability validation.")
    parser.add_argument("--market", choices=["CN", "US"], required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--scenario-set", choices=["standard", "ablation"], default="standard")
    parser.add_argument("--holding-sessions", type=int, default=5)
    parser.add_argument("--detail-limit", type=int, default=20)
    parser.add_argument("--history-limit", type=int, default=90)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    market = Market(args.market)
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    payload = run_study(
        market,
        start_date=start_date,
        end_date=end_date,
        detail_limit=args.detail_limit,
        history_limit=args.history_limit,
        holding_sessions=args.holding_sessions,
        scenario_set=args.scenario_set,
    )
    suffix = "validation_study" if args.scenario_set == "standard" else f"{args.scenario_set}_validation_study"
    relative_base = f"{end_date.isoformat()}/{market.value.lower()}_{suffix}"
    json_path = write_json_artifact(ARTIFACT_DIR, f"{relative_base}.json", payload)
    lines = [
        f"# {market.value} Validation Study",
        "",
        f"- period: {start_date.isoformat()} to {end_date.isoformat()}",
        f"- scenario_set: {args.scenario_set}",
        f"- holding_sessions: {args.holding_sessions}",
        f"- recommended_scenario: {payload['parameter_stability']['recommended_scenario']}",
        "",
        "## Segment Summaries",
    ]
    for scenario_name, segments in payload["segment_summaries"].items():
        lines.append(f"- {scenario_name}: train={segments['train']['average_return']} validate={segments['validate']['average_return']} test={segments['test']['average_return']}")
    md_path = write_text_artifact(ARTIFACT_DIR, f"{relative_base}.md", "\n".join(lines) + "\n")
    print(json.dumps({"json": json_path, "markdown": md_path, "recommended_scenario": payload["parameter_stability"]["recommended_scenario"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
