from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

from .backtest import build_forward_return_report, serialize_backtest_report
from .cli import run_market
from .engine import AStockSelectionStrategy, StandardStrategyRunner, USStockSelectionStrategy
from .models import ExecutionMode, Market, RuntimeMode
from .artifacts import read_json_artifact, write_json_artifact, write_text_artifact
from .real_data import build_market_snapshot, fetch_cn_benchmark_history, fetch_us_benchmark_history

ROOT_DIR = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT_DIR / "artifacts"
TEMPLATES_ROOT = ROOT_DIR / "templates"
STATIC_ROOT = ROOT_DIR / "static"

DEFAULT_PAGE_TITLE = "Stock Quantification Dashboard"
FACTOR_CATALOG: Dict[str, Dict[str, str]] = {
    "rel_ret_20": {"label": "20日相对强度", "description": "近20个交易日相对基准的强弱"},
    "rel_ret_60": {"label": "60日相对强度", "description": "近60个交易日相对基准的强弱"},
    "trend": {"label": "趋势强度", "description": "价格趋势是否持续向上"},
    "liquidity": {"label": "流动性", "description": "成交活跃度和交易便利度"},
    "profitability": {"label": "盈利能力", "description": "公司赚钱能力和利润质量"},
    "quality": {"label": "经营质量", "description": "经营稳健度和财务质量"},
    "volatility": {"label": "波动率", "description": "价格波动大小，通常越低越稳"},
    "drawdown": {"label": "回撤", "description": "阶段高点回落幅度，通常越低越稳"},
}


@dataclass(frozen=True)
class ArtifactEntry:
    relative_path: str
    display_name: str
    mtime: float
    summary: Dict[str, Any]


@dataclass(frozen=True)
class WebResponse:
    status: int
    content_type: str
    body: bytes
    headers: Dict[str, str] | None = None


class DashboardState:
    def __init__(self) -> None:
        self.chat_messages = deque(maxlen=24)
        self.flash_messages = deque(maxlen=8)
        self.last_run_results: List[Dict[str, Any]] = []
        self.last_factor_backtest_result: Optional[Dict[str, Any]] = None

    def push_chat(self, user_message: str, assistant_message: str) -> None:
        self.chat_messages.append({"role": "user", "content": user_message})
        self.chat_messages.append({"role": "assistant", "content": assistant_message})

    def push_flash(self, message: str) -> None:
        self.flash_messages.append(message)


class DashboardApp:
    def __init__(self, state: Optional[DashboardState] = None) -> None:
        self.state = state or DashboardState()

    def dispatch(self, method: str, path: str, query: Dict[str, List[str]], body: Dict[str, List[str]]) -> WebResponse:
        if path == "/":
            return self.render_home(query)
        if path == "/run" and method == "POST":
            return self.handle_run(body)
        if path == "/factor-backtest" and method == "POST":
            return self.handle_factor_backtest(body)
        if path == "/chat" and method == "POST":
            return self.handle_chat(body)
        if path == "/artifact-file":
            return self.serve_artifact(query)
        if path.startswith("/static/"):
            return self.serve_static(path)
        return self._text("Not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")

    def render_home(self, query: Dict[str, List[str]]) -> WebResponse:
        artifact_query = query.get("artifact", [None])[0]
        selected_artifact = self._resolve_selected_artifact(artifact_query)
        artifact_html = self._render_selected_artifact(selected_artifact)
        run_results_html = self._render_run_results()
        factor_backtest_html = self._render_factor_backtest_results()
        artifact_cards_html = self._render_recent_artifact_cards(selected_artifact.relative_path if selected_artifact else None)
        chat_html = self._render_chat_panel()
        flash_html = self._render_flash_messages()
        factor_form_html = self._render_factor_backtest_form()

        content = self._render_content(
            artifact_html=artifact_html,
            run_results_html=run_results_html,
            factor_backtest_html=factor_backtest_html,
            artifact_cards_html=artifact_cards_html,
            chat_html=chat_html,
            flash_html=flash_html,
            factor_form_html=factor_form_html,
        )
        return self._html_page(content)

    def handle_run(self, body: Dict[str, List[str]]) -> WebResponse:
        markets = self._markets_from_form(body.get("market", ["ALL"])[0])
        execution_mode = ExecutionMode(body.get("execution_mode", ["ADVISORY"])[0])
        runtime_mode = RuntimeMode(body.get("runtime_mode", ["PAPER"])[0])
        cash = Decimal(body.get("cash", ["100000"])[0])
        detail_limit = int(body.get("detail_limit", ["20"])[0])
        history_limit = int(body.get("history_limit", ["90"])[0])
        beta_window = int(body.get("beta_window", ["20"])[0])
        top_n = int(body.get("top_n", ["10"])[0])
        forward_days = int(body.get("forward_days", ["0"])[0])
        as_of_date_raw = body.get("as_of_date", [""])[0].strip()
        as_of_date = date.fromisoformat(as_of_date_raw) if as_of_date_raw else None

        run_results: List[Dict[str, Any]] = []
        for market in markets:
            symbols = self._symbols_for_market(market, body)
            run_results.append(
                run_market(
                    market=market,
                    symbols=symbols,
                    execution_mode=execution_mode,
                    runtime_mode=runtime_mode,
                    cash=cash,
                    detail_limit=detail_limit,
                    history_limit=history_limit,
                    beta_window=beta_window,
                    top_n=top_n,
                    as_of_date=as_of_date,
                    forward_days=forward_days,
                )
            )

        self.state.last_run_results = run_results
        self.state.push_flash(f"已运行 {len(run_results)} 个市场的本地策略。")
        target_artifact = self._artifact_query_path(run_results[0]["artifacts"]["json"]) if run_results else None
        target = f"/?artifact={quote(target_artifact)}" if target_artifact else "/"
        return self._redirect(target)

    def handle_factor_backtest(self, body: Dict[str, List[str]]) -> WebResponse:
        market = Market(body.get("factor_market", ["CN"])[0])
        selected_factors = body.get("factor", [])
        start_date = date.fromisoformat(body.get("factor_start_date", [""])[0])
        end_date = date.fromisoformat(body.get("factor_end_date", [""])[0])
        holding_sessions = int(body.get("factor_holding_sessions", ["5"])[0])
        detail_limit = int(body.get("factor_detail_limit", ["8"])[0])
        history_limit = int(body.get("factor_history_limit", ["60"])[0])
        top_n = int(body.get("factor_top_n", ["4"])[0])
        try:
            result = self._run_factor_backtest(
                market=market,
                selected_factors=selected_factors,
                start_date=start_date,
                end_date=end_date,
                holding_sessions=holding_sessions,
                detail_limit=detail_limit,
                history_limit=history_limit,
                top_n=top_n,
            )
        except Exception as exc:
            self.state.push_flash(f"因子回测失败：{exc}")
            return self._redirect("/")
        self.state.last_factor_backtest_result = result
        factor_names = "、".join(self._factor_label(factor_name) for factor_name in result["summary"]["selected_factors"])
        self.state.push_flash(f"{market.value} 因子回测已完成：{factor_names}")
        target_artifact = self._artifact_query_path(result["artifacts"]["json"])
        return self._redirect(f"/?artifact={quote(target_artifact)}")

    def handle_chat(self, body: Dict[str, List[str]]) -> WebResponse:
        message = body.get("message", [""])[0].strip()
        if message:
            assistant_message = f"本地回显：我收到了你的消息「{message}」。这里是交互占位，后面可以接真实 LLM。"
            self.state.push_chat(message, assistant_message)
            self.state.push_flash("已追加一条本地聊天记录。")
        return self._redirect("/")

    def serve_artifact(self, query: Dict[str, List[str]]) -> WebResponse:
        relative_path = query.get("path", [""])[0]
        if not relative_path:
            return self._text("Missing path", HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8")
        path = self._safe_artifact_path(relative_path)
        if path is None or not path.exists():
            return self._text("Artifact not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
        content_type = self._guess_content_type(path)
        return WebResponse(status=HTTPStatus.OK, content_type=content_type, body=path.read_bytes())

    def serve_static(self, path: str) -> WebResponse:
        rel = path.removeprefix("/static/").strip()
        if not rel:
            return self._text("Not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
        file_path = (STATIC_ROOT / rel).resolve()
        if STATIC_ROOT not in file_path.parents and file_path != STATIC_ROOT:
            return self._text("Forbidden", HTTPStatus.FORBIDDEN, "text/plain; charset=utf-8")
        if not file_path.exists():
            return self._text("Not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
        return WebResponse(status=HTTPStatus.OK, content_type=self._guess_content_type(file_path), body=file_path.read_bytes())

    def _render_selected_artifact(self, artifact: Optional[ArtifactEntry]) -> str:
        if artifact is None:
            return """
            <section class="panel panel--empty">
              <h2>当前没有选中的 artifact</h2>
              <p>先从右侧列表选一份回测结果，或者直接运行一次策略。</p>
            </section>
            """

        summary = artifact.summary.get("summary", {})
        if summary.get("artifact_type") == "factor_backtest":
            return self._render_factor_backtest_artifact(artifact, summary)
        daily = artifact.summary.get("daily", [])
        final_positions = summary.get("final_positions", [])
        chart_html = self._render_chart_block(artifact.relative_path, summary)
        daily_html = self._render_daily_preview(daily)
        positions_html = "".join(
            f"<li><strong>{escape(str(position.get('instrument_id', '')))}</strong><span>{escape(str(position.get('qty', '')))} 股</span><span>{escape(str(position.get('market_value', '')))}</span></li>"
            for position in final_positions[:6]
        )
        return f"""
        <section class="panel panel--selected">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Selected Artifact</p>
              <h2>{escape(artifact.display_name)}</h2>
            </div>
            <a class="button button--ghost" href="/artifact-file?path={quote(artifact.relative_path)}" target="_blank" rel="noreferrer">Open JSON</a>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Market", summary.get("market", "N/A"))}
            {self._summary_tile("Mode", summary.get("runtime_mode", "N/A"))}
            {self._summary_tile("Return", summary.get("total_return", "N/A"))}
            {self._summary_tile("Final NAV", summary.get("final_nav", "N/A"))}
            {self._summary_tile("Buy Fills", summary.get("buy_fill_count", "0"))}
            {self._summary_tile("Sell Fills", summary.get("sell_fill_count", "0"))}
          </div>
          {chart_html}
          <div class="panel__split">
            <div>
              <h3>Final Positions</h3>
              <ul class="position-list">{positions_html or '<li class="muted">暂无持仓</li>'}</ul>
            </div>
            <div>
              <h3>Daily Preview</h3>
              {daily_html}
            </div>
          </div>
        </section>
        """

    def _render_factor_backtest_artifact(self, artifact: ArtifactEntry, summary: Dict[str, Any]) -> str:
        daily = artifact.summary.get("daily", [])
        selected_factors = summary.get("selected_factors", [])
        factor_badges = "".join(
            f"<li><strong>{escape(self._factor_label(factor_name))}</strong><span>{escape(self._factor_description(factor_name))}</span></li>"
            for factor_name in selected_factors
        )
        daily_html = self._render_factor_backtest_daily_preview(daily)
        return f"""
        <section class="panel panel--selected">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Selected Artifact</p>
              <h2>{escape(artifact.display_name)}</h2>
            </div>
            <a class="button button--ghost" href="/artifact-file?path={quote(artifact.relative_path)}" target="_blank" rel="noreferrer">Open JSON</a>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Market", summary.get("market", "N/A"))}
            {self._summary_tile("观察区间", f"{summary.get('start_date', '')} -> {summary.get('end_date', '')}")}
            {self._summary_tile("平均收益", summary.get("average_return", "N/A"))}
            {self._summary_tile("平均超额", summary.get("average_excess_return", "N/A"))}
            {self._summary_tile("胜率", summary.get("average_win_rate", "N/A"))}
            {self._summary_tile("样本数", summary.get("observations", "0"))}
          </div>
          <div class="panel__split">
            <div>
              <h3>因子组合</h3>
              <ul class="position-list">{factor_badges or '<li class="muted">没有选中的因子</li>'}</ul>
            </div>
            <div>
              <h3>每日回测摘要</h3>
              {daily_html}
            </div>
          </div>
        </section>
        """

    def _render_run_results(self) -> str:
        if not self.state.last_run_results:
            return """
            <section class="panel panel--empty">
              <h2>最近运行</h2>
              <p>这里会展示你刚运行出来的本地策略结果。</p>
            </section>
            """
        cards = []
        for result in self.state.last_run_results:
            summary = result.get("summary", {})
            cards.append(
                f"""
                <article class="result-card">
                  <p class="eyebrow">{escape(summary.get('market', ''))} / {escape(summary.get('runtime_mode', ''))}</p>
                  <h3>{escape(summary.get('total_return', ''))}</h3>
                  <p>Final NAV {escape(summary.get('final_nav', ''))}</p>
                  <p>{escape(summary.get('start_date', ''))} - {escape(summary.get('end_date', ''))}</p>
                </article>
                """
            )
        return f"""
        <section class="panel">
          <h2>最近运行</h2>
          <div class="card-grid">{''.join(cards)}</div>
        </section>
        """

    def _render_factor_backtest_results(self) -> str:
        if not self.state.last_factor_backtest_result:
            return """
            <section class="panel panel--empty">
              <h2>因子回测结果</h2>
              <p>从下方勾选因子后运行一轮回测，这里会显示最近一次结果。</p>
            </section>
            """
        summary = self.state.last_factor_backtest_result.get("summary", {})
        factor_list = "、".join(self._factor_label(name) for name in summary.get("selected_factors", []))
        return f"""
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Factor Backtest</p>
              <h2>最近一次因子组合回测</h2>
            </div>
            <a class="button button--ghost" href="/artifact-file?path={quote(self._artifact_query_path(self.state.last_factor_backtest_result['artifacts']['json']))}" target="_blank" rel="noreferrer">Open JSON</a>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Market", summary.get("market", "N/A"))}
            {self._summary_tile("平均收益", summary.get("average_return", "N/A"))}
            {self._summary_tile("平均超额", summary.get("average_excess_return", "N/A"))}
            {self._summary_tile("胜率", summary.get("average_win_rate", "N/A"))}
            {self._summary_tile("样本数", summary.get("observations", "0"))}
            {self._summary_tile("最佳组合日", summary.get("best_trade_date", "N/A"))}
          </div>
          <p class="hero__copy">当前因子：{escape(factor_list)}</p>
        </section>
        """

    def _render_factor_backtest_form(self) -> str:
        factor_cards = []
        for factor_name, meta in FACTOR_CATALOG.items():
            factor_cards.append(
                f"""
                <label class="factor-chip">
                  <input type="checkbox" name="factor" value="{escape(factor_name)}" checked />
                  <span class="factor-chip__title">{escape(meta['label'])}</span>
                  <span class="factor-chip__meta">{escape(factor_name)}</span>
                  <span class="factor-chip__desc">{escape(meta['description'])}</span>
                </label>
                """
            )
        return f"""
        <section class="panel panel--form">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Factor Backtest</p>
              <h2>主流因子组合回测</h2>
            </div>
          </div>
          <form class="stack" method="post" action="/factor-backtest">
            <div class="grid-form">
              <label>Market<select name="factor_market"><option value="CN">CN</option><option value="US">US</option></select></label>
              <label>Start Date<input name="factor_start_date" value="2026-01-02" /></label>
              <label>End Date<input name="factor_end_date" value="2026-03-31" /></label>
              <label>Holding Sessions<input name="factor_holding_sessions" value="5" /></label>
              <label>Top N<input name="factor_top_n" value="4" /></label>
              <label>Detail Limit<input name="factor_detail_limit" value="8" /></label>
              <label>History Limit<input name="factor_history_limit" value="60" /></label>
            </div>
            <div class="factor-grid">{''.join(factor_cards)}</div>
            <button class="button button--primary" type="submit">运行因子回测</button>
          </form>
        </section>
        """

    def _render_recent_artifact_cards(self, selected_relative_path: Optional[str]) -> str:
        artifacts = self._recent_artifacts(limit=12)
        cards = []
        for artifact in artifacts:
            active_class = " result-card--active" if artifact.relative_path == selected_relative_path else ""
            cards.append(
                f"""
                <a class="result-card{active_class}" href="/?artifact={quote(artifact.relative_path)}">
                  <p class="eyebrow">{escape(artifact.summary.get('summary', {}).get('market', 'artifact'))}</p>
                  <h3>{escape(artifact.summary.get('summary', {}).get('runtime_mode', 'JSON'))}</h3>
                  <p>{escape(artifact.display_name)}</p>
                </a>
                """
            )
        return f"""
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Artifacts</p>
              <h2>最近结果</h2>
            </div>
            <a class="button button--ghost" href="/">Refresh</a>
          </div>
          <div class="card-grid card-grid--tight">{''.join(cards)}</div>
        </section>
        """

    def _render_chat_panel(self) -> str:
        messages = []
        for message in self.state.chat_messages:
            role = message["role"]
            css_class = "chat-bubble chat-bubble--assistant" if role == "assistant" else "chat-bubble chat-bubble--user"
            messages.append(
                f'<div class="{css_class}"><span>{escape(message["content"])}</span></div>'
            )
        return f"""
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Chat Placeholder</p>
              <h2>和我交互</h2>
            </div>
          </div>
          <div class="chat-thread">{''.join(messages) if messages else '<div class="muted">还没有消息，先发一条试试。</div>'}</div>
          <form class="stack" method="post" action="/chat">
            <textarea name="message" rows="3" placeholder="输入一句话，先做本地回显占位..."></textarea>
            <button class="button button--primary" type="submit">Send</button>
          </form>
        </section>
        """

    def _render_flash_messages(self) -> str:
        if not self.state.flash_messages:
            return ""
        items = "".join(f"<li>{escape(message)}</li>" for message in self.state.flash_messages)
        return f"""
        <section class="panel panel--flash">
          <ul class="flash-list">{items}</ul>
        </section>
        """

    def _render_daily_preview(self, daily: Iterable[Dict[str, Any]]) -> str:
        rows = []
        for row in list(daily)[-5:]:
            rows.append(
                f"""
                <tr>
                  <td>{escape(str(row.get('trade_date', '')))}</td>
                  <td>{escape(str(row.get('end_of_day_nav', '')))}</td>
                  <td>{len(row.get('fills', []))}</td>
                </tr>
                """
            )
        empty_row = "<tr><td colspan='3'>暂无数据</td></tr>"
        table_rows = "".join(rows) if rows else empty_row
        return f"""
        <table class="data-table">
          <thead><tr><th>Date</th><th>NAV</th><th>Fills</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
        """

    def _render_factor_backtest_daily_preview(self, daily: Iterable[Dict[str, Any]]) -> str:
        rows = []
        for row in list(daily)[-6:]:
            rows.append(
                f"""
                <tr>
                  <td>{escape(str(row.get('trade_date', '')))}</td>
                  <td>{escape(str(row.get('equal_weight_return', '')))}</td>
                  <td>{escape(str(row.get('excess_return', '')))}</td>
                  <td>{escape(str(row.get('win_rate', '')))}</td>
                </tr>
                """
            )
        table_rows = "".join(rows) if rows else "<tr><td colspan='4'>暂无数据</td></tr>"
        return f"""
        <table class="data-table">
          <thead><tr><th>Date</th><th>Return</th><th>Excess</th><th>Win Rate</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
        """

    def _render_chart_block(self, artifact_relative_path: str, summary: Dict[str, Any]) -> str:
        chart_path = self._chart_for_artifact(artifact_relative_path)
        if chart_path is None:
            return ""
        return f"""
        <div class="chart-block">
          <div class="chart-block__header">
            <h3>Equity Curve</h3>
            <a href="/artifact-file?path={quote(chart_path.relative_to(ARTIFACT_ROOT).as_posix())}" target="_blank" rel="noreferrer">Open PNG</a>
          </div>
          <img src="/artifact-file?path={quote(chart_path.relative_to(ARTIFACT_ROOT).as_posix())}" alt="Equity curve for {escape(summary.get('market', 'market'))}" />
        </div>
        """

    def _chart_for_artifact(self, artifact_relative_path: str) -> Optional[Path]:
        artifact_path = self._safe_artifact_path(artifact_relative_path)
        if artifact_path is None:
            return None
        chart_name = "march_2026_backtest_nav_curve.png"
        chart_path = artifact_path.parent / chart_name
        return chart_path if chart_path.exists() else None

    def _resolve_selected_artifact(self, artifact_query: Optional[str]) -> Optional[ArtifactEntry]:
        candidates = self._recent_artifacts(limit=20)
        if artifact_query:
            decoded = self._artifact_query_path(unquote(artifact_query))
            for artifact in candidates:
                if artifact.relative_path == decoded:
                    return artifact
            return None
        for preferred in ("cn_march_2026_backtest_rebalance.json", "us_march_2026_backtest_rebalance.json"):
            for artifact in candidates:
                if artifact.relative_path.endswith(preferred):
                    return artifact
        return candidates[0] if candidates else None

    def _recent_artifacts(self, limit: int = 12) -> List[ArtifactEntry]:
        entries: List[ArtifactEntry] = []
        for path in sorted(ARTIFACT_ROOT.glob("**/*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                summary = read_json_artifact(ARTIFACT_ROOT, path.relative_to(ARTIFACT_ROOT).as_posix())
            except Exception:
                continue
            if not isinstance(summary, dict):
                continue
            entries.append(
                ArtifactEntry(
                    relative_path=path.relative_to(ARTIFACT_ROOT).as_posix(),
                    display_name=path.name,
                    mtime=path.stat().st_mtime,
                    summary=summary,
                )
            )
            if len(entries) >= limit:
                break
        return entries

    def _symbols_for_market(self, market: Market, body: Dict[str, List[str]]) -> List[str]:
        field = "symbols_cn" if market == Market.CN else "symbols_us"
        raw_symbols = body.get(field, [""])[0]
        return [item.strip().upper() for item in raw_symbols.split(",") if item.strip()]

    def _markets_from_form(self, raw_market: str) -> List[Market]:
        if raw_market == "ALL":
            return [Market.CN, Market.US]
        return [Market(raw_market)]

    def _safe_artifact_path(self, relative_path: str) -> Optional[Path]:
        raw_path = Path(relative_path)
        candidate = raw_path.resolve() if raw_path.is_absolute() else (ARTIFACT_ROOT / relative_path).resolve()
        if ARTIFACT_ROOT not in candidate.parents and candidate != ARTIFACT_ROOT:
            return None
        return candidate

    def _artifact_query_path(self, artifact_path: str) -> str:
        path = Path(artifact_path)
        if path.is_absolute():
            try:
                return path.relative_to(ARTIFACT_ROOT).as_posix()
            except ValueError:
                return artifact_path
        return artifact_path

    def _html_page(self, content: str) -> WebResponse:
        title = DEFAULT_PAGE_TITLE
        template = self._load_template("dashboard.html")
        body = Template(template).safe_substitute(
            page_title=escape(title),
            content=content,
        )
        return self._text(body, HTTPStatus.OK, "text/html; charset=utf-8")

    def _render_content(
        self,
        artifact_html: str,
        run_results_html: str,
        factor_backtest_html: str,
        artifact_cards_html: str,
        chat_html: str,
        flash_html: str,
        factor_form_html: str,
    ) -> str:
        return f"""
        <main class="shell">
          <section class="hero">
            <div>
              <p class="eyebrow">Stock Quantification</p>
              <h1>双市场量化控制台</h1>
              <p class="hero__copy">本地查看回测/净值结果，触发一次策略运行，并保留一个和你交互的轻量聊天占位。</p>
            </div>
          </section>
          {flash_html}
          <section class="panel panel--form">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Run Strategy</p>
                <h2>本地运行</h2>
              </div>
            </div>
            <form class="grid-form" method="post" action="/run">
              <label>Market<select name="market"><option value="ALL">ALL</option><option value="CN">CN</option><option value="US">US</option></select></label>
              <label>Runtime<select name="runtime_mode"><option value="PAPER">PAPER</option><option value="BACKTEST">BACKTEST</option><option value="LIVE">LIVE</option></select></label>
              <label>Execution<select name="execution_mode"><option value="ADVISORY">ADVISORY</option><option value="AUTO">AUTO</option></select></label>
              <label>Cash<input name="cash" value="100000" /></label>
              <label>Top N<input name="top_n" value="10" /></label>
              <label>Detail Limit<input name="detail_limit" value="20" /></label>
              <label>History Limit<input name="history_limit" value="90" /></label>
              <label>Beta Window<input name="beta_window" value="20" /></label>
              <label>Forward Days<input name="forward_days" value="0" /></label>
              <label>As Of Date<input name="as_of_date" placeholder="2026-03-15" /></label>
              <label>A 股 Symbols<input name="symbols_cn" placeholder="600000,600036" /></label>
              <label>美股 Symbols<input name="symbols_us" placeholder="AAPL,MSFT" /></label>
              <div class="grid-form__actions"><button class="button button--primary" type="submit">Run</button></div>
            </form>
          </section>
          {factor_form_html}
          {artifact_html}
          {run_results_html}
          {factor_backtest_html}
          {artifact_cards_html}
          {chat_html}
        </main>
        """

    def _factor_label(self, factor_name: str) -> str:
        return FACTOR_CATALOG.get(factor_name, {}).get("label", factor_name)

    def _factor_description(self, factor_name: str) -> str:
        return FACTOR_CATALOG.get(factor_name, {}).get("description", factor_name)

    def _baseline_alpha_weights(self, market: Market) -> Dict[str, Decimal]:
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

    def _selected_factor_overrides(self, market: Market, selected_factors: Iterable[str]) -> Dict[str, Decimal]:
        base_weights = self._baseline_alpha_weights(market)
        available = [factor_name for factor_name in selected_factors if factor_name in base_weights]
        if not available:
            raise ValueError("至少选择一个当前市场可用的因子")
        total_abs = sum(abs(weight) for weight in base_weights.values())
        selected_abs = sum(abs(base_weights[factor_name]) for factor_name in available)
        scale = (total_abs / selected_abs) if selected_abs else Decimal("1")
        overrides = {factor_name: Decimal("0") for factor_name in base_weights}
        for factor_name in available:
            overrides[factor_name] = (base_weights[factor_name] * scale).quantize(Decimal("0.0001"))
        return overrides

    def _trading_dates_for_market(self, market: Market, start_date: date, end_date: date) -> List[date]:
        calendar_span = max(30, (end_date - start_date).days + 30)
        history_limit = max(120, min(1000, calendar_span * 2))
        if market == Market.CN:
            _, bars = fetch_cn_benchmark_history(limit=history_limit)
        else:
            _, bars = fetch_us_benchmark_history(lookback_days=calendar_span, limit=history_limit)
        return [bar.timestamp.date() for bar in bars if start_date <= bar.timestamp.date() <= end_date]

    def _run_factor_backtest(
        self,
        market: Market,
        selected_factors: List[str],
        start_date: date,
        end_date: date,
        holding_sessions: int,
        detail_limit: int,
        history_limit: int,
        top_n: int,
    ) -> Dict[str, Any]:
        selected = [factor_name for factor_name in selected_factors if factor_name in self._baseline_alpha_weights(market)]
        alpha_overrides = self._selected_factor_overrides(market, selected)
        trading_dates = self._trading_dates_for_market(market, start_date, end_date)
        snapshot_cache: Dict[date, Any] = {}
        daily_reports: List[Dict[str, Any]] = []

        for trade_date in trading_dates:
            snapshot_history_limit = max(
                history_limit,
                min(1000, max(120, (date.today() - trade_date).days + 40)),
            )
            snapshot = snapshot_cache.get(trade_date)
            if snapshot is None:
                snapshot = build_market_snapshot(
                    market,
                    symbols=[],
                    detail_limit=detail_limit,
                    history_limit=snapshot_history_limit,
                    as_of_date=trade_date,
                )
                snapshot_cache[trade_date] = snapshot
            if snapshot.as_of.date() != trade_date:
                continue
            available_ids = {
                instrument.instrument_id
                for instrument in snapshot.research_data_bundle.market_data_provider.list_instruments(market)
            }
            benchmark_weights = {
                instrument_id: weight
                for instrument_id, weight in snapshot.research_data_bundle.benchmark_weights(market, snapshot.as_of.date()).items()
                if instrument_id in available_ids
            }
            if market == Market.CN:
                strategy = AStockSelectionStrategy(
                    top_n=top_n,
                    benchmark_instrument_id=snapshot.benchmark_instrument_id,
                    benchmark_weights=dict(benchmark_weights),
                    alpha_weights_override=dict(alpha_overrides),
                )
            else:
                strategy = USStockSelectionStrategy(
                    top_n=top_n,
                    benchmark_instrument_id=snapshot.benchmark_instrument_id,
                    benchmark_weights=dict(benchmark_weights),
                    alpha_weights_override=dict(alpha_overrides),
                )
            runner = StandardStrategyRunner(snapshot.data_provider, snapshot.universe_provider, snapshot.calendar_provider)
            outputs = runner.run(strategy, snapshot.as_of)
            rankings = outputs.get("rankings", [])
            signals = outputs.get("signals", [])
            instrument_lookup = {
                instrument.instrument_id: instrument
                for instrument in snapshot.data_provider.list_instruments(market)
            }
            ranking_map = {str(row["instrument_id"]): row for row in rankings}
            recommended_stocks = [
                {
                    "instrument_id": signal.instrument_id,
                    "name": self._instrument_name_safe(instrument_lookup.get(signal.instrument_id), signal.instrument_id),
                    "sector": ranking_map.get(signal.instrument_id, {}).get("sector", "UNKNOWN"),
                    "score": signal.score,
                    "target_weight": ranking_map.get(signal.instrument_id, {}).get("target_weight", Decimal("0")),
                    "qty": 0,
                    "buy_price": None,
                    "reason": signal.reason,
                }
                for signal in signals
                if signal.instrument_id in instrument_lookup
            ]
            if not recommended_stocks:
                continue
            ranked_candidates = [
                {"instrument_id": row["instrument_id"], "score": row["score"]}
                for row in rankings
            ]
            report = build_forward_return_report(
                market,
                trade_date,
                recommended_stocks,
                ranked_candidates,
                holding_sessions=holding_sessions,
            )
            serialized = serialize_backtest_report(report)
            summary = serialized["summary"]
            daily_reports.append(
                {
                    "trade_date": summary["selection_date"],
                    "exit_date": summary["exit_date"],
                    "equal_weight_return": summary["equal_weight_return"],
                    "excess_return": summary["excess_return"],
                    "win_rate": summary["win_rate"],
                    "selected_count": summary["selected_count"],
                    "best_name": summary["best_name"],
                    "worst_name": summary["worst_name"],
                }
            )

        if not daily_reports:
            raise ValueError("当前参数下没有可用的回测结果")

        average_return = self._average_decimal(daily_reports, "equal_weight_return")
        average_excess_return = self._average_decimal(daily_reports, "excess_return")
        average_win_rate = self._average_decimal(daily_reports, "win_rate")
        best_day = max(daily_reports, key=lambda row: Decimal(str(row["equal_weight_return"])))
        worst_day = min(daily_reports, key=lambda row: Decimal(str(row["equal_weight_return"])))
        summary = {
            "artifact_type": "factor_backtest",
            "market": market.value,
            "runtime_mode": "FACTOR_BACKTEST",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "holding_sessions": holding_sessions,
            "selected_factors": selected,
            "selected_factor_labels": [self._factor_label(factor_name) for factor_name in selected],
            "average_return": str(average_return.quantize(Decimal("0.0001"))),
            "average_excess_return": str(average_excess_return.quantize(Decimal("0.0001"))),
            "average_win_rate": str(average_win_rate.quantize(Decimal("0.0001"))),
            "observations": len(daily_reports),
            "best_trade_date": best_day["trade_date"],
            "best_return": best_day["equal_weight_return"],
            "worst_trade_date": worst_day["trade_date"],
            "worst_return": worst_day["equal_weight_return"],
            "total_return": str(average_return.quantize(Decimal("0.0001"))),
            "final_nav": f"{len(daily_reports)} samples",
        }
        payload = {"summary": summary, "daily": daily_reports}
        digest = hashlib.sha1(
            f"{market.value}|{start_date.isoformat()}|{end_date.isoformat()}|{','.join(selected)}".encode("utf-8")
        ).hexdigest()[:10]
        relative_base = f"{end_date.isoformat()}/{market.value.lower()}_factor_backtest_{digest}"
        json_path = write_json_artifact(ARTIFACT_ROOT, f"{relative_base}.json", payload)
        md_lines = [
            f"# {market.value} Factor Backtest",
            "",
            f"- period: {start_date.isoformat()} to {end_date.isoformat()}",
            f"- selected_factors: {'、'.join(self._factor_label(factor_name) for factor_name in selected)}",
            f"- average_return: {summary['average_return']}",
            f"- average_excess_return: {summary['average_excess_return']}",
            f"- average_win_rate: {summary['average_win_rate']}",
        ]
        md_path = write_text_artifact(ARTIFACT_ROOT, f"{relative_base}.md", "\n".join(md_lines) + "\n")
        return {"summary": summary, "daily": daily_reports, "artifacts": {"json": json_path, "markdown": md_path}}

    def _average_decimal(self, rows: Iterable[Dict[str, Any]], key: str) -> Decimal:
        items = [Decimal(str(row[key])) for row in rows]
        if not items:
            return Decimal("0")
        return sum(items, Decimal("0")) / Decimal(len(items))

    def _instrument_name_safe(self, instrument: Any, fallback: str) -> str:
        if instrument is None:
            return fallback
        return str(
            instrument.attributes.get("name")
            or instrument.attributes.get("company_name")
            or instrument.attributes.get("display_name")
            or instrument.symbol
        )

    def _load_template(self, filename: str) -> str:
        template_path = TEMPLATES_ROOT / filename
        return template_path.read_text(encoding="utf-8")

    def _text(self, text: str, status: int, content_type: str) -> WebResponse:
        return WebResponse(status=status, content_type=content_type, body=text.encode("utf-8"))

    def _redirect(self, location: str) -> WebResponse:
        return WebResponse(status=HTTPStatus.SEE_OTHER, content_type="text/plain; charset=utf-8", body=b"", headers={"Location": location})

    def _summary_tile(self, label: str, value: Any) -> str:
        return f"""
        <div class="summary-tile">
          <span>{escape(label)}</span>
          <strong>{escape(str(value))}</strong>
        </div>
        """

    def _guess_content_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".json":
            return "application/json; charset=utf-8"
        if suffix == ".md":
            return "text/markdown; charset=utf-8"
        if suffix == ".png":
            return "image/png"
        if suffix in {".css"}:
            return "text/css; charset=utf-8"
        if suffix in {".js"}:
            return "application/javascript; charset=utf-8"
        return "application/octet-stream"


def create_app() -> DashboardApp:
    return DashboardApp()


class QuantificationHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "StockQuantificationWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        response = self.server.app.dispatch("GET", parsed.path, query, {})
        self._write_response(response)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        response = self.server.app.dispatch("GET", parsed.path, query, {})
        self._write_response(response, include_body=False)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("content-length", "0") or "0")
        raw_body = self.rfile.read(length).decode("utf-8") if length else ""
        body = parse_qs(raw_body)
        response = self.server.app.dispatch("POST", parsed.path, {}, body)
        self._write_response(response)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _write_response(self, response: WebResponse, include_body: bool = True) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        if response.headers:
            for key, value in response.headers.items():
                self.send_header(key, value)
        self.end_headers()
        if include_body and response.body:
            self.wfile.write(response.body)


class QuantificationThreadingHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, app: DashboardApp):
        super().__init__(server_address, RequestHandlerClass)
        self.app = app


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    app = create_app()
    server = QuantificationThreadingHTTPServer((host, port), QuantificationHTTPRequestHandler, app)
    print(f"Web dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the local quantification dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
