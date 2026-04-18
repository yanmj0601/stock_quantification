from __future__ import annotations

import argparse
import json
from datetime import date

from stock_quantification.artifacts import write_json_artifact, write_text_artifact
from stock_quantification.backtest import (
    build_rolling_strategy_backtest_report,
    serialize_rolling_backtest_report,
)
from stock_quantification.models import Market
from stock_quantification.result_index import normalize_rolling_backtest_summary, record_result
from stock_quantification.strategy_catalog import strategy_presets_for_market

ARTIFACT_DIR = "artifacts"


def run_single_strategy_backtest(
    market: Market,
    preset_id: str,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
) -> dict:
    preset = next(item for item in strategy_presets_for_market(market) if item.preset_id == preset_id)
    report = build_rolling_strategy_backtest_report(
        market=market,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        detail_limit=detail_limit,
        history_limit=history_limit,
    )
    payload = serialize_rolling_backtest_report(report)
    payload["normalized_summary"] = normalize_rolling_backtest_summary(payload)
    relative = f"{end_date.isoformat()}/{market.value.lower()}_{preset_id}_rolling_backtest.json"
    json_path = write_json_artifact(ARTIFACT_DIR, relative, payload)
    summary = payload["summary"]
    lines = [
        f"# {summary['display_name']} Rolling Backtest",
        "",
        f"- market: {summary['market']}",
        f"- period: {summary['start_date']} to {summary['end_date']}",
        f"- total_return: {summary['total_return']}",
        f"- benchmark_total_return: {summary['benchmark_total_return'] or 'N/A'}",
        f"- excess_return: {summary['excess_return'] or 'N/A'}",
        f"- max_drawdown: {summary['max_drawdown']}",
        f"- benchmark_available: {summary['benchmark_available']}",
        "",
    ]
    md_path = write_text_artifact(ARTIFACT_DIR, relative.replace(".json", ".md"), "\n".join(lines))
    record_result(
        ARTIFACT_DIR,
        {
            "result_id": f"rolling_backtest:{market.value}:{preset_id}:{end_date.isoformat()}",
            "artifact_kind": "rolling_backtest",
            "market": market.value,
            "preset_id": preset_id,
            "display_name": summary["display_name"],
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "sort_date": end_date.isoformat(),
            "summary": {**payload["normalized_summary"], "trading_days": summary["trading_days"]},
            "artifacts": {"json": json_path, "markdown": md_path},
        },
    )
    return {"summary": payload, "artifacts": {"json": json_path, "markdown": md_path}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a rolling backtest for a single strategy preset.")
    parser.add_argument("--market", choices=["CN", "US"], required=True)
    parser.add_argument("--preset-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--detail-limit", type=int, default=8)
    parser.add_argument("--history-limit", type=int, default=60)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    output = run_single_strategy_backtest(
        market=Market(args.market),
        preset_id=args.preset_id,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        detail_limit=args.detail_limit,
        history_limit=args.history_limit,
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
