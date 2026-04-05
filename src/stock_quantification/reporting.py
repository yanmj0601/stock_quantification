from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, List, Mapping


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _format_decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001")))


def _serialize_beta(beta_metrics: Mapping[str, str] | None) -> Dict[str, str] | None:
    if beta_metrics is None:
        return None
    return dict(beta_metrics)


def build_recommended_stocks(
    signals: Iterable[Mapping[str, object]],
    ranked_candidates: Iterable[Mapping[str, object]],
    trade_suggestions: Iterable[Mapping[str, object]],
    execution_fills: Iterable[Mapping[str, object]],
) -> List[Dict[str, object]]:
    ranking_map = {
        str(row["instrument_id"]): row
        for row in ranked_candidates
    }
    suggestion_map = {
        str(row["instrument_id"]): row
        for row in trade_suggestions
    }
    fill_map = {
        str(row["instrument_id"]): row
        for row in execution_fills
    }
    rows: List[Dict[str, object]] = []
    for signal in signals:
        instrument_id = str(signal["instrument_id"])
        ranked = ranking_map.get(instrument_id, {})
        suggestion = suggestion_map.get(instrument_id, {})
        fill = fill_map.get(instrument_id, {})
        rows.append(
            {
                "instrument_id": instrument_id,
                "name": signal.get("name", instrument_id),
                "sector": ranked.get("sector", "UNKNOWN"),
                "score": str(signal.get("score", "0")),
                "beta": signal.get("beta"),
                "target_weight": str(ranked.get("target_weight", "0")),
                "qty": suggestion.get("qty", 0),
                "buy_price": str(fill.get("estimated_price", "")),
                "reason": signal.get("reason", ""),
            }
        )
    return rows


def build_ranked_candidates(
    rankings: Iterable[Mapping[str, object]],
    beta_by_instrument: Mapping[str, Mapping[str, str]],
    instrument_names: Mapping[str, str] | None = None,
    limit: int = 20,
) -> List[Dict[str, object]]:
    instrument_names = instrument_names or {}
    rows: List[Dict[str, object]] = []
    for rank, row in enumerate(list(rankings)[:limit], start=1):
        rows.append(
            {
                "rank": rank,
                "instrument_id": row["instrument_id"],
                "name": instrument_names.get(str(row["instrument_id"]), str(row["instrument_id"])),
                "sector": row.get("sector", "UNKNOWN"),
                "score": _format_decimal(_to_decimal(row.get("score", 0))),
                "target_weight": _format_decimal(_to_decimal(row.get("target_weight", 0))),
                "selected": bool(row.get("selected", False)),
                "beta": _serialize_beta(beta_by_instrument.get(str(row["instrument_id"]))),
            }
        )
    return rows


def build_candidate_buckets(
    rankings: Iterable[Mapping[str, object]],
    beta_by_instrument: Mapping[str, Mapping[str, str]],
    instrument_names: Mapping[str, str] | None = None,
    top_n: int = 5,
) -> Dict[str, List[Dict[str, object]]]:
    instrument_names = instrument_names or {}
    sorted_rows = list(rankings)

    def bucket(predicate) -> List[Dict[str, object]]:
        selected: List[Dict[str, object]] = []
        for row in sorted_rows:
            beta_metrics = beta_by_instrument.get(str(row["instrument_id"]))
            if not predicate(row, beta_metrics):
                continue
            selected.append(
                {
                    "instrument_id": row["instrument_id"],
                    "name": instrument_names.get(str(row["instrument_id"]), str(row["instrument_id"])),
                    "sector": row.get("sector", "UNKNOWN"),
                    "score": _format_decimal(_to_decimal(row.get("score", 0))),
                    "beta": _serialize_beta(beta_metrics),
                }
            )
            if len(selected) >= top_n:
                break
        return selected

    sector_leaders: Dict[str, Dict[str, object]] = {}
    for row in sorted_rows:
        sector = str(row.get("sector", "UNKNOWN"))
        if sector not in sector_leaders:
            sector_leaders[sector] = {
                "instrument_id": row["instrument_id"],
                "name": instrument_names.get(str(row["instrument_id"]), str(row["instrument_id"])),
                "sector": sector,
                "score": _format_decimal(_to_decimal(row.get("score", 0))),
                "beta": _serialize_beta(beta_by_instrument.get(str(row["instrument_id"]))),
            }
        if len(sector_leaders) >= top_n:
            break

    return {
        "defensive_alpha": bucket(
            lambda row, beta: beta is not None and Decimal(beta["beta"]) <= Decimal("0.80")
        ),
        "balanced_alpha": bucket(
            lambda row, beta: beta is not None and Decimal("0.80") < Decimal(beta["beta"]) <= Decimal("1.20")
        ),
        "aggressive_alpha": bucket(
            lambda row, beta: beta is not None and Decimal(beta["beta"]) > Decimal("1.20")
        ),
        "sector_leaders": list(sector_leaders.values()),
    }


def build_beta_extremes(
    beta_by_instrument: Mapping[str, Mapping[str, str]],
    instrument_names: Mapping[str, str] | None = None,
    limit: int = 5,
) -> Dict[str, List[Dict[str, str]]]:
    instrument_names = instrument_names or {}
    ranked = sorted(
        (
            {
                "instrument_id": instrument_id,
                "name": instrument_names.get(instrument_id, instrument_id),
                "beta": metrics["beta"],
                "correlation": metrics["correlation"],
                "sample_size": metrics["sample_size"],
            }
            for instrument_id, metrics in beta_by_instrument.items()
        ),
        key=lambda item: Decimal(item["beta"]),
    )
    return {
        "lowest_beta": ranked[:limit],
        "highest_beta": list(reversed(ranked[-limit:])),
    }


def build_markdown_report(
    market: str,
    trade_date: str,
    strategy_id: str,
    scope: str,
    recommended_stocks: List[Mapping[str, object]],
    ranked_candidates: List[Mapping[str, object]],
    candidate_buckets: Mapping[str, List[Mapping[str, object]]],
    beta_extremes: Mapping[str, List[Mapping[str, str]]],
    backtest_report: Mapping[str, object] | None = None,
) -> str:
    lines = [
        f"# {market} {trade_date} {strategy_id}",
        "",
        f"- scope: `{scope}`",
        f"- ranked candidates: `{len(ranked_candidates)}`",
        "",
        "## Recommendations",
    ]
    for index, row in enumerate(recommended_stocks, start=1):
        lines.append(
            f"- {index}. {row['instrument_id']} {row['name']} sector={row['sector']} beta={row['beta']['beta'] if row['beta'] else 'n/a'} target_weight={row['target_weight']} qty={row['qty']} buy_price={row['buy_price'] or 'n/a'} reason={row['reason']}"
        )
    lines.append("")
    lines.append("## Top Alpha")
    for row in ranked_candidates[:10]:
        lines.append(
            f"- {row['rank']}. {row['instrument_id']} {row['name']} score={row['score']} sector={row['sector']} beta={row['beta']['beta'] if row['beta'] else 'n/a'}"
        )
    lines.append("")
    lines.append("## Candidate Buckets")
    for bucket_name, entries in candidate_buckets.items():
        lines.append(
            f"- {bucket_name}: "
            + (", ".join(f"{item['instrument_id']} {item['name']}" for item in entries) if entries else "none")
        )
    lines.append("")
    lines.append("## Beta Extremes")
    lines.append(
        "- lowest_beta: "
        + (", ".join(f"{item['instrument_id']} {item['name']}" for item in beta_extremes["lowest_beta"]) if beta_extremes["lowest_beta"] else "none")
    )
    lines.append(
        "- highest_beta: "
        + (", ".join(f"{item['instrument_id']} {item['name']}" for item in beta_extremes["highest_beta"]) if beta_extremes["highest_beta"] else "none")
    )
    if backtest_report:
        summary = backtest_report.get("summary", {})
        rows = backtest_report.get("rows", [])
        lines.append("")
        lines.append("## Forward Backtest")
        lines.append(
            "- summary: "
            f"selection_date={summary.get('selection_date', 'n/a')} "
            f"exit_date={summary.get('exit_date', 'n/a')} "
            f"holding_sessions={summary.get('holding_sessions', 'n/a')} "
            f"equal_weight_return={summary.get('equal_weight_return', 'n/a')} "
            f"benchmark_return={summary.get('benchmark_return', 'n/a')} "
            f"excess_return={summary.get('excess_return', 'n/a')} "
            f"win_rate={summary.get('win_rate', 'n/a')} "
            f"ic={summary.get('ic', 'n/a')} "
            f"rank_ic={summary.get('rank_ic', 'n/a')}"
        )
        for index, row in enumerate(rows, start=1):
            lines.append(
                f"- {index}. {row['instrument_id']} {row['name']} forward_return={row['forward_return']} benchmark_return={row['benchmark_return']} excess_return={row['excess_return']} exit_date={row['exit_date']}"
            )
    return "\n".join(lines) + "\n"
