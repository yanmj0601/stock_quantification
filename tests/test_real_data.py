from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from stock_quantification.engine import InMemoryMarketDataProvider
from stock_quantification.models import AssetType, Bar, Instrument, Market
from stock_quantification.research_data import DataAvailability, build_default_bundle
from stock_quantification.real_data import (
    build_market_snapshot,
    fetch_cn_benchmark_history,
    fetch_cn_daily_history,
    fetch_us_daily_history,
)


class FakeResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload.encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class RealDataTests(TestCase):
    @patch("stock_quantification.real_data.urlopen")
    def test_fetch_cn_daily_history_parses_eastmoney_payload(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(
            'v_sh600000="1~PFBANK~600000~10.12~10.25~10.25~411518~184746~226773~10.12~1019~10.11~1038~10.10~1455~10.09~3415~10.08~4556~10.13~483~10.14~1494~10.15~293~10.16~671~10.17~614~~20260403161426~-0.13~-1.27~10.25~10.08~10.12/411518/417211984~411518~41721~0.12~";'
        )
        instrument, bars = fetch_cn_daily_history("600000")
        self.assertEqual(instrument.instrument_id, "CN.600000")
        self.assertEqual(instrument.exchange, "SSE")
        self.assertEqual(bars[-1].close, Decimal("10.12"))

    @patch("stock_quantification.real_data.urlopen")
    def test_fetch_us_daily_history_parses_nasdaq_payload(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(
            '{"data":{"tradesTable":{"rows":[{"date":"04/02/2026","close":"$255.92","volume":"31,289,370","open":"$254.20","high":"$256.13","low":"$250.65"},{"date":"04/01/2026","close":"$255.63","volume":"40,059,430","open":"$254.08","high":"$256.18","low":"$253.33"}]}}}'
        )
        instrument, bars = fetch_us_daily_history("AAPL")
        self.assertEqual(instrument.instrument_id, "US.AAPL")
        self.assertEqual(instrument.asset_type, AssetType.COMMON_STOCK)
        self.assertEqual(bars[-1].close, Decimal("255.92"))

    @patch("stock_quantification.real_data._http_get_json")
    def test_fetch_cn_benchmark_history_retries_after_param_error_payload(self, mock_http_get_json) -> None:
        mock_http_get_json.side_effect = [
            {"code": 0, "msg": "param error", "data": []},
            {
                "code": 0,
                "msg": "",
                "data": {
                    "sh000300": {
                        "day": [
                            ["2026-04-02", "4514.440", "4478.910", "4519.690", "4459.610", "190992161.000"],
                            ["2026-04-03", "4492.850", "4440.790", "4494.460", "4437.600", "168321705.000"],
                        ]
                    }
                },
            },
        ]
        instrument, bars = fetch_cn_benchmark_history(limit=2500)
        self.assertEqual(instrument.instrument_id, "CN.000300")
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[-1].close, Decimal("4440.790"))

    @patch("stock_quantification.real_data._build_real_research_bundle")
    @patch("stock_quantification.real_data.fetch_cn_detailed_history")
    def test_build_market_snapshot_uses_latest_common_session(self, mock_fetch, mock_bundle_builder) -> None:
        mock_fetch.side_effect = [
            (
                Instrument("CN.600000", Market.CN, "600000", AssetType.COMMON_STOCK, "CNY", "SSE"),
                [
                    Bar("CN.600000", datetime(2026, 4, 2, 15, 0, 0), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1, Decimal("1")),
                    Bar("CN.600000", datetime(2026, 4, 3, 15, 0, 0), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1, Decimal("1")),
                ],
            ),
            (
                Instrument("CN.000001", Market.CN, "000001", AssetType.COMMON_STOCK, "CNY", "SZSE"),
                [
                    Bar("CN.000001", datetime(2026, 4, 1, 15, 0, 0), Decimal("8"), Decimal("8"), Decimal("8"), Decimal("8"), 1, Decimal("1")),
                    Bar("CN.000001", datetime(2026, 4, 2, 15, 0, 0), Decimal("8"), Decimal("8"), Decimal("8"), Decimal("8"), 1, Decimal("1")),
                ],
            ),
        ]
        mock_bundle_builder.side_effect = (
            lambda provider, market, as_of, benchmark_id, **kwargs: build_default_bundle(
                provider,
                market,
                benchmark_id,
                as_of,
            )
        )
        snapshot = build_market_snapshot(Market.CN, ["600000", "000001"])
        self.assertEqual(snapshot.as_of.isoformat(), "2026-04-02T15:00:00")

    @patch("stock_quantification.real_data._build_real_research_bundle")
    @patch("stock_quantification.real_data.fetch_cn_detailed_history")
    def test_build_market_snapshot_respects_historical_as_of_date(self, mock_fetch, mock_bundle_builder) -> None:
        mock_fetch.side_effect = [
            (
                Instrument("CN.600000", Market.CN, "600000", AssetType.COMMON_STOCK, "CNY", "SSE"),
                [
                    Bar("CN.600000", datetime(2026, 3, 12, 15, 0, 0), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1, Decimal("1")),
                    Bar("CN.600000", datetime(2026, 3, 13, 15, 0, 0), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1, Decimal("1")),
                    Bar("CN.600000", datetime(2026, 3, 16, 15, 0, 0), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1, Decimal("1")),
                ],
            ),
            (
                Instrument("CN.000001", Market.CN, "000001", AssetType.COMMON_STOCK, "CNY", "SZSE"),
                [
                    Bar("CN.000001", datetime(2026, 3, 11, 15, 0, 0), Decimal("8"), Decimal("8"), Decimal("8"), Decimal("8"), 1, Decimal("1")),
                    Bar("CN.000001", datetime(2026, 3, 13, 15, 0, 0), Decimal("8"), Decimal("8"), Decimal("8"), Decimal("8"), 1, Decimal("1")),
                    Bar("CN.000001", datetime(2026, 3, 16, 15, 0, 0), Decimal("8"), Decimal("8"), Decimal("8"), Decimal("8"), 1, Decimal("1")),
                ],
            ),
        ]
        mock_bundle_builder.side_effect = (
            lambda provider, market, as_of, benchmark_id, **kwargs: build_default_bundle(
                provider,
                market,
                benchmark_id,
                as_of,
            )
        )
        snapshot = build_market_snapshot(Market.CN, ["600000", "000001"], as_of_date=datetime(2026, 3, 15).date())
        self.assertEqual(snapshot.as_of.isoformat(), "2026-03-13T15:00:00")
        self.assertEqual(
            snapshot.data_provider.get_next_bar("CN.600000", snapshot.as_of).timestamp.isoformat(),
            "2026-03-16T15:00:00",
        )

    @patch("stock_quantification.real_data._build_real_research_bundle")
    @patch("stock_quantification.real_data.fetch_cn_detailed_history")
    def test_build_market_snapshot_skips_symbols_that_fail_to_load(self, mock_fetch, mock_bundle_builder) -> None:
        mock_fetch.side_effect = [
            RuntimeError("temporary network error"),
            (
                Instrument("CN.000001", Market.CN, "000001", AssetType.COMMON_STOCK, "CNY", "SZSE"),
                [
                    Bar("CN.000001", datetime(2026, 4, 2, 15, 0, 0), Decimal("8"), Decimal("8"), Decimal("8"), Decimal("8"), 1, Decimal("1")),
                    Bar("CN.000001", datetime(2026, 4, 3, 15, 0, 0), Decimal("8"), Decimal("8"), Decimal("8"), Decimal("8"), 1, Decimal("1")),
                ],
            ),
        ]
        mock_bundle_builder.side_effect = (
            lambda provider, market, as_of, benchmark_id, **kwargs: build_default_bundle(
                provider,
                market,
                benchmark_id,
                as_of,
            )
        )
        snapshot = build_market_snapshot(Market.CN, ["600000", "000001"])
        instrument_ids = {instrument.instrument_id for instrument in snapshot.data_provider.list_instruments(Market.CN)}
        self.assertIn("CN.000001", instrument_ids)
        self.assertNotIn("CN.600000", instrument_ids)

    @patch("stock_quantification.real_data._fetch_market_benchmark_constituents", side_effect=RuntimeError("benchmark unavailable"))
    @patch("stock_quantification.real_data._fetch_market_fundamentals", side_effect=AssertionError("historical path should not call snapshot fundamentals"))
    @patch("stock_quantification.real_data.fetch_us_benchmark_history")
    @patch("stock_quantification.real_data.fetch_us_daily_history")
    def test_build_market_snapshot_historical_path_uses_safe_metrics_and_marks_benchmark_unavailable(
        self,
        mock_fetch_us_daily_history,
        mock_fetch_us_benchmark_history,
        _mock_fetch_market_fundamentals,
        _mock_fetch_market_benchmark_constituents,
    ) -> None:
        mock_fetch_us_daily_history.return_value = (
            Instrument("US.AAPL", Market.US, "AAPL", AssetType.COMMON_STOCK, "USD", "NASDAQ"),
            [
                Bar("US.AAPL", datetime(2026, 3, 4, 16, 0, 0), Decimal("98"), Decimal("98"), Decimal("98"), Decimal("98"), 1, Decimal("1000")),
                Bar("US.AAPL", datetime(2026, 3, 5, 16, 0, 0), Decimal("99"), Decimal("99"), Decimal("99"), Decimal("99"), 1, Decimal("1000")),
                Bar("US.AAPL", datetime(2026, 3, 6, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 1, Decimal("1000")),
                Bar("US.AAPL", datetime(2026, 3, 9, 16, 0, 0), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), 1, Decimal("1000")),
                Bar("US.AAPL", datetime(2026, 3, 12, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 1, Decimal("1000")),
                Bar("US.AAPL", datetime(2026, 3, 13, 16, 0, 0), Decimal("102"), Decimal("102"), Decimal("102"), Decimal("102"), 1, Decimal("1000")),
                Bar("US.AAPL", datetime(2026, 3, 16, 16, 0, 0), Decimal("104"), Decimal("104"), Decimal("104"), Decimal("104"), 1, Decimal("1000")),
            ],
        )
        mock_fetch_us_benchmark_history.return_value = (
            Instrument("US.SPY", Market.US, "SPY", AssetType.ETF, "USD", "NYSE"),
            [
                Bar("US.SPY", datetime(2026, 3, 4, 16, 0, 0), Decimal("98"), Decimal("98"), Decimal("98"), Decimal("98"), 1, Decimal("1000")),
                Bar("US.SPY", datetime(2026, 3, 5, 16, 0, 0), Decimal("99"), Decimal("99"), Decimal("99"), Decimal("99"), 1, Decimal("1000")),
                Bar("US.SPY", datetime(2026, 3, 6, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 1, Decimal("1000")),
                Bar("US.SPY", datetime(2026, 3, 9, 16, 0, 0), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), 1, Decimal("1000")),
                Bar("US.SPY", datetime(2026, 3, 12, 16, 0, 0), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 1, Decimal("1000")),
                Bar("US.SPY", datetime(2026, 3, 13, 16, 0, 0), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), 1, Decimal("1000")),
                Bar("US.SPY", datetime(2026, 3, 16, 16, 0, 0), Decimal("102"), Decimal("102"), Decimal("102"), Decimal("102"), 1, Decimal("1000")),
            ],
        )

        snapshot = build_market_snapshot(Market.US, ["AAPL"], as_of_date=date(2026, 3, 13))
        bundle = snapshot.research_data_bundle
        self.assertEqual(bundle.benchmark_status(Market.US, snapshot.as_of.date()), DataAvailability.UNAVAILABLE)
        self.assertFalse(bundle.benchmark_is_available(Market.US, snapshot.as_of.date()))
        self.assertEqual(bundle.benchmark_weights(Market.US, snapshot.as_of.date()), {})
        self.assertEqual(bundle.corporate_action_status("US.AAPL", snapshot.as_of.date(), snapshot.as_of.date()), DataAvailability.UNAVAILABLE)
        enriched = bundle.fundamental_provider.get_snapshot("US.AAPL", snapshot.as_of.date())
        self.assertIsNotNone(enriched)
        assert enriched is not None
        self.assertIn("latest_price", enriched.metrics)
        self.assertIn("price_return_5", enriched.metrics)
        self.assertNotIn("profitability", enriched.metrics)
        self.assertNotIn("quality", enriched.metrics)
