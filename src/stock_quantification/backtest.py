from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Dict, Iterable, List, Mapping, Sequence

from .analytics import InformationCoefficientMetrics, compute_information_coefficient
from .models import Market
from .real_data import (
    fetch_cn_benchmark_history,
    fetch_cn_detailed_history,
    fetch_us_benchmark_history,
    fetch_us_daily_history,
)


@dataclass(frozen=True)
class ForwardReturnRow:
    instrument_id: str
    name: str
    sector: str
    entry_date: str
    exit_date: str
    entry_price: Decimal
    exit_price: Decimal
    holding_sessions: int
    forward_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal
    target_weight: Decimal
    qty: int
    buy_price: Decimal | None
    score: Decimal
    reason: str


@dataclass(frozen=True)
class BacktestSummary:
    selection_date: str
    exit_date: str
    holding_sessions: int
    selected_count: int
    positive_count: int
    negative_count: int
    win_rate: Decimal
    equal_weight_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal
    average_return: Decimal
    median_return: Decimal
    average_excess_return: Decimal
    best_instrument_id: str
    best_name: str
    best_return: Decimal
    worst_instrument_id: str
    worst_name: str
    worst_return: Decimal
    ic: Decimal
    rank_ic: Decimal
    ic_sample_size: int


@dataclass(frozen=True)
class BacktestReport:
    summary: BacktestSummary
    rows: List[ForwardReturnRow]


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _serialize_row(row: ForwardReturnRow) -> Dict[str, object]:
    payload = asdict(row)
    for key, value in payload.items():
        if isinstance(value, Decimal):
            payload[key] = str(value.quantize(Decimal("0.0001")))
    if row.buy_price is None:
        payload["buy_price"] = None
    return payload


def _serialize_summary(summary: BacktestSummary) -> Dict[str, object]:
    payload = asdict(summary)
    for key, value in payload.items():
        if isinstance(value, Decimal):
            payload[key] = str(value.quantize(Decimal("0.0001")))
    return payload


def serialize_backtest_report(report: BacktestReport) -> Dict[str, object]:
    return {
        "summary": _serialize_summary(report.summary),
        "rows": [_serialize_row(row) for row in report.rows],
    }


def build_forward_return_report(
    market: Market,
    trade_date: date,
    recommended_stocks: Sequence[Mapping[str, object]],
    ranked_candidates: Sequence[Mapping[str, object]],
    holding_sessions: int = 5,
) -> BacktestReport:
    if holding_sessions <= 0:
        raise ValueError("holding_sessions must be positive")

    benchmark_entry_price, benchmark_exit_price, exit_date = _benchmark_window(market, trade_date, holding_sessions)
    benchmark_return = _simple_return(benchmark_entry_price, benchmark_exit_price)

    rows: List[ForwardReturnRow] = []
    for stock in recommended_stocks:
        entry_date, resolved_exit_date, entry_price, exit_price = _instrument_window(
            market,
            str(stock["instrument_id"]),
            trade_date,
            holding_sessions,
        )
        buy_price = _optional_decimal(stock.get("buy_price"))
        effective_entry = buy_price or entry_price
        forward_return = _simple_return(effective_entry, exit_price)
        rows.append(
            ForwardReturnRow(
                instrument_id=str(stock["instrument_id"]),
                name=str(stock.get("name", stock["instrument_id"])),
                sector=str(stock.get("sector", "UNKNOWN")),
                entry_date=entry_date.isoformat(),
                exit_date=resolved_exit_date.isoformat(),
                entry_price=entry_price,
                exit_price=exit_price,
                holding_sessions=holding_sessions,
                forward_return=forward_return,
                benchmark_return=benchmark_return,
                excess_return=forward_return - benchmark_return,
                target_weight=_to_decimal(stock.get("target_weight", "0")),
                qty=int(stock.get("qty", 0)),
                buy_price=buy_price,
                score=_to_decimal(stock.get("score", "0")),
                reason=str(stock.get("reason", "")),
            )
        )

    rows.sort(key=lambda item: item.forward_return, reverse=True)

    factor_values = {
        str(row["instrument_id"]): _to_decimal(row.get("score", "0"))
        for row in ranked_candidates
    }
    future_returns = {
        row.instrument_id: row.forward_return
        for row in rows
    }
    ic_metrics: InformationCoefficientMetrics = compute_information_coefficient(factor_values, future_returns)
    summary = _build_summary(trade_date, exit_date, holding_sessions, rows, benchmark_return, ic_metrics)
    return BacktestReport(summary=summary, rows=rows)


def _build_summary(
    trade_date: date,
    exit_date: date,
    holding_sessions: int,
    rows: Sequence[ForwardReturnRow],
    benchmark_return: Decimal,
    ic_metrics: InformationCoefficientMetrics,
) -> BacktestSummary:
    if not rows:
        return BacktestSummary(
            selection_date=trade_date.isoformat(),
            exit_date=exit_date.isoformat(),
            holding_sessions=holding_sessions,
            selected_count=0,
            positive_count=0,
            negative_count=0,
            win_rate=Decimal("0"),
            equal_weight_return=Decimal("0"),
            benchmark_return=benchmark_return,
            excess_return=Decimal("0") - benchmark_return,
            average_return=Decimal("0"),
            median_return=Decimal("0"),
            average_excess_return=Decimal("0"),
            best_instrument_id="",
            best_name="",
            best_return=Decimal("0"),
            worst_instrument_id="",
            worst_name="",
            worst_return=Decimal("0"),
            ic=ic_metrics.ic,
            rank_ic=ic_metrics.rank_ic,
            ic_sample_size=ic_metrics.sample_size,
        )

    returns = [row.forward_return for row in rows]
    excess_returns = [row.excess_return for row in rows]
    equal_weight_return = sum(returns, Decimal("0")) / Decimal(len(returns))
    best = max(rows, key=lambda item: item.forward_return)
    worst = min(rows, key=lambda item: item.forward_return)
    positive_count = sum(1 for row in rows if row.forward_return > 0)
    negative_count = sum(1 for row in rows if row.forward_return < 0)
    return BacktestSummary(
        selection_date=trade_date.isoformat(),
        exit_date=exit_date.isoformat(),
        holding_sessions=holding_sessions,
        selected_count=len(rows),
        positive_count=positive_count,
        negative_count=negative_count,
        win_rate=Decimal(positive_count) / Decimal(len(rows)),
        equal_weight_return=equal_weight_return,
        benchmark_return=benchmark_return,
        excess_return=equal_weight_return - benchmark_return,
        average_return=equal_weight_return,
        median_return=Decimal(str(median([float(item) for item in returns]))),
        average_excess_return=sum(excess_returns, Decimal("0")) / Decimal(len(excess_returns)),
        best_instrument_id=best.instrument_id,
        best_name=best.name,
        best_return=best.forward_return,
        worst_instrument_id=worst.instrument_id,
        worst_name=worst.name,
        worst_return=worst.forward_return,
        ic=ic_metrics.ic,
        rank_ic=ic_metrics.rank_ic,
        ic_sample_size=ic_metrics.sample_size,
    )


def _benchmark_window(market: Market, trade_date: date, holding_sessions: int) -> tuple[Decimal, Decimal, date]:
    if market == Market.CN:
        _, bars = fetch_cn_benchmark_history(limit=180)
    else:
        _, bars = fetch_us_benchmark_history(limit=180)
    entry_date, exit_date, entry_price, exit_price = _price_window(bars, trade_date, holding_sessions)
    del entry_date
    return entry_price, exit_price, exit_date


def _instrument_window(
    market: Market,
    instrument_id: str,
    trade_date: date,
    holding_sessions: int,
) -> tuple[date, date, Decimal, Decimal]:
    symbol = instrument_id.split(".", 1)[1]
    if market == Market.CN:
        _, bars = fetch_cn_detailed_history(symbol, limit=180)
    else:
        _, bars = fetch_us_daily_history(symbol, lookback_days=365, limit=180)
    return _price_window(bars, trade_date, holding_sessions)


def _price_window(bars: Sequence[object], trade_date: date, holding_sessions: int) -> tuple[date, date, Decimal, Decimal]:
    eligible = [bar for bar in bars if bar.timestamp.date() <= trade_date]
    if not eligible:
        raise ValueError("No eligible bars on or before %s" % trade_date.isoformat())
    entry_bar = eligible[-1]
    full = list(bars)
    try:
        entry_index = full.index(entry_bar)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError("Unable to locate entry bar") from exc
    exit_index = min(entry_index + holding_sessions, len(full) - 1)
    exit_bar = full[exit_index]
    return entry_bar.timestamp.date(), exit_bar.timestamp.date(), entry_bar.close, exit_bar.close


def _simple_return(entry_price: Decimal, exit_price: Decimal) -> Decimal:
    if entry_price == 0:
        return Decimal("0")
    return (exit_price / entry_price) - Decimal("1")


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, "", "n/a"):
        return None
    return _to_decimal(value)
