from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .engine import InMemoryCalendarProvider, InMemoryMarketDataProvider, InMemoryUniverseProvider
from .models import Bar, Instrument, Market
from .real_data import (
    MarketSnapshot,
    RealDataError,
    _fetch_market_benchmark_constituents,
    _resolve_symbols_for_scope,
    build_market_snapshot,
    fetch_cn_benchmark_history,
    fetch_cn_detailed_history,
    fetch_us_benchmark_history,
    fetch_us_daily_history,
)
from .research_data import (
    InMemoryBenchmarkProvider,
    InMemoryFundamentalProvider,
    ResearchDataBundle,
    UnavailableBenchmarkProvider,
    UnavailableCorporateActionProvider,
    build_point_in_time_safe_snapshots,
)


@dataclass(frozen=True)
class MarketDataset:
    market: Market
    sessions: Tuple[date, ...]
    snapshots_by_session: Dict[date, MarketSnapshot]

    def snapshot_for_session(self, session_date: date) -> Optional[MarketSnapshot]:
        return self.snapshots_by_session.get(session_date)

    def materialize_snapshots(self) -> List[MarketSnapshot]:
        return [
            self.snapshots_by_session[session_date]
            for session_date in self.sessions
            if session_date in self.snapshots_by_session
        ]


def build_market_dataset(
    market: Market,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
    *,
    symbols: Optional[Iterable[str]] = None,
    build_snapshot_fn: Callable[..., MarketSnapshot] = build_market_snapshot,
) -> MarketDataset:
    if build_snapshot_fn is not build_market_snapshot:
        return _build_dataset_from_snapshot_builder(
            market=market,
            start_date=start_date,
            end_date=end_date,
            detail_limit=detail_limit,
            history_limit=history_limit,
            build_snapshot_fn=build_snapshot_fn,
        )

    return _build_dataset_from_prefetched_histories(
        market=market,
        start_date=start_date,
        end_date=end_date,
        detail_limit=detail_limit,
        history_limit=history_limit,
        symbols=symbols,
    )


def _build_dataset_from_snapshot_builder(
    *,
    market: Market,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
    build_snapshot_fn: Callable[..., MarketSnapshot],
) -> MarketDataset:
    snapshots_by_session: Dict[date, MarketSnapshot] = {}
    for session_date in _weekdays(start_date, end_date):
        snapshot = build_snapshot_fn(
            market,
            symbols=[],
            detail_limit=detail_limit,
            history_limit=_snapshot_history_limit(session_date, history_limit),
            as_of_date=session_date,
        )
        if snapshot.as_of.date() == session_date:
            snapshots_by_session[session_date] = snapshot
    return MarketDataset(
        market=market,
        sessions=tuple(sorted(snapshots_by_session)),
        snapshots_by_session=snapshots_by_session,
    )


def _build_dataset_from_prefetched_histories(
    *,
    market: Market,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
    symbols: Optional[Iterable[str]],
) -> MarketDataset:
    resolved_symbols = _resolve_symbols_for_scope(market, symbols, detail_limit)
    fetch_limit = _snapshot_history_limit(start_date, history_limit)
    fetch_lookback_days = max(fetch_limit * 2, 180, (date.today() - start_date).days + 40)

    instruments: List[Instrument] = []
    bars_by_instrument: Dict[str, List[Bar]] = {}
    for symbol in resolved_symbols:
        try:
            if market == Market.CN:
                instrument, bars = fetch_cn_detailed_history(symbol, limit=fetch_limit)
            else:
                instrument, bars = fetch_us_daily_history(symbol, lookback_days=fetch_lookback_days, limit=fetch_limit)
        except Exception:
            continue
        instruments.append(instrument)
        bars_by_instrument[instrument.instrument_id] = bars

    if not bars_by_instrument:
        raise RealDataError("No bars fetched for market %s" % market.value)

    benchmark_proxy_id = "CSI300_PROXY" if market == Market.CN else "SP500_PROXY"
    benchmark_instrument: Optional[Instrument] = None
    benchmark_bars: List[Bar] = []
    try:
        if market == Market.CN:
            benchmark_instrument, benchmark_bars = fetch_cn_benchmark_history(limit=fetch_limit)
        else:
            benchmark_instrument, benchmark_bars = fetch_us_benchmark_history(
                lookback_days=fetch_lookback_days,
                limit=fetch_limit,
            )
    except Exception:
        benchmark_instrument = None
        benchmark_bars = []

    try:
        benchmark_provider = InMemoryBenchmarkProvider(
            _fetch_market_benchmark_constituents(market, benchmark_proxy_id)
        )
    except Exception:
        benchmark_provider = UnavailableBenchmarkProvider()

    session_as_ofs: Dict[date, datetime] = {}
    for session_date in _weekdays(start_date, end_date):
        as_of = _resolve_session_as_of(bars_by_instrument.values(), session_date)
        if as_of is not None and as_of.date() == session_date:
            session_as_ofs[session_date] = as_of

    if not session_as_ofs:
        raise RuntimeError(f"Not enough sessions found for {market.value}")

    session_timestamps = [session_as_ofs[session_date] for session_date in sorted(session_as_ofs)]
    snapshots_by_session: Dict[date, MarketSnapshot] = {}

    for session_date, as_of in session_as_ofs.items():
        eligible_instrument_ids = {
            instrument_id
            for instrument_id, bars in bars_by_instrument.items()
            if any(bar.timestamp <= as_of for bar in bars)
        }
        session_instruments = [
            instrument
            for instrument in instruments
            if instrument.instrument_id in eligible_instrument_ids
        ]
        session_bars_by_instrument = {
            instrument_id: bars
            for instrument_id, bars in bars_by_instrument.items()
            if instrument_id in eligible_instrument_ids
        }

        benchmark_instrument_id: Optional[str] = None
        if benchmark_instrument and any(bar.timestamp <= as_of for bar in benchmark_bars):
            session_instruments.append(benchmark_instrument)
            session_bars_by_instrument[benchmark_instrument.instrument_id] = benchmark_bars
            benchmark_instrument_id = benchmark_instrument.instrument_id

        raw_data_provider = InMemoryMarketDataProvider(session_instruments, session_bars_by_instrument)
        snapshots = build_point_in_time_safe_snapshots(
            raw_data_provider,
            raw_data_provider.list_instruments(market),
            as_of.date(),
        )
        research_data_bundle = ResearchDataBundle(
            market_data_provider=raw_data_provider,
            fundamental_provider=InMemoryFundamentalProvider(snapshots),
            benchmark_provider=benchmark_provider,
            corporate_action_provider=UnavailableCorporateActionProvider(),
            benchmark_ids_by_market={market: benchmark_proxy_id},
        )
        enriched_instruments = research_data_bundle.enrich_instruments(session_instruments, as_of.date())
        data_provider = InMemoryMarketDataProvider(enriched_instruments, session_bars_by_instrument)
        research_data_bundle = ResearchDataBundle(
            market_data_provider=data_provider,
            fundamental_provider=research_data_bundle.fundamental_provider,
            benchmark_provider=research_data_bundle.benchmark_provider,
            corporate_action_provider=research_data_bundle.corporate_action_provider,
            benchmark_ids_by_market=research_data_bundle.benchmark_ids_by_market,
        )
        snapshots_by_session[session_date] = MarketSnapshot(
            market=market,
            as_of=as_of,
            data_provider=data_provider,
            calendar_provider=InMemoryCalendarProvider({market: session_timestamps}),
            universe_provider=InMemoryUniverseProvider(data_provider),
            research_data_bundle=research_data_bundle,
            benchmark_instrument_id=benchmark_instrument_id,
        )

    return MarketDataset(
        market=market,
        sessions=tuple(sorted(session_as_ofs)),
        snapshots_by_session=snapshots_by_session,
    )


def _resolve_session_as_of(bars_by_instrument: Iterable[Sequence[Bar]], session_date: date) -> Optional[datetime]:
    as_of_candidates: List[datetime] = []
    for bars in bars_by_instrument:
        eligible = [bar for bar in bars if bar.timestamp.date() <= session_date]
        if eligible:
            as_of_candidates.append(eligible[-1].timestamp)
    return min(as_of_candidates) if as_of_candidates else None


def _snapshot_history_limit(oldest_session: date, history_limit: int) -> int:
    return max(
        history_limit,
        min(1000, max(120, (date.today() - oldest_session).days + 40)),
    )


def _weekdays(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current = current.fromordinal(current.toordinal() + 1)
