from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from .interfaces import MarketDataProvider
from .models import Bar, Instrument, Market
from .runtime import CorporateAction


class DataAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class FundamentalSnapshot:
    instrument_id: str
    as_of: date
    metrics: Dict[str, object]


@dataclass(frozen=True)
class BenchmarkConstituent:
    benchmark_id: str
    instrument_id: str
    weight: Decimal
    as_of: date


class FundamentalProvider:
    def get_snapshot(self, instrument_id: str, as_of: date) -> Optional[FundamentalSnapshot]:
        raise NotImplementedError


class CorporateActionProvider:
    def get_actions(self, instrument_id: str, start_date: date, end_date: date) -> List[CorporateAction]:
        raise NotImplementedError

    def availability(self, instrument_id: str, start_date: date, end_date: date) -> DataAvailability:
        raise NotImplementedError


class BenchmarkProvider:
    def get_constituents(self, benchmark_id: str, as_of: date) -> List[BenchmarkConstituent]:
        raise NotImplementedError

    def availability(self, benchmark_id: str, as_of: date) -> DataAvailability:
        raise NotImplementedError

    def get_weights(self, benchmark_id: str, as_of: date) -> Dict[str, Decimal]:
        return {
            item.instrument_id: item.weight
            for item in self.get_constituents(benchmark_id, as_of)
        }


class InMemoryFundamentalProvider(FundamentalProvider):
    def __init__(self, snapshots: Iterable[FundamentalSnapshot]) -> None:
        grouped: Dict[str, List[FundamentalSnapshot]] = {}
        for snapshot in snapshots:
            grouped.setdefault(snapshot.instrument_id, []).append(snapshot)
        self._snapshots = {
            instrument_id: sorted(values, key=lambda item: item.as_of)
            for instrument_id, values in grouped.items()
        }

    def get_snapshot(self, instrument_id: str, as_of: date) -> Optional[FundamentalSnapshot]:
        candidates = [item for item in self._snapshots.get(instrument_id, []) if item.as_of <= as_of]
        return candidates[-1] if candidates else None


class InMemoryCorporateActionProvider(CorporateActionProvider):
    def __init__(self, actions: Iterable[CorporateAction]) -> None:
        grouped: Dict[str, List[CorporateAction]] = {}
        for action in actions:
            grouped.setdefault(action.instrument_id, []).append(action)
        self._actions = {
            instrument_id: sorted(values, key=lambda item: item.effective_date)
            for instrument_id, values in grouped.items()
        }

    def get_actions(self, instrument_id: str, start_date: date, end_date: date) -> List[CorporateAction]:
        return [
            action
            for action in self._actions.get(instrument_id, [])
            if start_date <= action.effective_date <= end_date
        ]

    def availability(self, instrument_id: str, start_date: date, end_date: date) -> DataAvailability:
        del instrument_id, start_date, end_date
        return DataAvailability.AVAILABLE


class UnavailableCorporateActionProvider(CorporateActionProvider):
    def __init__(self, reason: str = "corporate_actions_unavailable") -> None:
        self.reason = reason

    def get_actions(self, instrument_id: str, start_date: date, end_date: date) -> List[CorporateAction]:
        del instrument_id, start_date, end_date
        return []

    def availability(self, instrument_id: str, start_date: date, end_date: date) -> DataAvailability:
        del instrument_id, start_date, end_date
        return DataAvailability.UNAVAILABLE


class InMemoryBenchmarkProvider(BenchmarkProvider):
    def __init__(self, constituents: Iterable[BenchmarkConstituent]) -> None:
        grouped: Dict[str, List[BenchmarkConstituent]] = {}
        for constituent in constituents:
            grouped.setdefault(constituent.benchmark_id, []).append(constituent)
        self._constituents = {
            benchmark_id: sorted(values, key=lambda item: item.as_of)
            for benchmark_id, values in grouped.items()
        }

    def get_constituents(self, benchmark_id: str, as_of: date) -> List[BenchmarkConstituent]:
        candidates = [item for item in self._constituents.get(benchmark_id, []) if item.as_of <= as_of]
        latest_date = max((item.as_of for item in candidates), default=None)
        if latest_date is None:
            return []
        latest = [item for item in candidates if item.as_of == latest_date]
        total = sum(item.weight for item in latest)
        if total <= 0:
            return []
        return [
            BenchmarkConstituent(
                benchmark_id=item.benchmark_id,
                instrument_id=item.instrument_id,
                weight=item.weight / total,
                as_of=item.as_of,
            )
            for item in latest
        ]

    def availability(self, benchmark_id: str, as_of: date) -> DataAvailability:
        return DataAvailability.AVAILABLE if self.get_constituents(benchmark_id, as_of) else DataAvailability.UNAVAILABLE


class UnavailableBenchmarkProvider(BenchmarkProvider):
    def __init__(self, reason: str = "benchmark_unavailable") -> None:
        self.reason = reason

    def get_constituents(self, benchmark_id: str, as_of: date) -> List[BenchmarkConstituent]:
        del benchmark_id, as_of
        return []

    def availability(self, benchmark_id: str, as_of: date) -> DataAvailability:
        del benchmark_id, as_of
        return DataAvailability.UNAVAILABLE


@dataclass(frozen=True)
class ResearchDataBundle:
    market_data_provider: MarketDataProvider
    fundamental_provider: FundamentalProvider
    benchmark_provider: BenchmarkProvider
    corporate_action_provider: CorporateActionProvider
    benchmark_ids_by_market: Dict[Market, str] = field(default_factory=dict)

    def default_benchmark_id(self, market: Market) -> Optional[str]:
        return self.benchmark_ids_by_market.get(market)

    def benchmark_status(self, market: Market, as_of: date) -> DataAvailability:
        benchmark_id = self.default_benchmark_id(market)
        if not benchmark_id:
            return DataAvailability.UNAVAILABLE
        return self.benchmark_provider.availability(benchmark_id, as_of)

    def benchmark_is_available(self, market: Market, as_of: date) -> bool:
        return self.benchmark_status(market, as_of) == DataAvailability.AVAILABLE

    def benchmark_weights(self, market: Market, as_of: date) -> Dict[str, Decimal]:
        benchmark_id = self.default_benchmark_id(market)
        if not benchmark_id:
            return {}
        return self.benchmark_provider.get_weights(benchmark_id, as_of)

    def corporate_action_status(self, instrument_id: str, start_date: date, end_date: date) -> DataAvailability:
        return self.corporate_action_provider.availability(instrument_id, start_date, end_date)

    def enrich_instruments(self, instruments: Sequence[Instrument], as_of: date) -> List[Instrument]:
        enriched: List[Instrument] = []
        for instrument in instruments:
            snapshot = self.fundamental_provider.get_snapshot(instrument.instrument_id, as_of)
            if snapshot is None:
                enriched.append(instrument)
                continue
            attributes = dict(instrument.attributes)
            attributes.update(snapshot.metrics)
            enriched.append(
                Instrument(
                    instrument_id=instrument.instrument_id,
                    market=instrument.market,
                    symbol=instrument.symbol,
                    asset_type=instrument.asset_type,
                    currency=instrument.currency,
                    exchange=instrument.exchange,
                    status=instrument.status,
                    attributes=attributes,
                )
            )
        return enriched


def build_point_in_time_safe_snapshots(
    market_data_provider: MarketDataProvider,
    instruments: Iterable[Instrument],
    as_of: date,
) -> List[FundamentalSnapshot]:
    as_of_dt = datetime.combine(as_of, datetime.max.time())
    snapshots: List[FundamentalSnapshot] = []
    for instrument in instruments:
        history = market_data_provider.get_price_history(instrument.instrument_id, as_of_dt, 60)
        if not history:
            continue
        closes = [bar.close for bar in history]
        turnovers = [bar.turnover for bar in history]
        metrics: Dict[str, object] = {
            "latest_price": closes[-1],
        }
        if len(closes) >= 6:
            metrics["price_return_5"] = _safe_return(closes, 5)
        if len(closes) >= 21:
            metrics["price_return_20"] = _safe_return(closes, 20)
            metrics["average_turnover_20"] = _average_decimal(turnovers[-20:])
        if len(closes) >= 61:
            metrics["price_return_60"] = _safe_return(closes, 60)
            metrics["average_turnover_60"] = _average_decimal(turnovers[-60:])
        elif turnovers:
            metrics["average_turnover_20"] = _average_decimal(turnovers[-min(20, len(turnovers)) :])
        snapshots.append(FundamentalSnapshot(instrument.instrument_id, as_of, metrics))
    return snapshots


def build_default_bundle(
    market_data_provider: MarketDataProvider,
    market: Market,
    benchmark_id: str,
    as_of: date,
) -> ResearchDataBundle:
    instruments = market_data_provider.list_instruments(market)
    snapshots = build_point_in_time_safe_snapshots(market_data_provider, instruments, as_of)
    return ResearchDataBundle(
        market_data_provider=market_data_provider,
        fundamental_provider=InMemoryFundamentalProvider(snapshots),
        benchmark_provider=UnavailableBenchmarkProvider(),
        corporate_action_provider=UnavailableCorporateActionProvider(),
        benchmark_ids_by_market={market: benchmark_id},
    )


def _safe_return(closes: Sequence[object], window: int) -> Decimal:
    subset = list(closes)[-(window + 1) :]
    if len(subset) < window + 1:
        return Decimal("0")
    first = subset[0].close if isinstance(subset[0], Bar) else subset[0]
    last = subset[-1].close if isinstance(subset[-1], Bar) else subset[-1]
    if first == 0:
        return Decimal("0")
    return (last / first) - Decimal("1")


def _average_decimal(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))
