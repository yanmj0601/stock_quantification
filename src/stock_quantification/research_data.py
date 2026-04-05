from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from .interfaces import MarketDataProvider
from .models import Instrument, Market
from .runtime import CorporateAction


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


class BenchmarkProvider:
    def get_constituents(self, benchmark_id: str, as_of: date) -> List[BenchmarkConstituent]:
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


@dataclass(frozen=True)
class ResearchDataBundle:
    market_data_provider: MarketDataProvider
    fundamental_provider: FundamentalProvider
    benchmark_provider: BenchmarkProvider
    corporate_action_provider: CorporateActionProvider
    benchmark_ids_by_market: Dict[Market, str] = field(default_factory=dict)

    def default_benchmark_id(self, market: Market) -> Optional[str]:
        return self.benchmark_ids_by_market.get(market)

    def benchmark_weights(self, market: Market, as_of: date) -> Dict[str, Decimal]:
        benchmark_id = self.default_benchmark_id(market)
        if not benchmark_id:
            return {}
        return self.benchmark_provider.get_weights(benchmark_id, as_of)

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


def build_default_bundle(
    market_data_provider: MarketDataProvider,
    market: Market,
    benchmark_id: str,
    as_of: date,
) -> ResearchDataBundle:
    instruments = market_data_provider.list_instruments(market)
    snapshots = []
    constituents = []
    common_metrics = ("profitability", "quality", "leverage", "sector_momentum")
    equal_weight = Decimal("1") / Decimal(len(instruments)) if instruments else Decimal("0")
    for instrument in instruments:
        metrics = {
            metric: Decimal(str(instrument.attributes.get(metric, "0")))
            for metric in common_metrics
            if instrument.attributes.get(metric) is not None
        }
        snapshots.append(FundamentalSnapshot(instrument.instrument_id, as_of, metrics))
        if equal_weight > 0:
            constituents.append(BenchmarkConstituent(benchmark_id, instrument.instrument_id, equal_weight, as_of))
    return ResearchDataBundle(
        market_data_provider=market_data_provider,
        fundamental_provider=InMemoryFundamentalProvider(snapshots),
        benchmark_provider=InMemoryBenchmarkProvider(constituents),
        corporate_action_provider=InMemoryCorporateActionProvider([]),
        benchmark_ids_by_market={market: benchmark_id},
    )
