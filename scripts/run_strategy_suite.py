from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from typing import Dict, List

from stock_quantification.artifacts import write_json_artifact, write_text_artifact
from stock_quantification.backtest import (
    build_rolling_strategy_backtest_report,
    serialize_rolling_backtest_report,
)
from stock_quantification.models import Market
from stock_quantification.result_index import normalize_strategy_suite_summary, record_result
from stock_quantification.research_diagnostics import (
    build_strategy_scorecard,
    serialize_alpha_mix,
    serialize_regime_summaries,
    serialize_strategy_scorecard,
    summarize_alpha_mix,
    summarize_regimes,
)
from stock_quantification.strategy_catalog import strategy_presets_for_market

ARTIFACT_DIR = "artifacts"


def run_strategy_suite(
    market: Market,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
) -> Dict[str, object]:
    summaries: List[Dict[str, object]] = []
    strategy_presets = strategy_presets_for_market(market)

    for preset in strategy_presets:
        report = build_rolling_strategy_backtest_report(
            market=market,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            detail_limit=detail_limit,
            history_limit=history_limit,
        )
        serialized = serialize_rolling_backtest_report(report)
        summary = serialized["summary"]
        regime_summaries = summarize_regimes(report)
        alpha_mix = summarize_alpha_mix(preset)
        scorecard = build_strategy_scorecard(preset, report, regime_summaries)
        summaries.append(
            {
                "preset_id": summary["preset_id"],
                "display_name": summary["display_name"],
                "family": preset.family,
                "description": preset.description,
                "total_return": summary["total_return"],
                "pre_fee_return": summary["pre_fee_return"],
                "fee_drag": summary["fee_drag"],
                "annualized_return": summary["annualized_return"],
                "annualized_volatility": summary["annualized_volatility"],
                "sharpe_ratio": summary["sharpe_ratio"],
                "average_turnover": summary["average_turnover"],
                "total_fees": summary["total_fees"],
                "max_drawdown": summary["max_drawdown"],
                "final_nav": summary["final_nav"],
                "trading_days": summary["trading_days"],
                "benchmark_available": summary["benchmark_available"],
                "benchmark_total_return": summary["benchmark_total_return"],
                "excess_return": summary["excess_return"],
                "regime_summary": serialize_regime_summaries(regime_summaries),
                "alpha_mix": serialize_alpha_mix(alpha_mix),
                "scorecard": serialize_strategy_scorecard(scorecard),
            }
        )

    summaries.sort(key=lambda item: Decimal(item["scorecard"]["score"]), reverse=True)
    recommended = [row["preset_id"] for row in summaries if row["scorecard"]["decision"] == "KEEP"][:3]
    watchlist = [row["preset_id"] for row in summaries if row["scorecard"]["decision"] == "REVIEW"]
    drop_list = [row["preset_id"] for row in summaries if row["scorecard"]["decision"] == "DROP"]
    payload = {
        "market": market.value,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "detail_limit": detail_limit,
        "history_limit": history_limit,
        "recommended_presets": recommended,
        "watchlist_presets": watchlist,
        "drop_presets": drop_list,
        "strategies": summaries,
    }
    payload["normalized_summary"] = normalize_strategy_suite_summary(payload)
    relative = f"{end_date.isoformat()}/{market.value.lower()}_strategy_suite.json"
    json_path = write_json_artifact(ARTIFACT_DIR, relative, payload)
    lines = [
        f"# {market.value} Strategy Suite",
        "",
        f"- period: {start_date.isoformat()} to {end_date.isoformat()}",
        "",
        f"- recommended_presets: {', '.join(recommended) if recommended else 'none'}",
        f"- watchlist_presets: {', '.join(watchlist) if watchlist else 'none'}",
        f"- drop_presets: {', '.join(drop_list) if drop_list else 'none'}",
        "",
        "| 策略 | 家族 | 决策 | 评分 | 净收益 | 费前收益 | 费用拖累 | 超额收益 | 夏普 | 最大回撤 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summaries:
        lines.append(
            f"| {row['display_name']} | {row['family']} | {row['scorecard']['decision']} | {row['scorecard']['score']} | {row['total_return']} | "
            f"{row['pre_fee_return']} | {row['fee_drag']} | {row['excess_return'] or 'N/A'} | {row['sharpe_ratio']} | {row['max_drawdown']} |"
        )
    md_path = write_text_artifact(ARTIFACT_DIR, relative.replace(".json", ".md"), "\n".join(lines) + "\n")
    record_result(
        ARTIFACT_DIR,
        {
            "result_id": f"strategy_suite:{market.value}:{end_date.isoformat()}",
            "artifact_kind": "strategy_suite",
            "market": market.value,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "sort_date": end_date.isoformat(),
            "summary": {
                **payload["normalized_summary"],
                "recommended_presets": recommended,
                "watchlist_count": len(watchlist),
                "drop_count": len(drop_list),
            },
            "artifacts": {"json": json_path, "markdown": md_path},
        },
    )
    return {"summary": payload, "artifacts": {"json": json_path, "markdown": md_path}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a suite of mainstream long-only strategy presets.")
    parser.add_argument("--market", choices=["CN", "US", "ALL"], default="ALL")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--detail-limit-cn", type=int, default=8)
    parser.add_argument("--detail-limit-us", type=int, default=6)
    parser.add_argument("--history-limit", type=int, default=60)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    markets = [Market.CN, Market.US] if args.market == "ALL" else [Market(args.market)]
    outputs = []
    for market in markets:
        detail_limit = args.detail_limit_cn if market == Market.CN else args.detail_limit_us
        outputs.append(
            run_strategy_suite(
                market,
                start_date=start_date,
                end_date=end_date,
                detail_limit=detail_limit,
                history_limit=args.history_limit,
            )
        )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
