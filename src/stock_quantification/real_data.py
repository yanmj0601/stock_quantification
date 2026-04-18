from __future__ import annotations

import io
import json
import hashlib
import re
import socket
import subprocess
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import unescape
from http.client import RemoteDisconnected
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .artifacts import read_bytes_artifact, read_json_artifact, write_bytes_artifact, write_json_artifact
from .engine import InMemoryCalendarProvider, InMemoryMarketDataProvider, InMemoryUniverseProvider
from .models import AssetType, Bar, Instrument, Market
from .research_data import (
    BenchmarkConstituent,
    FundamentalSnapshot,
    InMemoryBenchmarkProvider,
    InMemoryCorporateActionProvider,
    InMemoryFundamentalProvider,
    ResearchDataBundle,
    UnavailableCorporateActionProvider,
    build_default_bundle,
    build_point_in_time_safe_snapshots,
)

_HTTP_HEADERS = {
    "user-agent": "Mozilla/5.0",
    "accept": "application/json,text/plain,*/*",
}

_SEC_HEADERS = {
    "user-agent": "Codex quant research bot contact openai@example.com",
    "accept": "application/json,text/plain,*/*",
}

_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_XLSX_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_SEC_TICKER_CACHE: Optional[Dict[str, str]] = None
_US_SCREENER_CACHE: Optional[Dict[str, Dict[str, str]]] = None
_CACHE_DIR = ".cache/stock_quantification"
_HTTP_CACHE_TTL_HOURS = 6
_HTTP_RETRY_COUNT = 3


class RealDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketSnapshot:
    market: Market
    as_of: datetime
    data_provider: InMemoryMarketDataProvider
    calendar_provider: InMemoryCalendarProvider
    universe_provider: InMemoryUniverseProvider
    research_data_bundle: ResearchDataBundle
    benchmark_instrument_id: Optional[str] = None


def _http_cache_path(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    host = re.sub(r"[^a-zA-Z0-9]+", "_", url.split("://", 1)[-1].split("/", 1)[0])
    return f"http/{host}/{digest}.bin"


def _sleep_before_retry(attempt: int) -> None:
    if attempt <= 0:
        return
    time.sleep(min(0.5 * attempt, 2.0))


def _http_get_json(url: str) -> Dict[str, object]:
    return json.loads(_http_get_bytes(url, headers=_HTTP_HEADERS).decode("utf-8"))


def _http_get_json_via_curl(url: str) -> Dict[str, object]:
    return json.loads(_http_get_bytes_via_curl(url, _HTTP_HEADERS).decode("utf-8"))


def _http_get_json_with_headers(url: str, headers: Mapping[str, str]) -> Dict[str, object]:
    return json.loads(_http_get_bytes(url, headers=headers).decode("utf-8"))


def _http_get_text(url: str, encoding: str = "utf-8", headers: Optional[Mapping[str, str]] = None) -> str:
    merged_headers = dict(_HTTP_HEADERS)
    if headers:
        merged_headers.update(headers)
    return _http_get_bytes(url, headers=merged_headers).decode(encoding, "ignore")


def _http_get_bytes(url: str, headers: Optional[Mapping[str, str]] = None) -> bytes:
    merged_headers = dict(_HTTP_HEADERS)
    if headers:
        merged_headers.update(headers)
    cache_path = _http_cache_path(url)
    cached = read_bytes_artifact(_CACHE_DIR, cache_path, max_age_hours=_HTTP_CACHE_TTL_HOURS)
    if cached is not None:
        return cached
    request = Request(url, headers=merged_headers)
    last_error: Optional[Exception] = None
    for attempt in range(_HTTP_RETRY_COUNT):
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read()
                write_bytes_artifact(_CACHE_DIR, cache_path, payload)
                return payload
        except (RemoteDisconnected, socket.timeout, TimeoutError) as exc:
            last_error = exc
            _sleep_before_retry(attempt + 1)
        except HTTPError as exc:
            raise RealDataError("HTTP error when loading %s: %s" % (url, exc)) from exc
        except URLError as exc:
            last_error = exc
            _sleep_before_retry(attempt + 1)
        except Exception as exc:
            last_error = exc
            _sleep_before_retry(attempt + 1)
    try:
        payload = _http_get_bytes_via_curl(url, merged_headers)
        write_bytes_artifact(_CACHE_DIR, cache_path, payload)
        return payload
    except RealDataError as exc:
        if last_error is not None:
            raise RealDataError("Network error when loading %s: %s" % (url, last_error)) from exc
        raise


def _http_get_bytes_via_curl(url: str, headers: Mapping[str, str]) -> bytes:
    try:
        args = ["curl", "-L", "--max-time", "20"]
        for key, value in headers.items():
            args.extend(["-H", f"{key}: {value}"])
        args.append(url)
        result = subprocess.run(
            args,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "ignore").strip()
        raise RealDataError("curl failed for %s: %s" % (url, stderr)) from exc
    return result.stdout


def _parse_decimal(raw: str) -> Decimal:
    return Decimal(raw.replace("$", "").replace(",", "").strip())


def _parse_optional_decimal(raw: object) -> Optional[Decimal]:
    if raw in (None, "", "N/A", "-", "--"):
        return None
    try:
        return _parse_decimal(str(raw).replace("%", ""))
    except Exception:
        return None


def _fraction_from_percent(raw: object) -> Optional[Decimal]:
    value = _parse_optional_decimal(raw)
    if value is None:
        return None
    return (value / Decimal("100")).quantize(Decimal("0.0001"))


def _safe_ratio(numerator: Optional[Decimal], denominator: Optional[Decimal]) -> Optional[Decimal]:
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    return (numerator / denominator).quantize(Decimal("0.0001"))


def _chunked(values: Sequence[str], size: int) -> Iterator[List[str]]:
    for index in range(0, len(values), size):
        yield list(values[index : index + size])


def _cn_exchange(symbol: str) -> str:
    return "SSE" if symbol.startswith("6") else "SZSE"


def _cn_secid(symbol: str) -> str:
    return ("1." if symbol.startswith("6") else "0.") + symbol


def _build_cn_url(symbol: str, limit: int) -> str:
    del limit
    return "https://qt.gtimg.cn/q=%s%s" % ("sh" if symbol.startswith("6") else "sz", symbol)


def _build_cn_history_url(symbol: str, limit: int) -> str:
    return (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        "secid=%s&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        "&klt=101&fqt=1&lmt=%s&end=20500101"
        % (_cn_secid(symbol), limit)
    )


def _build_us_url(symbol: str, from_date: str, to_date: str, limit: int, assetclass: str = "stocks") -> str:
    return "https://api.nasdaq.com/api/quote/%s/historical?%s" % (
        symbol,
        urlencode(
            {
                "assetclass": assetclass,
                "fromdate": from_date,
                "todate": to_date,
                "limit": str(limit),
            }
        ),
    )


def _build_cn_tencent_kline_url(symbol: str, limit: int, adjustment: str = "qfq") -> str:
    return "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s%s,day,,,%s,%s" % (
        "sh" if symbol.startswith("6") else "sz",
        symbol,
        limit,
        adjustment,
    )


def _build_cn_tencent_index_kline_url(symbol: str, limit: int) -> str:
    return "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=sh%s,day,,,%s" % (symbol, limit)


def _parse_date(raw: str, fmt: str) -> date:
    return datetime.strptime(raw, fmt).date()


def _extract_symbol_from_instrument_id(instrument_id: str) -> str:
    return instrument_id.split(".", 1)[1]


def _strip_html(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    return unescape(text).replace("\xa0", " ").strip()


def _parse_sec_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _latest_sec_fact(payload: Mapping[str, object], fact_names: Iterable[str]) -> Optional[Decimal]:
    facts = payload.get("facts", {}).get("us-gaap", {})
    best_entry = None
    best_rank = (-1, date.min, date.min)
    for fact_name in fact_names:
        node = facts.get(fact_name)
        if not isinstance(node, dict):
            continue
        for entry in node.get("units", {}).get("USD", []):
            if not isinstance(entry, dict) or entry.get("val") is None or not entry.get("end"):
                continue
            form = entry.get("form", "")
            rank = 1 if form in {"10-K", "10-K/A", "20-F", "20-F/A"} else 0
            end_date = _parse_sec_date(entry["end"])
            filed_date = _parse_sec_date(entry.get("filed", entry["end"]))
            entry_rank = (rank, end_date, filed_date)
            if entry_rank > best_rank:
                best_rank = entry_rank
                best_entry = entry
    if best_entry is None:
        return None
    return Decimal(str(best_entry["val"]))


def _load_sec_ticker_cache() -> Dict[str, str]:
    global _SEC_TICKER_CACHE
    if _SEC_TICKER_CACHE is not None:
        return _SEC_TICKER_CACHE
    payload = _http_get_json_with_headers("https://www.sec.gov/files/company_tickers.json", _SEC_HEADERS)
    _SEC_TICKER_CACHE = {
        str(item["ticker"]).upper(): str(item["cik_str"]).zfill(10)
        for item in payload.values()
        if isinstance(item, dict) and item.get("ticker") and item.get("cik_str") is not None
    }
    return _SEC_TICKER_CACHE


def _fetch_sse_symbol_directory() -> Dict[str, str]:
    cached = read_json_artifact(_CACHE_DIR, "universes/sse_symbols.json", max_age_hours=12)
    if isinstance(cached, dict):
        return {str(key): str(value) for key, value in cached.items()}
    payload = _http_get_text("https://www.sse.com.cn/js/common/ssesuggestdataAll.js")
    symbols: Dict[str, str] = {}
    for code, name in re.findall(r'val:"(\d{6})",val2:"([^"]+)"', payload):
        if code.startswith(("600", "601", "603", "605", "688")):
            symbols[code] = name
    write_json_artifact(_CACHE_DIR, "universes/sse_symbols.json", symbols)
    return symbols


def _fetch_szse_symbol_directory() -> Dict[str, str]:
    cached = read_json_artifact(_CACHE_DIR, "universes/szse_symbols.json", max_age_hours=12)
    if isinstance(cached, dict):
        return {str(key): str(value) for key, value in cached.items()}
    workbook = _http_get_bytes(
        "https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1"
    )
    with zipfile.ZipFile(io.BytesIO(workbook)) as archive:
        worksheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows = worksheet.find(f"{_XLSX_NS}sheetData")
        symbols: Dict[str, str] = {}
        for row in list(rows)[1:]:
            values: List[str] = []
            for cell in row:
                inline = cell.find(f"{_XLSX_NS}is")
                value = cell.find(f"{_XLSX_NS}v")
                if inline is not None:
                    values.append("".join(node.text or "" for node in inline.iter(f"{_XLSX_NS}t")))
                elif value is not None:
                    values.append(value.text or "")
                else:
                    values.append("")
            if len(values) < 6:
                continue
            code = values[4].strip()
            name = values[5].strip()
            if re.fullmatch(r"\d{6}", code):
                symbols[code] = name
    write_json_artifact(_CACHE_DIR, "universes/szse_symbols.json", symbols)
    return symbols


def _fetch_cn_quote_batch(symbols: Sequence[str]) -> Dict[str, Dict[str, object]]:
    if not symbols:
        return {}
    results: Dict[str, Dict[str, object]] = {}
    for batch in _chunked(list(symbols), 60):
        query = ",".join(f"{'sh' if symbol.startswith('6') else 'sz'}{symbol}" for symbol in batch)
        payload = _http_get_text(f"https://qt.gtimg.cn/q={query}", encoding="gbk")
        for record in payload.split(";"):
            if "~" not in record:
                continue
            try:
                fields = record.split('"')[1].split("~")
            except Exception:
                continue
            if len(fields) < 53:
                continue
            code = fields[2].strip()
            if not re.fullmatch(r"\d{6}", code):
                continue
            turnover = Decimal("0")
            if len(fields) > 35 and "/" in fields[35]:
                try:
                    turnover = _parse_decimal(fields[35].split("/")[2])
                except Exception:
                    turnover = Decimal("0")
            results[code] = {
                "name": fields[1].strip(),
                "close": _parse_optional_decimal(fields[3]),
                "turnover": turnover,
                "market_cap": _parse_optional_decimal(fields[44] if len(fields) > 44 else None),
                "float_market_cap": _parse_optional_decimal(fields[45] if len(fields) > 45 else None),
                "pb_ratio": _parse_optional_decimal(fields[46] if len(fields) > 46 else None),
                "pe_ttm": _parse_optional_decimal(fields[52] if len(fields) > 52 else None),
            }
    return results


def _resolve_full_cn_symbols(detail_limit: int) -> List[str]:
    directory = _fetch_sse_symbol_directory()
    directory.update(_fetch_szse_symbol_directory())
    quotes = _fetch_cn_quote_batch(sorted(directory))
    ranked = []
    for symbol, quote in quotes.items():
        close = quote.get("close")
        turnover = quote.get("turnover") or Decimal("0")
        if close is None or close < Decimal("3") or turnover <= 0:
            continue
        ranked.append(
            (
                Decimal(turnover),
                quote.get("float_market_cap") or quote.get("market_cap") or Decimal("0"),
                symbol,
            )
        )
    ranked.sort(reverse=True)
    return [symbol for _turnover, _market_cap, symbol in ranked[:detail_limit]]


def _is_us_common_stock_row(row: Mapping[str, str]) -> bool:
    name = str(row.get("name", "")).upper()
    industry = str(row.get("industry", "")).upper()
    if "DEPOSITARY" in name or "ADR" in name or "ETF" in name:
        return False
    if "WARRANT" in name or "RIGHT" in name or "UNIT" in name or "PREFERRED" in name:
        return False
    if "BLANK CHECKS" in industry:
        return False
    if "COMMON STOCK" in name or "ORDINARY SHARE" in name or "ORDINARY SHARES" in name:
        return True
    return False


def _fetch_us_screener_rows() -> List[Dict[str, str]]:
    global _US_SCREENER_CACHE
    if _US_SCREENER_CACHE is not None:
        return list(_US_SCREENER_CACHE.values())
    cached = read_json_artifact(_CACHE_DIR, "universes/us_screener_rows.json", max_age_hours=6)
    if isinstance(cached, list):
        _US_SCREENER_CACHE = {str(row.get("symbol", "")).upper(): row for row in cached if isinstance(row, dict)}
        return [row for row in cached if isinstance(row, dict)]
    try:
        payload = _http_get_json("https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true")
        rows = payload.get("data", {}).get("rows")
    except Exception:
        rows = None
    if not isinstance(rows, list):
        stale_cached = read_json_artifact(_CACHE_DIR, "universes/us_screener_rows.json")
        if isinstance(stale_cached, list):
            _US_SCREENER_CACHE = {str(row.get("symbol", "")).upper(): row for row in stale_cached if isinstance(row, dict)}
            return [row for row in stale_cached if isinstance(row, dict)]
        raise RealDataError("Nasdaq screener returned no rows")
    filtered_rows = [row for row in rows if isinstance(row, dict)]
    _US_SCREENER_CACHE = {str(row.get("symbol", "")).upper(): row for row in filtered_rows}
    write_json_artifact(_CACHE_DIR, "universes/us_screener_rows.json", filtered_rows)
    return filtered_rows


def _resolve_full_us_symbols(detail_limit: int) -> List[str]:
    ranked = []
    for row in _fetch_us_screener_rows():
        if not _is_us_common_stock_row(row):
            continue
        symbol = str(row.get("symbol", "")).upper()
        if not symbol or not re.fullmatch(r"[A-Z\.]+", symbol):
            continue
        lastsale = _parse_optional_decimal(row.get("lastsale"))
        volume = _parse_optional_decimal(row.get("volume"))
        market_cap = _parse_optional_decimal(row.get("marketCap"))
        if lastsale is None or volume is None or market_cap is None:
            continue
        turnover = lastsale * volume
        ranked.append((turnover, market_cap, symbol))
    ranked.sort(reverse=True)
    return [symbol for _turnover, _market_cap, symbol in ranked[:detail_limit]]


def load_symbol_directory(market: Market) -> List[Tuple[str, str]]:
    if market == Market.CN:
        directory = _fetch_sse_symbol_directory()
        directory.update(_fetch_szse_symbol_directory())
        return sorted(directory.items(), key=lambda item: item[0])
    if market == Market.US:
        rows = [row for row in _fetch_us_screener_rows() if _is_us_common_stock_row(row)]
        directory = {
            str(row.get("symbol", "")).upper(): str(row.get("name", "")).strip()
            for row in rows
            if str(row.get("symbol", "")).strip()
        }
        return sorted(directory.items(), key=lambda item: item[0])
    raise RealDataError("Unsupported market %s" % market.value)


def _us_company_name(symbol: str) -> str:
    screener_row = (_US_SCREENER_CACHE or {}).get(symbol.upper())
    if screener_row and screener_row.get("name"):
        return str(screener_row["name"]).strip()
    try:
        _fetch_us_screener_rows()
    except Exception:
        pass
    screener_row = (_US_SCREENER_CACHE or {}).get(symbol.upper())
    if screener_row and screener_row.get("name"):
        return str(screener_row["name"]).strip()
    return symbol


def _fetch_us_fundamental_snapshot(
    instrument: Instrument,
    as_of: date,
    deep: bool = True,
) -> Optional[FundamentalSnapshot]:
    screener_row = (_US_SCREENER_CACHE or {}).get(instrument.symbol.upper(), {})
    metrics: Dict[str, object] = {}
    sector = screener_row.get("sector")
    industry = screener_row.get("industry")
    market_cap = _parse_optional_decimal(screener_row.get("marketCap"))
    average_volume = _parse_optional_decimal(screener_row.get("volume"))
    dividend_yield = None
    if not screener_row:
        summary_url = f"https://api.nasdaq.com/api/quote/{instrument.symbol}/summary?assetclass=stocks"
        summary_payload = _http_get_json(summary_url)
        summary_data = summary_payload.get("data", {}).get("summaryData", {})
        sector = summary_data.get("Sector", {}).get("value")
        industry = summary_data.get("Industry", {}).get("value")
        market_cap = _parse_optional_decimal(summary_data.get("MarketCap", {}).get("value"))
        average_volume = _parse_optional_decimal(summary_data.get("AverageVolume", {}).get("value"))
        dividend_yield = _fraction_from_percent(summary_data.get("Yield", {}).get("value"))
    if sector and sector not in {"N/A", "-"}:
        metrics["sector"] = sector
    if industry and industry not in {"N/A", "-"}:
        metrics["industry"] = industry
    if market_cap is not None:
        metrics["market_cap"] = market_cap
    if average_volume is not None:
        metrics["average_volume"] = average_volume
    if dividend_yield is not None:
        metrics["dividend_yield"] = dividend_yield

    if not deep:
        return FundamentalSnapshot(instrument.instrument_id, as_of, metrics) if metrics else None

    cik = _load_sec_ticker_cache().get(instrument.symbol.upper())
    if cik:
        companyfacts = _http_get_json_with_headers(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", _SEC_HEADERS)
        net_income = _latest_sec_fact(companyfacts, ("NetIncomeLoss",))
        revenue = _latest_sec_fact(
            companyfacts,
            ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"),
        )
        assets = _latest_sec_fact(companyfacts, ("Assets",))
        equity = _latest_sec_fact(companyfacts, ("StockholdersEquity",))
        liabilities = _latest_sec_fact(companyfacts, ("Liabilities",))
        gross_profit = _latest_sec_fact(companyfacts, ("GrossProfit",))
        operating_income = _latest_sec_fact(companyfacts, ("OperatingIncomeLoss",))

        roe = _safe_ratio(net_income, equity)
        roa = _safe_ratio(net_income, assets)
        operating_margin = _safe_ratio(operating_income, revenue)
        gross_margin = _safe_ratio(gross_profit, revenue)
        leverage = _safe_ratio(liabilities, assets)

        profitability_components = [value for value in (roe, roa, operating_margin) if value is not None]
        quality_components = [value for value in (gross_margin, operating_margin) if value is not None]
        if profitability_components:
            metrics["profitability"] = (
                sum(profitability_components, Decimal("0")) / Decimal(len(profitability_components))
            ).quantize(Decimal("0.0001"))
        if quality_components:
            metrics["quality"] = (
                sum(quality_components, Decimal("0")) / Decimal(len(quality_components))
            ).quantize(Decimal("0.0001"))
        if leverage is not None:
            metrics["leverage"] = leverage

    if not metrics:
        return None
    return FundamentalSnapshot(instrument.instrument_id, as_of, metrics)


def _fetch_cn_tencent_quote_fields(symbol: str) -> List[str]:
    payload = _http_get_text(_build_cn_url(symbol, 0), encoding="gbk")
    try:
        return payload.split('"')[1].split("~")
    except Exception as exc:
        raise RealDataError("Unexpected Tencent quote payload for %s" % symbol) from exc


def _fetch_cn_fundamental_snapshot(
    instrument: Instrument,
    as_of: date,
    sector_by_symbol: Optional[Mapping[str, str]] = None,
    quote_snapshot: Optional[Mapping[str, object]] = None,
) -> Optional[FundamentalSnapshot]:
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get?"
        f"secid={_cn_secid(instrument.symbol)}&fields=f57,f58,f127,f116,f117,f162,f167,f173,f187"
    )
    metrics: Dict[str, object] = {}
    if quote_snapshot:
        sector = sector_by_symbol.get(instrument.symbol) if sector_by_symbol else None
        market_cap = _parse_optional_decimal(quote_snapshot.get("market_cap"))
        float_market_cap = _parse_optional_decimal(quote_snapshot.get("float_market_cap"))
        pe_ttm = _parse_optional_decimal(quote_snapshot.get("pe_ttm"))
        pb_ratio = _parse_optional_decimal(quote_snapshot.get("pb_ratio"))
        if sector:
            metrics["sector"] = sector
        if market_cap is not None:
            metrics["market_cap"] = market_cap
        if float_market_cap is not None:
            metrics["float_market_cap"] = float_market_cap
        if pe_ttm is not None and pe_ttm > 0:
            metrics["profitability"] = (Decimal("1") / pe_ttm).quantize(Decimal("0.0001"))
            metrics["pe_ttm"] = pe_ttm
        if pb_ratio is not None and pb_ratio > 0:
            metrics["quality"] = (Decimal("1") / pb_ratio).quantize(Decimal("0.0001"))
            metrics["pb_ratio"] = pb_ratio

    if metrics:
        return FundamentalSnapshot(instrument.instrument_id, as_of, metrics)

    try:
        payload = _http_get_json(url)
        data = payload.get("data")
        if isinstance(data, dict):
            sector = data.get("f127")
            market_cap = _parse_optional_decimal(data.get("f116"))
            float_market_cap = _parse_optional_decimal(data.get("f117"))
            profitability = _fraction_from_percent(data.get("f173"))
            quality = _fraction_from_percent(data.get("f187"))
            pb = _parse_optional_decimal(data.get("f167"))
            if sector:
                metrics["sector"] = sector
            if market_cap is not None:
                metrics["market_cap"] = market_cap
            if float_market_cap is not None:
                metrics["float_market_cap"] = float_market_cap
            if profitability is not None:
                metrics["profitability"] = profitability
            if quality is not None:
                metrics["quality"] = quality
            if pb is not None:
                metrics["pb_ratio"] = (pb / Decimal("100")).quantize(Decimal("0.0001")) if pb > 100 else pb
    except Exception:
        pass

    if not metrics:
        fields = _fetch_cn_tencent_quote_fields(instrument.symbol)
        sector = sector_by_symbol.get(instrument.symbol) if sector_by_symbol else None
        pe_ttm = _parse_optional_decimal(fields[52] if len(fields) > 52 else None)
        pb_ratio = _parse_optional_decimal(fields[46] if len(fields) > 46 else None)
        market_cap = _parse_optional_decimal(fields[44] if len(fields) > 44 else None)
        float_market_cap = _parse_optional_decimal(fields[45] if len(fields) > 45 else None)
        if sector:
            metrics["sector"] = sector
        if market_cap is not None:
            metrics["market_cap"] = market_cap
        if float_market_cap is not None:
            metrics["float_market_cap"] = float_market_cap
        if pe_ttm is not None and pe_ttm > 0:
            metrics["profitability"] = (Decimal("1") / pe_ttm).quantize(Decimal("0.0001"))
            metrics["pe_ttm"] = pe_ttm
        if pb_ratio is not None and pb_ratio > 0:
            metrics["quality"] = (Decimal("1") / pb_ratio).quantize(Decimal("0.0001"))
            metrics["pb_ratio"] = pb_ratio

    if not metrics:
        return None
    return FundamentalSnapshot(instrument.instrument_id, as_of, metrics)


def _fetch_market_fundamentals(
    market: Market,
    instruments: Iterable[Instrument],
    as_of: date,
    cn_sector_by_symbol: Optional[Mapping[str, str]] = None,
    deep_us_fundamentals: bool = True,
) -> List[FundamentalSnapshot]:
    snapshots: List[FundamentalSnapshot] = []
    cn_quotes = (
        _fetch_cn_quote_batch([instrument.symbol for instrument in instruments])
        if market == Market.CN
        else {}
    )
    for instrument in instruments:
        try:
            if market == Market.US:
                snapshot = _fetch_us_fundamental_snapshot(instrument, as_of, deep=deep_us_fundamentals)
            else:
                snapshot = _fetch_cn_fundamental_snapshot(
                    instrument,
                    as_of,
                    cn_sector_by_symbol,
                    quote_snapshot=cn_quotes.get(instrument.symbol),
                )
        except Exception:
            snapshot = None
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


def _parse_spy_holdings(workbook_bytes: bytes, benchmark_id: str) -> List[BenchmarkConstituent]:
    with zipfile.ZipFile(io.BytesIO(workbook_bytes)) as archive:
        shared_strings = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(text.text or "" for text in node.iter(f"{_XLSX_NS}t")) for node in shared_strings]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
        holdings_sheet = workbook.find(f"{_XLSX_NS}sheets")[0]
        relationship_id = holdings_sheet.attrib[f"{_XLSX_REL_NS}id"]
        sheet_xml = ET.fromstring(archive.read("xl/" + rel_map[relationship_id]))
        rows = sheet_xml.find(f"{_XLSX_NS}sheetData")

        parsed_rows: Dict[int, Dict[str, str]] = {}
        for row in rows:
            row_index = int(row.attrib["r"])
            cells: Dict[str, str] = {}
            for cell in row:
                reference = cell.attrib.get("r", "")
                column = "".join(ch for ch in reference if ch.isalpha())
                value_node = cell.find(f"{_XLSX_NS}v")
                value = value_node.text if value_node is not None else ""
                if cell.attrib.get("t") == "s" and value:
                    value = strings[int(value)]
                cells[column] = value
            parsed_rows[row_index] = cells

    as_of_match = re.search(r"As of (\d{2})-([A-Za-z]{3})-(\d{4})", parsed_rows.get(3, {}).get("B", ""))
    as_of = date.today()
    if as_of_match:
        as_of = datetime.strptime("-".join(as_of_match.groups()), "%d-%b-%Y").date()

    constituents: List[BenchmarkConstituent] = []
    for row_index in sorted(parsed_rows):
        if row_index < 6:
            continue
        row = parsed_rows[row_index]
        ticker = row.get("B", "").strip().upper()
        if not ticker:
            continue
        weight = _parse_optional_decimal(row.get("E"))
        if weight is None:
            continue
        constituents.append(
            BenchmarkConstituent(
                benchmark_id=benchmark_id,
                instrument_id=f"US.{ticker}",
                weight=(weight / Decimal("100")).quantize(Decimal("0.0000001")),
                as_of=as_of,
            )
        )
    return constituents


def _parse_csi300_rows(raw_html: str) -> Tuple[date, List[Tuple[str, str, Decimal]]]:
    table_match = re.search(r'<table[^>]*id="constituents"[^>]*>(.*?)</table>', raw_html, re.S)
    if not table_match:
        raise RealDataError("CSI 300 constituent table not found")
    as_of_match = re.search(r"<i>As of ([^<]+)</i>", raw_html)
    as_of = date.today()
    if as_of_match:
        as_of = datetime.strptime(as_of_match.group(1).strip(), "%d %B %Y").date()

    rows = re.findall(r"<tr>(.*?)</tr>", table_match.group(1), re.S)
    rows_with_metadata: List[Tuple[str, str, Decimal]] = []
    for row_html in rows[1:]:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)
        if len(cells) < 5:
            continue
        code_match = re.search(r">(\d{6})<", cells[0])
        if not code_match:
            continue
        symbol = code_match.group(1)
        sector = _strip_html(cells[2])
        weight = _parse_optional_decimal(_strip_html(cells[4]))
        if weight is None:
            continue
        rows_with_metadata.append((symbol, sector, (weight / Decimal("100")).quantize(Decimal("0.0000001"))))
    return as_of, rows_with_metadata


def _parse_csi300_constituents(raw_html: str, benchmark_id: str) -> List[BenchmarkConstituent]:
    as_of, rows_with_metadata = _parse_csi300_rows(raw_html)
    constituents: List[BenchmarkConstituent] = []
    for symbol, _sector, weight in rows_with_metadata:
        constituents.append(
            BenchmarkConstituent(
                benchmark_id=benchmark_id,
                instrument_id=f"CN.{symbol}",
                weight=weight,
                as_of=as_of,
            )
        )
    return constituents


def _fetch_market_benchmark_constituents(market: Market, benchmark_id: str) -> List[BenchmarkConstituent]:
    if market == Market.US:
        workbook_bytes = _http_get_bytes(
            "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
        )
        return _parse_spy_holdings(workbook_bytes, benchmark_id)
    payload = _http_get_json_with_headers(
        "https://en.wikipedia.org/w/api.php?action=parse&page=CSI_300_Index&prop=text&format=json",
        {"user-agent": "Mozilla/5.0", "accept": "application/json,text/plain,*/*"},
    )
    html = payload.get("parse", {}).get("text", {}).get("*")
    if not isinstance(html, str):
        raise RealDataError("Wikipedia CSI 300 payload missing HTML table")
    return _parse_csi300_constituents(html, benchmark_id)


def _build_real_research_bundle(
    market_data_provider: InMemoryMarketDataProvider,
    market: Market,
    as_of: date,
    benchmark_id: str,
    deep_us_fundamentals: bool = True,
) -> ResearchDataBundle:
    instruments = market_data_provider.list_instruments(market)
    fallback_bundle = build_default_bundle(market_data_provider, market, benchmark_id, as_of)
    historical_mode = as_of < date.today()

    constituents: List[BenchmarkConstituent] = []
    cn_sector_by_symbol: Dict[str, str] = {}
    try:
        if market == Market.CN:
            payload = _http_get_json_with_headers(
                "https://en.wikipedia.org/w/api.php?action=parse&page=CSI_300_Index&prop=text&format=json",
                {"user-agent": "Mozilla/5.0", "accept": "application/json,text/plain,*/*"},
            )
            html = payload.get("parse", {}).get("text", {}).get("*")
            if not isinstance(html, str):
                raise RealDataError("Wikipedia CSI 300 payload missing HTML table")
            cn_as_of, cn_rows = _parse_csi300_rows(html)
            constituents = [
                BenchmarkConstituent(
                    benchmark_id=benchmark_id,
                    instrument_id=f"CN.{symbol}",
                    weight=weight,
                    as_of=cn_as_of,
                )
                for symbol, _sector, weight in cn_rows
            ]
            cn_sector_by_symbol = {symbol: sector for symbol, sector, _weight in cn_rows}
        else:
            constituents = _fetch_market_benchmark_constituents(market, benchmark_id)
    except Exception:
        constituents = []

    if historical_mode:
        snapshots = build_point_in_time_safe_snapshots(market_data_provider, instruments, as_of)
    else:
        try:
            snapshots = _fetch_market_fundamentals(
                market,
                instruments,
                as_of,
                cn_sector_by_symbol,
                deep_us_fundamentals=deep_us_fundamentals,
            )
        except Exception:
            snapshots = []

        if not snapshots:
            snapshots = [
                fallback_bundle.fundamental_provider.get_snapshot(instrument.instrument_id, as_of)
                for instrument in instruments
            ]
            snapshots = [snapshot for snapshot in snapshots if snapshot is not None]

    if not constituents:
        constituents = fallback_bundle.benchmark_provider.get_constituents(benchmark_id, as_of)

    return ResearchDataBundle(
        market_data_provider=market_data_provider,
        fundamental_provider=InMemoryFundamentalProvider(snapshots),
        benchmark_provider=InMemoryBenchmarkProvider(constituents),
        corporate_action_provider=UnavailableCorporateActionProvider(),
        benchmark_ids_by_market={market: benchmark_id},
    )


def fetch_cn_daily_history(symbol: str, limit: int = 5) -> Tuple[Instrument, List[Bar]]:
    del limit
    try:
        payload = _http_get_text(_build_cn_url(symbol, 0), encoding="gbk")
    except Exception as exc:  # pragma: no cover - network-only fallback
        raise RealDataError("No A-share quote returned for %s: %s" % (symbol, exc)) from exc

    data = payload.split('"')[1].split("~")
    if len(data) < 36:
        raise RealDataError("Unexpected A-share quote payload for %s" % symbol)

    instrument = Instrument(
        instrument_id="CN.%s" % symbol,
        market=Market.CN,
        symbol=symbol,
        asset_type=AssetType.COMMON_STOCK,
        currency="CNY",
        exchange=_cn_exchange(symbol),
        attributes={"listed_days": 365, "is_st": False, "name": data[1]},
    )
    last_dt = datetime.strptime(data[30], "%Y%m%d%H%M%S")
    current_close = _parse_decimal(data[3])
    previous_close = _parse_decimal(data[4])
    current_open = _parse_decimal(data[5])
    current_volume = int(data[6])
    turnover = _parse_decimal(data[35].split("/")[2])
    previous_dt = last_dt - timedelta(days=1)
    bars = [
        Bar(
            instrument_id=instrument.instrument_id,
            timestamp=previous_dt.replace(hour=15, minute=0, second=0),
            open=previous_close,
            close=previous_close,
            high=previous_close,
            low=previous_close,
            volume=0,
            turnover=Decimal("0"),
            adjustment_flag="RAW",
        ),
        Bar(
            instrument_id=instrument.instrument_id,
            timestamp=last_dt.replace(hour=15, minute=0, second=0),
            open=current_open,
            close=current_close,
            high=_parse_decimal(data[33]),
            low=_parse_decimal(data[34]),
            volume=current_volume,
            turnover=turnover,
            adjustment_flag="RAW",
        ),
    ]
    return instrument, bars


def fetch_cn_detailed_history(symbol: str, limit: int = 90) -> Tuple[Instrument, List[Bar]]:
    quote_fields = _fetch_cn_tencent_quote_fields(symbol)
    payload = _http_get_json(_build_cn_tencent_kline_url(symbol, limit))
    data = payload.get("data", {}).get(f"{'sh' if symbol.startswith('6') else 'sz'}{symbol}", {})
    rows = data.get("qfqday") or data.get("day") or []
    if not rows:
        raise RealDataError("No A-share history returned for %s" % symbol)
    instrument = Instrument(
        instrument_id="CN.%s" % symbol,
        market=Market.CN,
        symbol=symbol,
        asset_type=AssetType.COMMON_STOCK,
        currency="CNY",
        exchange=_cn_exchange(symbol),
        attributes={"listed_days": 365, "is_st": False, "name": quote_fields[1]},
    )
    bars: List[Bar] = []
    for row in rows:
        close = _parse_decimal(row[2])
        volume = int(Decimal(str(row[5])))
        bars.append(
            Bar(
                instrument_id=instrument.instrument_id,
                timestamp=datetime.strptime(row[0] + " 15:00:00", "%Y-%m-%d %H:%M:%S"),
                open=_parse_decimal(row[1]),
                close=close,
                high=_parse_decimal(row[3]),
                low=_parse_decimal(row[4]),
                volume=volume,
                turnover=(close * Decimal(volume)).quantize(Decimal("0.01")),
                adjustment_flag="QFQ",
            )
        )
    return instrument, bars


def fetch_cn_benchmark_history(symbol: str = "000300", limit: int = 90) -> Tuple[Instrument, List[Bar]]:
    safe_limit = min(limit, 2000)
    payload = _http_get_json(_build_cn_tencent_index_kline_url(symbol, safe_limit))
    raw_data = payload.get("data", {})
    if isinstance(raw_data, list):
        payload = _http_get_json(_build_cn_tencent_index_kline_url(symbol, 2000))
        raw_data = payload.get("data", {})
    data = raw_data.get(f"sh{symbol}", {}) if isinstance(raw_data, dict) else {}
    rows = data.get("day") or []
    if not rows:
        raise RealDataError("No A-share benchmark history returned for %s" % symbol)
    instrument = Instrument(
        instrument_id="CN.%s" % symbol,
        market=Market.CN,
        symbol=symbol,
        asset_type=AssetType.ETF,
        currency="CNY",
        exchange="SSE",
        attributes={"name": "CSI 300"},
    )
    bars: List[Bar] = []
    for row in rows:
        close = _parse_decimal(row[2])
        volume = int(Decimal(str(row[5])))
        bars.append(
            Bar(
                instrument_id=instrument.instrument_id,
                timestamp=datetime.strptime(row[0] + " 15:00:00", "%Y-%m-%d %H:%M:%S"),
                open=_parse_decimal(row[1]),
                close=close,
                high=_parse_decimal(row[3]),
                low=_parse_decimal(row[4]),
                volume=volume,
                turnover=(close * Decimal(volume)).quantize(Decimal("0.01")),
                adjustment_flag="RAW",
            )
        )
    return instrument, bars


def fetch_us_daily_history(
    symbol: str,
    lookback_days: int = 14,
    limit: int = 10,
    assetclass: str = "stocks",
    asset_type: AssetType = AssetType.COMMON_STOCK,
) -> Tuple[Instrument, List[Bar]]:
    today = datetime.now().date()
    payload = _http_get_json(
        _build_us_url(
            symbol,
            from_date=(today - timedelta(days=lookback_days)).isoformat(),
            to_date=today.isoformat(),
            limit=limit,
            assetclass=assetclass,
        )
    )
    data = payload.get("data")
    trades_table = data.get("tradesTable") if isinstance(data, dict) else None
    rows = trades_table.get("rows") if isinstance(trades_table, dict) else None
    if not rows:
        raise RealDataError("No U.S. history returned for %s" % symbol)

    instrument = Instrument(
        instrument_id="US.%s" % symbol,
        market=Market.US,
        symbol=symbol,
        asset_type=asset_type,
        currency="USD",
        exchange="NASDAQ",
        attributes={"name": _us_company_name(symbol)},
    )
    bars: List[Bar] = []
    for row in reversed(rows):
        close = _parse_decimal(row["close"])
        volume = int(row["volume"].replace(",", ""))
        bars.append(
            Bar(
                instrument_id=instrument.instrument_id,
                timestamp=datetime.strptime(row["date"] + " 16:00:00", "%m/%d/%Y %H:%M:%S"),
                open=_parse_decimal(row["open"]),
                close=close,
                high=_parse_decimal(row["high"]),
                low=_parse_decimal(row["low"]),
                volume=volume,
                turnover=(close * Decimal(volume)).quantize(Decimal("0.01")),
                adjustment_flag="RAW",
            )
        )
    return instrument, bars


def fetch_us_benchmark_history(symbol: str = "SPY", lookback_days: int = 180, limit: int = 120) -> Tuple[Instrument, List[Bar]]:
    instrument, bars = fetch_us_daily_history(
        symbol,
        lookback_days=lookback_days,
        limit=limit,
        assetclass="etf",
        asset_type=AssetType.ETF,
    )
    return instrument, bars


def _resolve_symbols_for_scope(
    market: Market,
    symbols: Optional[Iterable[str]],
    detail_limit: int,
) -> List[str]:
    if symbols:
        return list(symbols)
    if market == Market.CN:
        return _resolve_full_cn_symbols(detail_limit)
    return _resolve_full_us_symbols(detail_limit)


def build_market_snapshot(
    market: Market,
    symbols: Optional[Iterable[str]] = None,
    detail_limit: int = 80,
    history_limit: int = 90,
    as_of_date: Optional[date] = None,
) -> MarketSnapshot:
    if market not in {Market.CN, Market.US}:
        raise RealDataError("Unsupported market %s" % market.value)
    full_market_mode = not symbols
    resolved_symbols = _resolve_symbols_for_scope(market, symbols, detail_limit)

    instruments: List[Instrument] = []
    bars_by_instrument: Dict[str, List[Bar]] = {}
    for symbol in resolved_symbols:
        try:
            if market == Market.CN:
                instrument, bars = fetch_cn_detailed_history(symbol, limit=history_limit)
            else:
                instrument, bars = fetch_us_daily_history(symbol, lookback_days=max(history_limit * 2, 180), limit=history_limit)
        except Exception:
            continue
        instruments.append(instrument)
        bars_by_instrument[instrument.instrument_id] = bars

    as_of_candidates: List[datetime] = []
    for bars in bars_by_instrument.values():
        eligible = bars
        if as_of_date is not None:
            eligible = [bar for bar in bars if bar.timestamp.date() <= as_of_date]
        if eligible:
            as_of_candidates.append(eligible[-1].timestamp)

    as_of: Optional[datetime] = min(as_of_candidates) if as_of_candidates else None

    if as_of is None:
        raise RealDataError("No bars fetched for market %s" % market.value)

    eligible_instrument_ids = {
        instrument_id
        for instrument_id, bars in bars_by_instrument.items()
        if any(bar.timestamp <= as_of for bar in bars)
    }
    instruments = [
        instrument
        for instrument in instruments
        if instrument.instrument_id in eligible_instrument_ids
    ]
    bars_by_instrument = {
        instrument_id: bars
        for instrument_id, bars in bars_by_instrument.items()
        if instrument_id in eligible_instrument_ids
    }

    benchmark_instrument_id = "CN.000300" if market == Market.CN else "US.SPY"
    try:
        if market == Market.CN:
            benchmark_instrument, benchmark_bars = fetch_cn_benchmark_history(limit=history_limit)
        else:
            benchmark_instrument, benchmark_bars = fetch_us_benchmark_history(limit=history_limit)
        benchmark_eligible = [bar for bar in benchmark_bars if bar.timestamp <= as_of]
        if benchmark_eligible:
            instruments.append(benchmark_instrument)
            bars_by_instrument[benchmark_instrument.instrument_id] = benchmark_bars
    except Exception:
        benchmark_instrument_id = None

    raw_data_provider = InMemoryMarketDataProvider(
        instruments,
        bars_by_instrument,
    )
    calendar_provider = InMemoryCalendarProvider({market: [as_of]})
    benchmark_id = "CSI300_PROXY" if market == Market.CN else "SP500_PROXY"
    research_data_bundle = _build_real_research_bundle(
        raw_data_provider,
        market,
        as_of.date(),
        benchmark_id,
        deep_us_fundamentals=not full_market_mode and not symbols,
    )
    enriched_instruments = research_data_bundle.enrich_instruments(instruments, as_of.date())
    data_provider = InMemoryMarketDataProvider(
        enriched_instruments,
        bars_by_instrument,
    )
    research_data_bundle = ResearchDataBundle(
        market_data_provider=data_provider,
        fundamental_provider=research_data_bundle.fundamental_provider,
        benchmark_provider=research_data_bundle.benchmark_provider,
        corporate_action_provider=research_data_bundle.corporate_action_provider,
        benchmark_ids_by_market=research_data_bundle.benchmark_ids_by_market,
    )
    universe_provider = InMemoryUniverseProvider(data_provider)
    return MarketSnapshot(
        market=market,
        as_of=as_of,
        data_provider=data_provider,
        calendar_provider=calendar_provider,
        universe_provider=universe_provider,
        research_data_bundle=research_data_bundle,
        benchmark_instrument_id=benchmark_instrument_id,
    )
