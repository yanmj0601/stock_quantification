from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from string import Template
import threading
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

from .backtest import (
    build_forward_return_report,
    build_rolling_strategy_backtest_report,
    serialize_backtest_report,
    serialize_rolling_backtest_report,
)
from .cli import run_market
from .engine import AStockSelectionStrategy, StandardStrategyRunner, USStockSelectionStrategy
from .local_paper import LocalPaperLedger
from .models import ExecutionMode, Market, RuntimeMode
from .ops import ProjectOpsStore
from .result_index import build_result_center_groups, list_results
from .research_diagnostics import (
    build_strategy_scorecard,
    serialize_alpha_mix,
    serialize_regime_summaries,
    serialize_strategy_scorecard,
    summarize_alpha_mix,
    summarize_regimes,
)
from .artifacts import read_json_artifact, write_json_artifact, write_text_artifact
from .real_data import (
    build_market_snapshot,
    fetch_cn_benchmark_history,
    fetch_us_benchmark_history,
    load_symbol_directory,
)
from .strategy_catalog import StrategyPreset, lookup_strategy_preset, strategy_presets_for_market
from .strategy_state import StrategyStateStore

ROOT_DIR = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT_DIR / "artifacts"
TEMPLATES_ROOT = ROOT_DIR / "templates"
STATIC_ROOT = ROOT_DIR / "static"

DEFAULT_PAGE_TITLE = "Stock Quantification Dashboard"
WEB_STATE_RELATIVE_ROOT = "web"
PROJECT_CONFIG_RELATIVE_PATH = f"{WEB_STATE_RELATIVE_ROOT}/project_config.json"
TASK_LOG_RELATIVE_PATH = f"{WEB_STATE_RELATIVE_ROOT}/task_logs.json"
MAX_RECENT_RUN_RESULTS = 48
PRIMARY_VIEW_ALIASES = {
    "overview": "paper",
    "paper": "paper",
    "workbench": "optimize",
    "optimize": "optimize",
    "run": "run",
    "results": "results",
}
PAPER_SUBVIEW_ALIASES = {
    "account": "main",
    "ledger": "holdings",
    "runtime": "trades",
    "main": "main",
    "holdings": "holdings",
    "trades": "trades",
}
RESULTS_SUBVIEW_ALIASES = {
    "research": "archive",
    "runtime": "archive",
    "archive": "archive",
    "champions": "champions",
    "challengers": "challengers",
    "drops": "drops",
}
PRIMARY_VIEW_TABS = {
    "paper": [("main", "Main / 主页面"), ("holdings", "Holdings / 持仓"), ("trades", "Trades / 交易")],
    "optimize": [("create", "Create / 创建"), ("history", "History / 历史"), ("detail", "Detail / 详情")],
    "run": [("create", "Create / 创建"), ("history", "History / 历史"), ("detail", "Detail / 详情")],
    "results": [("champions", "Champion / 冠军"), ("challengers", "Challenger / 挑战者"), ("drops", "Drop / 淘汰"), ("archive", "Archive / 归档")],
}
DEFAULT_PROJECT_CONFIG: Dict[str, Dict[str, Any]] = {
    "run_defaults": {
        "market": "ALL",
        "runtime_mode": "PAPER",
        "execution_mode": "ADVISORY",
        "broker": "NONE",
        "cash": "100000",
        "broker_account_id": "web-paper-us",
        "top_n": "10",
        "detail_limit": "20",
        "history_limit": "90",
        "beta_window": "20",
        "forward_days": "0",
        "as_of_date": "",
        "symbols_cn": "",
        "symbols_us": "",
        "route_orders": False,
    },
    "factor_defaults": {
        "factor_market": "CN",
        "factor_start_date": "2026-01-02",
        "factor_end_date": "2026-03-31",
        "factor_holding_sessions": "5",
        "factor_top_n": "4",
        "factor_detail_limit": "8",
        "factor_history_limit": "60",
        "factor_initial_cash": "100000",
        "factor_turnover_cap": "0.18",
        "factor_rebalance_buffer": "0.05",
    },
    "ui_defaults": {
        "paper_account_id": "web-paper-us",
        "paper_start_date": "",
        "paper_end_date": "",
        "paper_recent_trade_limit": "18",
    },
}
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
        self.last_local_paper_account: Optional[Dict[str, Any]] = None

    def push_chat(self, user_message: str, assistant_message: str) -> None:
        self.chat_messages.append({"role": "user", "content": user_message})
        self.chat_messages.append({"role": "assistant", "content": assistant_message})

    def push_flash(self, message: str, audience: Optional[str] = None) -> None:
        self.flash_messages.append(
            {
                "message": str(message),
                "audience": str(audience or "").strip().lower(),
            }
        )


class DashboardApp:
    def __init__(self, state: Optional[DashboardState] = None) -> None:
        self.state = state or DashboardState()
        self._symbol_catalog_cache: Dict[str, List[Dict[str, str]]] = {}

    def dispatch(self, method: str, path: str, query: Dict[str, List[str]], body: Dict[str, List[str]]) -> WebResponse:
        if not path.startswith("/static/"):
            self._ops_store().heartbeat("web")
        if path == "/":
            return self.render_home(query)
        if path == "/project/config":
            if method == "POST":
                return self.handle_project_config(body)
            return self.render_project_config()
        if path == "/project/logs":
            return self.render_task_logs(query)
        if path == "/project/ops":
            if method == "POST":
                return self.handle_release_active_job(body)
            return self.render_ops_center()
        if path == "/healthz":
            return self.render_healthz()
        if path == "/readyz":
            return self.render_readyz()
        if path == "/api/project/status":
            return self.render_status_api()
        if path == "/api/symbol-search":
            return self.render_symbol_search_api(query)
        if path == "/run" and method == "POST":
            return self.handle_run(body)
        if path == "/local-paper/reset" and method == "POST":
            return self.handle_local_paper_reset(body)
        if path == "/strategy-state/current" and method == "POST":
            return self.handle_strategy_state_current(body)
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
        view = self._dashboard_view(query)
        primary_view = self._primary_view_for_view(view)
        subview = self._primary_subview_for_view(primary_view, query)
        if view in {"workbench", "optimize"}:
            return self._render_optimize_page(query, primary_view=primary_view, subview=subview)
        if view == "run":
            return self._render_run_page(query, primary_view=primary_view, subview=subview)
        if view == "results":
            return self._render_results_page(query, primary_view=primary_view, subview=subview)
        if view == "paper":
            return self._render_paper_page(query, primary_view=primary_view, subview=subview)
        return self._render_overview_page(query, primary_view=primary_view, subview=subview)

    def render_project_config(self) -> WebResponse:
        config = self._load_project_config()
        flash_html = self._render_flash_messages("config")
        run_defaults = config["run_defaults"]
        factor_defaults = config["factor_defaults"]
        ui_defaults = config["ui_defaults"]
        recommended_account_id = self._recommended_account_id(str(run_defaults["market"]))
        config_cn_picker = self._render_symbol_picker(
            "config-cn",
            Market.CN,
            "symbols_cn",
            str(run_defaults["symbols_cn"]),
        )
        config_us_picker = self._render_symbol_picker(
            "config-us",
            Market.US,
            "symbols_us",
            str(run_defaults["symbols_us"]),
        )
        body = f"""
          {flash_html}
          <section class="panel settings-summary">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Settings Contract</p>
                <h2>Default Rules / 默认规则</h2>
                <p class="muted">这些设置只影响未来运行和默认页面行为，不会改写已经生成的结果或日志。</p>
              </div>
            </div>
            <div class="summary-grid">
              {self._summary_tile("Runtime Defaults / 运行默认值", f"{run_defaults.get('market', 'N/A')} · {run_defaults.get('runtime_mode', 'N/A')} · {run_defaults.get('execution_mode', 'N/A')}", "未来策略运行默认沿用这组运行规则")}
              {self._summary_tile("Research Defaults / 研究默认值", f"{factor_defaults.get('factor_market', 'N/A')} · {factor_defaults.get('factor_start_date', 'N/A')} -> {factor_defaults.get('factor_end_date', 'N/A')}", "未来因子回测默认沿用这组研究窗口")}
              {self._summary_tile("UI Defaults / 页面默认值", f"{ui_defaults.get('paper_account_id', 'N/A')} · {ui_defaults.get('paper_start_date', 'N/A')} -> {ui_defaults.get('paper_end_date', 'N/A')}", "页面打开时会优先使用这组展示偏好")}
            </div>
          </section>
          <section class="panel">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Runtime Defaults</p>
                <h2>运行默认值</h2>
              </div>
            </div>
            <form class="stack" method="post" action="/project/config">
              <div class="grid-form">
                <label>Market / 市场<span class="field-note">默认运行市场</span><select id="config-market-select" name="market"><option value="ALL"{' selected' if run_defaults['market'] == 'ALL' else ''}>ALL</option><option value="CN"{' selected' if run_defaults['market'] == 'CN' else ''}>CN</option><option value="US"{' selected' if run_defaults['market'] == 'US' else ''}>US</option></select></label>
                <label>Runtime / 运行语义<span class="field-note">默认实时/回放语义</span><select name="runtime_mode"><option value="PAPER"{' selected' if run_defaults['runtime_mode'] == 'PAPER' else ''}>PAPER</option><option value="BACKTEST"{' selected' if run_defaults['runtime_mode'] == 'BACKTEST' else ''}>BACKTEST</option><option value="LIVE"{' selected' if run_defaults['runtime_mode'] == 'LIVE' else ''}>LIVE</option></select></label>
                <label>Execution / 执行模式<span class="field-note">默认 advisory 或 auto</span><select name="execution_mode"><option value="ADVISORY"{' selected' if run_defaults['execution_mode'] == 'ADVISORY' else ''}>ADVISORY</option><option value="AUTO"{' selected' if run_defaults['execution_mode'] == 'AUTO' else ''}>AUTO</option></select></label>
                <label>Broker / 接入口<span class="field-note">默认 broker 类型</span><select name="broker"><option value="NONE"{' selected' if run_defaults['broker'] == 'NONE' else ''}>NONE</option><option value="LOCAL_PAPER"{' selected' if run_defaults['broker'] == 'LOCAL_PAPER' else ''}>LOCAL_PAPER</option></select></label>
                <label>Cash / 初始资金<span class="field-note">新账户起始现金</span><input name="cash" value="{escape(str(run_defaults['cash']))}" /></label>
                <label>Paper Account ID / 模拟盘账户<span class="field-note">默认本地模拟盘 ID</span><input id="config-broker-account-id" name="broker_account_id" value="{escape(str(run_defaults['broker_account_id']))}" data-recommended-account="{escape(recommended_account_id)}" /><span class="field-note field-note--accent" id="config-broker-account-recommendation">推荐账户名: {escape(recommended_account_id)}</span></label>
                <label>Top N / 选股数<span class="field-note">默认组合容量</span><input name="top_n" value="{escape(str(run_defaults['top_n']))}" /></label>
                <label>Detail Limit / 细节样本<span class="field-note">默认详细抓取数量</span><input name="detail_limit" value="{escape(str(run_defaults['detail_limit']))}" /></label>
                <label>History Limit / 历史窗口<span class="field-note">默认研究窗口 bars</span><input name="history_limit" value="{escape(str(run_defaults['history_limit']))}" /></label>
                <label>Beta Window / Beta 窗口<span class="field-note">默认 beta 估算区间</span><input name="beta_window" value="{escape(str(run_defaults['beta_window']))}" /></label>
                <label>Forward Days / 前瞻天数<span class="field-note">默认 forward report 持有天数</span><input name="forward_days" value="{escape(str(run_defaults['forward_days']))}" /></label>
                <label>As Of Date / 历史日期<span class="field-note">留空表示最近有效交易日</span><input name="as_of_date" value="{escape(str(run_defaults['as_of_date']))}" placeholder="2026-03-15" /></label>
                <div class="field-group field-group--full"><span>A 股 Symbols / A 股股票池</span><span class="field-note">默认 A 股自选池，留空表示全市场</span>{config_cn_picker}</div>
                <div class="field-group field-group--full"><span>美股 Symbols / 美股股票池</span><span class="field-note">默认美股自选池，留空表示全市场</span>{config_us_picker}</div>
                <label class="checkbox-field"><input type="checkbox" name="route_orders"{' checked' if run_defaults.get('route_orders') else ''} />Route Orders / 默认写入模拟盘</label>
              </div>
              <div class="panel__header">
                <div>
                  <p class="eyebrow">Research Defaults</p>
                  <h2>研究默认值</h2>
                </div>
              </div>
              <div class="grid-form">
                <label>Factor Market / 因子市场<span class="field-note">默认研究市场</span><select name="factor_market"><option value="CN"{' selected' if factor_defaults['factor_market'] == 'CN' else ''}>CN</option><option value="US"{' selected' if factor_defaults['factor_market'] == 'US' else ''}>US</option></select></label>
                <label>Start Date / 开始日期<span class="field-note">默认回测起点</span><input name="factor_start_date" value="{escape(str(factor_defaults['factor_start_date']))}" /></label>
                <label>End Date / 结束日期<span class="field-note">默认回测终点</span><input name="factor_end_date" value="{escape(str(factor_defaults['factor_end_date']))}" /></label>
                <label>Holding Sessions / 持有周期<span class="field-note">默认持有交易日数</span><input name="factor_holding_sessions" value="{escape(str(factor_defaults['factor_holding_sessions']))}" /></label>
                <label>Factor Top N / 因子组合数<span class="field-note">默认每次保留股票数</span><input name="factor_top_n" value="{escape(str(factor_defaults['factor_top_n']))}" /></label>
                <label>Factor Detail Limit / 细节样本<span class="field-note">默认详细样本数</span><input name="factor_detail_limit" value="{escape(str(factor_defaults['factor_detail_limit']))}" /></label>
                <label>Factor History Limit / 历史窗口<span class="field-note">默认因子历史 bars</span><input name="factor_history_limit" value="{escape(str(factor_defaults['factor_history_limit']))}" /></label>
                <label>Factor Initial Cash / 回测资金<span class="field-note">滚动回测组合的初始资金</span><input name="factor_initial_cash" value="{escape(str(factor_defaults['factor_initial_cash']))}" /></label>
                <label>Turnover Cap / 换手上限<span class="field-note">组合构建时的换手约束</span><input name="factor_turnover_cap" value="{escape(str(factor_defaults['factor_turnover_cap']))}" /></label>
                <label>Rebalance Buffer / 调仓缓冲<span class="field-note">减少小幅漂移导致的频繁换手</span><input name="factor_rebalance_buffer" value="{escape(str(factor_defaults['factor_rebalance_buffer']))}" /></label>
              </div>
              <div class="panel__header">
                <div>
                  <p class="eyebrow">UI Defaults</p>
                  <h2>界面默认值</h2>
                </div>
              </div>
              <div class="grid-form">
                <label>Paper Account / 默认模拟盘<span class="field-note">页面默认查看的模拟盘账户</span><input name="paper_account_id" value="{escape(str(ui_defaults['paper_account_id']))}" /></label>
                <label>Paper Start Date / 默认开始日期<span class="field-note">流水默认筛选起点</span><input name="paper_start_date" value="{escape(str(ui_defaults['paper_start_date']))}" placeholder="2026-04-01" /></label>
                <label>Paper End Date / 默认结束日期<span class="field-note">流水默认筛选终点</span><input name="paper_end_date" value="{escape(str(ui_defaults['paper_end_date']))}" placeholder="2026-04-30" /></label>
                <label>Paper Recent Trades / 流水条数<span class="field-note">默认展示最近成交数</span><input name="paper_recent_trade_limit" value="{escape(str(ui_defaults['paper_recent_trade_limit']))}" /></label>
              </div>
              <button class="button button--primary" type="submit">保存项目配置</button>
            </form>
          </section>
        """
        return self._html_page(
            self._render_page_shell(
                "config",
                title="Project Settings / 项目设置",
                eyebrow="Project Settings",
                description="集中维护运行默认值、研究默认值和页面偏好，让未来的默认行为更可预测。",
                body=body,
            ),
            title="Project Settings",
        )

    def render_task_logs(self, query: Optional[Dict[str, List[str]]] = None) -> WebResponse:
        flash_html = self._render_flash_messages("logs")
        filters = self._task_log_filters_from_query(query or {})
        raw_logs = list(reversed(self._load_task_logs()))
        logs = self._filter_task_logs(raw_logs, filters)
        rows = []
        for row in logs[:80]:
            metadata = row.get("metadata", {})
            meta_text = " | ".join(f"{key}={value}" for key, value in metadata.items()) if metadata else "-"
            rows.append(
                f"""
                <tr>
                  <td>{escape(str(row.get('created_at', '')))}</td>
                  <td>{escape(str(row.get('category', '')))}</td>
                  <td>{escape(str(row.get('action', '')))}</td>
                  <td>{escape(str(row.get('status', '')))}</td>
                  <td>{escape(str(row.get('detail', '')))}</td>
                  <td>{escape(meta_text)}</td>
                </tr>
                """
            )
        table_rows = "".join(rows) if rows else "<tr><td colspan='6'>当前还没有任务日志</td></tr>"
        categories = sorted({str(row.get("category", "")).strip() for row in raw_logs if str(row.get("category", "")).strip()})
        statuses = sorted({str(row.get("status", "")).strip() for row in raw_logs if str(row.get("status", "")).strip()})
        category_options = ['<option value="">All / 全部</option>'] + [
            f'<option value="{escape(value)}"{" selected" if filters["category"] == value else ""}>{escape(value)}</option>'
            for value in categories
        ]
        status_options = ['<option value="">All / 全部</option>'] + [
            f'<option value="{escape(value)}"{" selected" if filters["status"] == value else ""}>{escape(value)}</option>'
            for value in statuses
        ]
        body = f"""
          {flash_html}
          <section class="panel">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Log Summary</p>
                <h2>Current Log State / 当前日志状态</h2>
                <p class="muted">先看最近发生了什么，再进入筛选后的流水表，减少在大表里盲找的时间。</p>
              </div>
            </div>
            <div class="summary-grid">
              {self._summary_tile("Visible Logs / 当前日志", len(logs), "当前筛选条件下可见的日志条数")}
              {self._summary_tile("Latest Action / 最近动作", logs[0].get("action", "N/A") if logs else "N/A", "最近一条可见日志对应的动作")}
              {self._summary_tile("Latest Status / 最近状态", logs[0].get("status", "N/A") if logs else "N/A", "最近一条可见日志的结果状态")}
              {self._summary_tile("Latest Time / 最近时间", logs[0].get("created_at", "N/A") if logs else "N/A", "最近一条可见日志的时间")}
            </div>
          </section>
          <section class="panel">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Log Filters</p>
                <h2>Log Filters / 日志筛选</h2>
              </div>
            </div>
            <form class="grid-form report-filter-bar" method="get" action="/project/logs">
              <label>Start Date / 开始日期
                <input type="date" name="start_date" value="{escape(filters['start_date'])}" />
              </label>
              <label>End Date / 结束日期
                <input type="date" name="end_date" value="{escape(filters['end_date'])}" />
              </label>
              <label>Category / 类别
                <select name="category">{''.join(category_options)}</select>
              </label>
              <label>Status / 状态
                <select name="status">{''.join(status_options)}</select>
              </label>
              <div class="grid-form__actions">
                <button class="button button--primary" type="submit">应用筛选</button>
                <a class="button button--ghost" href="/project/logs">清空筛选</a>
              </div>
            </form>
          </section>
          <section class="panel">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Project Activity</p>
                <h2>Task Ledger / 任务流水</h2>
              </div>
            </div>
            <table class="data-table data-table--logs">
              <thead><tr><th>Time / 时间</th><th>Category / 类别</th><th>Action / 动作</th><th>Status / 状态</th><th>Detail / 说明</th><th>Metadata / 元数据</th></tr></thead>
              <tbody>{table_rows}</tbody>
            </table>
          </section>
        """
        return self._html_page(
            self._render_page_shell(
                "logs",
                title="Tasks & Logs / 任务日志",
                eyebrow="Tasks & Logs",
                description="按时间、类别和状态筛选项目流水，快速回看后台最近做了什么。",
                body=body,
            ),
            title="Tasks & Logs",
        )

    def render_ops_center(self) -> WebResponse:
        flash_html = self._render_flash_messages("ops")
        system_status = self._build_system_status()
        component_rows = "".join(
            f"""
            <tr>
              <td>{escape(str(row.get('name', '')))}</td>
              <td>{escape(str(row.get('status', '')))}</td>
              <td>{escape(str(row.get('detail', '')))}</td>
            </tr>
            """
            for row in system_status["components"]
        ) or "<tr><td colspan='3'>暂无组件状态</td></tr>"
        audit_rows = "".join(
            f"""
            <tr>
              <td>{escape(str(row.get('created_at', '')))}</td>
              <td>{escape(str(row.get('category', '')))}</td>
              <td>{escape(str(row.get('action', '')))}</td>
              <td>{escape(str(row.get('status', '')))}</td>
              <td>{escape(str(row.get('detail', '')))}</td>
            </tr>
            """
            for row in list(reversed(system_status["audit_events"]))[:40]
        ) or "<tr><td colspan='5'>暂无审计事件</td></tr>"
        job_history_rows = "".join(
            f"""
            <tr>
              <td>{escape(str(row.get('started_at', '')))}</td>
              <td>{escape(str(row.get('kind', '')))}</td>
              <td>{escape(str(row.get('status', '')))}</td>
              <td>{escape(str(row.get('duration_seconds', '0')))}s</td>
              <td>{escape(str(row.get('detail', '')))}</td>
            </tr>
            """
            for row in list(reversed(system_status["job_history"]))[:30]
        ) or "<tr><td colspan='5'>暂无后台任务历史</td></tr>"
        active_job = system_status.get("active_job")
        display_job = system_status.get("display_job")
        active_job_html = self._render_job_progress_panel(display_job if isinstance(display_job, dict) else None, "ops-job-progress")
        if active_job:
            active_job_html += """
            <form method="post" action="/project/ops" class="inline-form">
              <input type="hidden" name="action" value="release_active_job" />
              <button class="button button--ghost" type="submit">释放卡住任务</button>
            </form>
            """
        active_job_label = "无运行中任务"
        if isinstance(display_job, dict):
            active_job_label = str(display_job.get("kind") or display_job.get("job_kind") or display_job.get("status") or "RUNNING")
            stage = str(display_job.get("stage") or "").strip()
            if stage:
                active_job_label = f"{active_job_label} / {stage}"
        if system_status["overall_status"] == "READY" and not active_job:
            ops_conclusion = "系统可用，当前没有卡住任务。"
            ops_next_action = "继续观察，无需人工处理。"
        elif active_job:
            ops_conclusion = f"系统有运行中任务：{active_job_label}"
            ops_next_action = "先确认任务是否正常推进；若长时间无进展，再手动释放。"
        else:
            ops_conclusion = "系统存在告警，请优先检查组件健康和最近异常。"
            ops_next_action = "先看组件状态和审计事件，确认是否需要人工介入。"
        body = f"""
          {flash_html}
          <section class="panel ops-conclusion">
            <div class="panel__header">
              <div>
                <p class="eyebrow">System Conclusion</p>
                <h2>System Conclusion / 系统结论</h2>
                <p class="muted">{escape(ops_conclusion)}</p>
              </div>
            </div>
            <div class="summary-grid">
              {self._summary_tile("Overall / 总体状态", system_status["overall_status"], "当前后台是否具备基本可用性")}
              {self._summary_tile("Active Job / 当前任务", active_job_label, "最近心跳中的后台任务状态")}
              {self._summary_tile("Next Action / 建议动作", ops_next_action, "值班人员下一步应该先做什么")}
              {self._summary_tile("Components / 组件数", len(system_status["components"]), "当前纳入健康检查的组件数量")}
            </div>
          </section>
          <section class="panel">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Operational Snapshot</p>
                <h2>Operational Snapshot / 运维摘要</h2>
              </div>
            </div>
            <div class="summary-grid">
              {self._summary_tile("Artifacts / 工件数", system_status["artifact_count"], "最近归档可见工件数量")}
              {self._summary_tile("Logs / 任务日志", system_status["task_log_count"], "持久化任务日志条数")}
              {self._summary_tile("Paper Accounts / 模拟盘账户", system_status["paper_account_count"], "本地模拟盘账户数量")}
              {self._summary_tile("Broker / 券商凭证", "READY" if system_status["broker_credentials_ready"] else "MISSING", "券商凭证当前是否就绪")}
            </div>
          </section>
          <section class="panel">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Run Guard</p>
                <h2>Run Guard / 运行守护</h2>
              </div>
            </div>
            <div class="alert-grid">{active_job_html}</div>
          </section>
          <section class="panel">
            <div class="panel__split">
              <div>
                <h3>Components / 组件健康</h3>
                <table class="data-table">
                  <thead><tr><th>Name / 组件</th><th>Status / 状态</th><th>Detail / 说明</th></tr></thead>
                  <tbody>{component_rows}</tbody>
                </table>
              </div>
              <div>
                <h3>Job History / 后台任务历史</h3>
                <table class="data-table">
                  <thead><tr><th>Start / 开始</th><th>Kind / 类型</th><th>Status / 状态</th><th>Duration / 耗时</th><th>Detail / 说明</th></tr></thead>
                  <tbody>{job_history_rows}</tbody>
                </table>
              </div>
            </div>
          </section>
          <section class="panel">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Audit Events</p>
                <h2>Audit Events / 审计事件</h2>
              </div>
            </div>
            <table class="data-table">
              <thead><tr><th>Time / 时间</th><th>Category / 类别</th><th>Action / 动作</th><th>Status / 状态</th><th>Detail / 说明</th></tr></thead>
              <tbody>{audit_rows}</tbody>
            </table>
          </section>
        """
        return self._html_page(
            self._render_page_shell(
                "ops",
                title="Operations / 运维中心",
                eyebrow="Operations",
                description="先判断系统能不能用、有没有卡住任务，再进入组件健康、任务历史和审计细节。",
                body=body,
            ),
            title="Operations",
        )

    def _task_log_filters_from_query(self, query: Dict[str, List[str]]) -> Dict[str, str]:
        return {
            "start_date": query.get("start_date", [""])[0].strip(),
            "end_date": query.get("end_date", [""])[0].strip(),
            "category": query.get("category", [""])[0].strip(),
            "status": query.get("status", [""])[0].strip(),
        }

    def _filter_task_logs(self, logs: List[Dict[str, Any]], filters: Dict[str, str]) -> List[Dict[str, Any]]:
        filtered = list(logs)
        if filters["category"]:
            filtered = [row for row in filtered if str(row.get("category", "")).strip() == filters["category"]]
        if filters["status"]:
            filtered = [row for row in filtered if str(row.get("status", "")).strip() == filters["status"]]
        if filters["start_date"]:
            filtered = [row for row in filtered if str(row.get("created_at", ""))[:10] >= filters["start_date"]]
        if filters["end_date"]:
            filtered = [row for row in filtered if str(row.get("created_at", ""))[:10] <= filters["end_date"]]
        return filtered

    def handle_release_active_job(self, body: Dict[str, List[str]]) -> WebResponse:
        action = body.get("action", [""])[0].strip()
        if action != "release_active_job":
            self.state.push_flash("未知运维操作。", audience="ops")
            return self._redirect("/project/ops")
        ops_store = self._ops_store()
        state = ops_store.load_state()
        active_job = state.get("active_job")
        if not isinstance(active_job, dict):
            self.state.push_flash("当前没有可释放的运行中任务。", audience="ops")
            return self._redirect("/project/ops")
        ops_store.release_active_job(
            detail="Released active job from operations center.",
            metadata={"released_from": "web_ops"},
        )
        self._append_task_log(
            category="ops",
            action="release_active_job",
            status="SUCCESS",
            detail=f"手动释放运行中任务 {active_job.get('kind', 'UNKNOWN')}",
            metadata={"job_id": active_job.get("job_id", ""), "kind": active_job.get("kind", "UNKNOWN")},
        )
        self.state.push_flash(f"已释放任务：{active_job.get('kind', 'UNKNOWN')}。", audience="ops")
        return self._redirect("/project/ops")

    def render_healthz(self) -> WebResponse:
        payload = {"status": "ok", "checked_at": datetime.utcnow().isoformat(timespec="seconds")}
        return self._json(payload, HTTPStatus.OK)

    def render_readyz(self) -> WebResponse:
        system_status = self._build_system_status()
        payload = {
            "status": system_status["overall_status"],
            "ready": system_status["overall_status"] in {"READY", "WARN"},
            "checked_at": datetime.utcnow().isoformat(timespec="seconds"),
            "components": system_status["components"],
        }
        http_status = HTTPStatus.OK if payload["ready"] else HTTPStatus.SERVICE_UNAVAILABLE
        return self._json(payload, http_status)

    def render_status_api(self) -> WebResponse:
        system_status = self._build_system_status()
        return self._json(system_status, HTTPStatus.OK)

    def render_symbol_search_api(self, query: Dict[str, List[str]]) -> WebResponse:
        market_raw = query.get("market", [""])[0].strip().upper()
        keyword = query.get("q", [""])[0].strip().lower()
        limit_raw = query.get("limit", ["40"])[0].strip()
        try:
            market = Market(market_raw)
        except Exception:
            return self._json({"error": "invalid market"}, HTTPStatus.BAD_REQUEST)
        try:
            limit = max(1, min(int(limit_raw or "40"), 80))
        except ValueError:
            limit = 40
        catalog = self._symbol_catalog(market)
        if keyword:
            rows = [
                row for row in catalog
                if keyword in row["symbol"].lower() or keyword in row["name"].lower()
            ]
        else:
            rows = catalog
        return self._json({"market": market.value, "items": rows[:limit]}, HTTPStatus.OK)

    def handle_run(self, body: Dict[str, List[str]]) -> WebResponse:
        config = self._load_project_config()
        defaults = config["run_defaults"]
        view = self._requested_view(body, "workbench")
        try:
            markets = self._markets_from_form(body.get("market", [str(defaults["market"])])[0])
            execution_mode = ExecutionMode(body.get("execution_mode", [str(defaults["execution_mode"])])[0])
            runtime_mode = RuntimeMode(body.get("runtime_mode", [str(defaults["runtime_mode"])])[0])
            cash = self._parse_decimal_field(body.get("cash", [str(defaults["cash"])])[0], "Cash / 初始资金", minimum=Decimal("0.0001"))
            detail_limit = self._parse_int_field(body.get("detail_limit", [str(defaults["detail_limit"])])[0], "Detail Limit / 细节样本", minimum=1)
            history_limit = self._parse_int_field(body.get("history_limit", [str(defaults["history_limit"])])[0], "History Limit / 历史窗口", minimum=1)
            beta_window = self._parse_int_field(body.get("beta_window", [str(defaults["beta_window"])])[0], "Beta Window / Beta 窗口", minimum=1)
            top_n = self._parse_int_field(body.get("top_n", [str(defaults["top_n"])])[0], "Top N / 选股数", minimum=1)
            forward_days = self._parse_int_field(body.get("forward_days", [str(defaults["forward_days"])])[0], "Forward Days / 前瞻天数", minimum=0)
            as_of_date = self._parse_optional_date_field(body.get("as_of_date", [str(defaults["as_of_date"])])[0], "As Of Date / 历史日期")
            broker_raw = body.get("broker", [str(defaults["broker"])])[0].strip().upper()
            broker_name = None if broker_raw in {"", "NONE"} else broker_raw
            broker_account_id = body.get("broker_account_id", [str(defaults["broker_account_id"])])[0].strip() or None
            route_orders = body.get("route_orders", ["on" if defaults.get("route_orders") else ""])[0] in {"on", "1", "true", "TRUE"}
            selected_strategy_ids: Dict[str, Optional[str]] = {}
            for market in markets:
                field_name = f"selected_strategy_{market.value.lower()}"
                selected_strategy_id = body.get(field_name, [""])[0].strip() or None
                if selected_strategy_id is not None:
                    lookup_strategy_preset(market, selected_strategy_id)
                selected_strategy_ids[market.value] = selected_strategy_id
        except (InvalidOperation, ValueError, KeyError) as exc:
            self.state.push_flash(f"策略运行参数错误：{exc}", audience=view)
            return self._redirect(self._view_url(view))
        symbols_by_market = {
            market.value: self._symbols_for_market(market, body)
            for market in markets
        }
        reservation = self._ops_store().begin_job(
            "strategy_run",
            metadata={
                "markets": [market.value for market in markets],
                "execution_mode": execution_mode.value,
                "runtime_mode": runtime_mode.value,
                "broker": broker_name or "NONE",
            },
        )
        if not reservation.get("accepted"):
            active_job = reservation.get("active_job", {})
            self.state.push_flash(f"后台已有任务运行中：{active_job.get('kind', 'UNKNOWN')}，请稍后重试。", audience="ops")
            self._append_task_log(
                category="runtime",
                action="strategy_run",
                status="BLOCKED",
                detail="策略运行被运行守护拦截",
                metadata={"active_job": active_job.get("kind", "UNKNOWN")},
            )
            return self._redirect("/project/ops")
        job_id = str(reservation["job"]["job_id"])
        self._ops_store().update_active_job(
            job_id,
            progress_pct=5,
            stage="PREPARING",
            detail="正在准备运行参数和市场快照。",
            metadata={"total_markets": len(markets), "completed_markets": 0},
        )
        self._append_task_log(
            category="runtime",
            action="strategy_run",
            status="STARTED",
            detail=f"已提交 {len(markets)} 个市场的策略运行任务",
            metadata={
                "markets": ",".join(market.value for market in markets),
                "broker": broker_name or "NONE",
                "route_orders": route_orders,
                "account_id": broker_account_id or "",
            },
        )
        self.state.push_flash(f"策略任务已提交，正在后台运行 {len(markets)} 个市场。", audience=view)
        self._start_background_task(
            self._run_strategy_job,
            job_id,
            markets,
            symbols_by_market,
            execution_mode,
            runtime_mode,
            cash,
            detail_limit,
            history_limit,
            beta_window,
            top_n,
            as_of_date,
            forward_days,
            broker_name,
            route_orders,
            broker_account_id,
            selected_strategy_ids,
        )
        return self._redirect(self._view_url(view))

    def handle_local_paper_reset(self, body: Dict[str, List[str]]) -> WebResponse:
        view = self._requested_view(body, "paper")
        account_id = body.get("account_id", [""])[0].strip()
        if not account_id:
            self.state.push_flash("模拟盘重置失败：缺少账户 ID。", audience=view)
            return self._redirect(self._view_url(view))
        removed = LocalPaperLedger().reset_account(account_id)
        if removed:
            if self.state.last_local_paper_account and self.state.last_local_paper_account.get("account_id") == account_id:
                self.state.last_local_paper_account = None
            self.state.push_flash(f"模拟盘账户 {account_id} 已重置。", audience=view)
            self._append_task_log(
                category="paper",
                action="reset_account",
                status="SUCCESS",
                detail=f"重置模拟盘账户 {account_id}",
                metadata={"account_id": account_id},
            )
        else:
            self.state.push_flash(f"没有找到模拟盘账户 {account_id}。", audience=view)
            self._append_task_log(
                category="paper",
                action="reset_account",
                status="MISS",
                detail=f"没有找到模拟盘账户 {account_id}",
                metadata={"account_id": account_id},
            )
        return self._redirect(self._view_url(view))

    def handle_strategy_state_current(self, body: Dict[str, List[str]]) -> WebResponse:
        market_raw = body.get("market", [""])[0].strip().upper()
        preset_id = body.get("preset_id", [""])[0].strip()
        paper_account_id = body.get("paper_account_id", [""])[0].strip()
        paper_start_date = body.get("paper_start_date", [""])[0].strip()
        paper_end_date = body.get("paper_end_date", [""])[0].strip()
        subview = body.get("subview", ["main"])[0].strip().lower() or "main"
        try:
            market = Market(market_raw)
            lookup_strategy_preset(market, preset_id)
        except Exception as exc:
            self.state.push_flash(f"设为当前执行策略失败：{exc}", audience="paper")
            return self._redirect(
                self._view_url(
                    "paper",
                    query={
                        "paper_account_id": paper_account_id,
                        "paper_start_date": paper_start_date,
                        "paper_end_date": paper_end_date,
                        "subview": subview,
                    },
                )
            )
        try:
            self._strategy_state_store().set_current_execution_preset(market, preset_id)
        except Exception as exc:
            self.state.push_flash(f"设为当前执行策略失败：{exc}", audience="paper")
            return self._redirect(
                self._view_url(
                    "paper",
                    query={
                        "paper_account_id": paper_account_id,
                        "paper_start_date": paper_start_date,
                        "paper_end_date": paper_end_date,
                        "subview": subview,
                    },
                )
            )
        self.state.push_flash(f"已设为当前执行策略：{market.value} / {preset_id}。", audience="paper")
        return self._redirect(
            self._view_url(
                "paper",
                query={
                    "paper_account_id": paper_account_id,
                    "paper_start_date": paper_start_date,
                    "paper_end_date": paper_end_date,
                    "subview": subview,
                },
            )
        )

    def handle_factor_backtest(self, body: Dict[str, List[str]]) -> WebResponse:
        config = self._load_project_config()
        defaults = config["factor_defaults"]
        view = self._requested_view(body, "workbench")
        try:
            market = Market(body.get("factor_market", [str(defaults["factor_market"])])[0])
            selected_factors = [item for item in body.get("factor", []) if item]
            if not selected_factors:
                fallback_payload = body.get("factor_selection_payload", [""])[0].strip()
                if fallback_payload:
                    selected_factors = [item.strip() for item in fallback_payload.split(",") if item.strip()]
            if not selected_factors:
                selected_factors = self._infer_selected_factors_from_body(market, body)
            if not selected_factors:
                raise ValueError("请至少选择 1 个因子后再运行策略实验。")
            start_date = self._parse_required_date_field(body.get("factor_start_date", [str(defaults["factor_start_date"])])[0], "Start Date / 开始日期")
            end_date = self._parse_required_date_field(body.get("factor_end_date", [str(defaults["factor_end_date"])])[0], "End Date / 结束日期")
            if start_date > end_date:
                raise ValueError("开始日期不能晚于结束日期。")
            holding_sessions = self._parse_int_field(body.get("factor_holding_sessions", [str(defaults["factor_holding_sessions"])])[0], "Holding Sessions / 持有周期", minimum=1)
            detail_limit = self._parse_int_field(body.get("factor_detail_limit", [str(defaults["factor_detail_limit"])])[0], "Factor Detail Limit / 细节样本", minimum=1)
            history_limit = self._parse_int_field(body.get("factor_history_limit", [str(defaults["factor_history_limit"])])[0], "Factor History Limit / 历史窗口", minimum=1)
            top_n = self._parse_int_field(body.get("factor_top_n", [str(defaults["factor_top_n"])])[0], "Factor Top N / 组合数量", minimum=1)
            initial_cash = self._parse_decimal_field(body.get("factor_initial_cash", [str(defaults["factor_initial_cash"])])[0], "Initial Cash / 回测资金", minimum=Decimal("0.0001"))
            turnover_cap = self._parse_decimal_field(body.get("factor_turnover_cap", [str(defaults["factor_turnover_cap"])])[0], "Turnover Cap / 换手上限", minimum=Decimal("0"))
            rebalance_buffer = self._parse_decimal_field(body.get("factor_rebalance_buffer", [str(defaults["factor_rebalance_buffer"])])[0], "Rebalance Buffer / 调仓缓冲", minimum=Decimal("0"))
            factor_tilts = {
                factor_name: self._parse_decimal_field(
                    body.get(f"factor_tilt_{factor_name}", ["1.0"])[0] or "1.0",
                    f"{self._factor_label(factor_name)} Tilt",
                    minimum=Decimal("0"),
                )
                for factor_name in FACTOR_CATALOG
            }
        except (InvalidOperation, ValueError) as exc:
            self.state.push_flash(f"策略实验参数错误：{exc}", audience=view)
            return self._redirect(self._view_url(view))
        reservation = self._ops_store().begin_job(
            "factor_backtest",
            metadata={"market": market.value, "factors": selected_factors},
        )
        if not reservation.get("accepted"):
            active_job = reservation.get("active_job", {})
            self.state.push_flash(f"因子回测被拦截：当前有任务 {active_job.get('kind', 'UNKNOWN')} 在运行。", audience="ops")
            self._append_task_log(
                category="research",
                action="factor_backtest",
                status="BLOCKED",
                detail="因子回测被运行守护拦截",
                metadata={"active_job": active_job.get("kind", "UNKNOWN")},
            )
            return self._redirect("/project/ops")
        job_id = str(reservation["job"]["job_id"])
        self._ops_store().update_active_job(
            job_id,
            progress_pct=5,
            stage="PREPARING",
            detail="正在准备因子回测窗口与样本。",
            metadata={"market": market.value, "selected_factors": selected_factors},
        )
        self._append_task_log(
            category="research",
            action="factor_backtest",
            status="STARTED",
            detail=f"已提交 {market.value} 因子回测任务",
            metadata={"market": market.value, "factors": ",".join(selected_factors)},
        )
        self.state.push_flash(f"{market.value} 因子回测任务已提交，正在后台运行。", audience=view)
        self._start_background_task(
            self._run_factor_backtest_job,
            job_id,
            market,
            selected_factors,
            start_date,
            end_date,
            holding_sessions,
            detail_limit,
            history_limit,
            top_n,
            initial_cash,
            turnover_cap,
            rebalance_buffer,
            factor_tilts,
        )
        return self._redirect(self._view_url(view))

    def handle_chat(self, body: Dict[str, List[str]]) -> WebResponse:
        message = body.get("message", [""])[0].strip()
        if message:
            assistant_message = f"本地回显：我收到了你的消息「{message}」。这里是交互占位，后面可以接真实 LLM。"
            self.state.push_chat(message, assistant_message)
            self.state.push_flash("已追加一条本地聊天记录。", audience="overview")
            self._append_task_log(
                category="collab",
                action="chat_echo",
                status="SUCCESS",
                detail="追加了一条本地聊天记录",
                metadata={"message": message[:48]},
            )
        return self._redirect("/")

    def handle_project_config(self, body: Dict[str, List[str]]) -> WebResponse:
        current = self._load_project_config()
        try:
            updated = {
                "run_defaults": {
                    "market": self._normalize_choice(body.get("market", [str(current["run_defaults"]["market"])])[0], {"ALL", "CN", "US"}, str(current["run_defaults"]["market"])),
                    "runtime_mode": self._normalize_choice(body.get("runtime_mode", [str(current["run_defaults"]["runtime_mode"])])[0], {item.value for item in RuntimeMode}, str(current["run_defaults"]["runtime_mode"])),
                    "execution_mode": self._normalize_choice(body.get("execution_mode", [str(current["run_defaults"]["execution_mode"])])[0], {item.value for item in ExecutionMode}, str(current["run_defaults"]["execution_mode"])),
                    "broker": self._normalize_choice(body.get("broker", [str(current["run_defaults"]["broker"])])[0], {"NONE", "LOCAL_PAPER"}, str(current["run_defaults"]["broker"])),
                    "cash": self._stringify_decimal(self._parse_decimal_field(body.get("cash", [str(current["run_defaults"]["cash"])])[0], "Cash / 初始资金", minimum=Decimal("0.0001"))),
                    "broker_account_id": body.get("broker_account_id", [str(current["run_defaults"]["broker_account_id"])])[0].strip(),
                    "top_n": str(self._parse_int_field(body.get("top_n", [str(current["run_defaults"]["top_n"])])[0], "Top N / 选股数", minimum=1)),
                    "detail_limit": str(self._parse_int_field(body.get("detail_limit", [str(current["run_defaults"]["detail_limit"])])[0], "Detail Limit / 细节样本", minimum=1)),
                    "history_limit": str(self._parse_int_field(body.get("history_limit", [str(current["run_defaults"]["history_limit"])])[0], "History Limit / 历史窗口", minimum=1)),
                    "beta_window": str(self._parse_int_field(body.get("beta_window", [str(current["run_defaults"]["beta_window"])])[0], "Beta Window / Beta 窗口", minimum=1)),
                    "forward_days": str(self._parse_int_field(body.get("forward_days", [str(current["run_defaults"]["forward_days"])])[0], "Forward Days / 前瞻天数", minimum=0)),
                    "as_of_date": self._stringify_optional_date(self._parse_optional_date_field(body.get("as_of_date", [str(current["run_defaults"]["as_of_date"])])[0], "As Of Date / 历史日期")),
                    "symbols_cn": body.get("symbols_cn", [str(current["run_defaults"]["symbols_cn"])])[0].strip(),
                    "symbols_us": body.get("symbols_us", [str(current["run_defaults"]["symbols_us"])])[0].strip(),
                    "route_orders": body.get("route_orders", [""])[0] in {"on", "1", "true", "TRUE"},
                },
                "factor_defaults": {
                    "factor_market": self._normalize_choice(body.get("factor_market", [str(current["factor_defaults"]["factor_market"])])[0], {"CN", "US"}, str(current["factor_defaults"]["factor_market"])),
                    "factor_start_date": self._stringify_date(self._parse_required_date_field(body.get("factor_start_date", [str(current["factor_defaults"]["factor_start_date"])])[0], "Factor Start Date / 开始日期")),
                    "factor_end_date": self._stringify_date(self._parse_required_date_field(body.get("factor_end_date", [str(current["factor_defaults"]["factor_end_date"])])[0], "Factor End Date / 结束日期")),
                    "factor_holding_sessions": str(self._parse_int_field(body.get("factor_holding_sessions", [str(current["factor_defaults"]["factor_holding_sessions"])])[0], "Holding Sessions / 持有周期", minimum=1)),
                    "factor_top_n": str(self._parse_int_field(body.get("factor_top_n", [str(current["factor_defaults"]["factor_top_n"])])[0], "Factor Top N / 组合数量", minimum=1)),
                    "factor_detail_limit": str(self._parse_int_field(body.get("factor_detail_limit", [str(current["factor_defaults"]["factor_detail_limit"])])[0], "Factor Detail Limit / 细节样本", minimum=1)),
                    "factor_history_limit": str(self._parse_int_field(body.get("factor_history_limit", [str(current["factor_defaults"]["factor_history_limit"])])[0], "Factor History Limit / 历史窗口", minimum=1)),
                    "factor_initial_cash": self._stringify_decimal(self._parse_decimal_field(body.get("factor_initial_cash", [str(current["factor_defaults"]["factor_initial_cash"])])[0], "Initial Cash / 回测资金", minimum=Decimal("0.0001"))),
                    "factor_turnover_cap": self._stringify_decimal(self._parse_decimal_field(body.get("factor_turnover_cap", [str(current["factor_defaults"]["factor_turnover_cap"])])[0], "Turnover Cap / 换手上限", minimum=Decimal("0"))),
                    "factor_rebalance_buffer": self._stringify_decimal(self._parse_decimal_field(body.get("factor_rebalance_buffer", [str(current["factor_defaults"]["factor_rebalance_buffer"])])[0], "Rebalance Buffer / 调仓缓冲", minimum=Decimal("0"))),
                },
                "ui_defaults": {
                    "paper_account_id": body.get("paper_account_id", [str(current["ui_defaults"]["paper_account_id"])])[0].strip(),
                    "paper_start_date": self._stringify_optional_date(self._parse_optional_date_field(body.get("paper_start_date", [str(current["ui_defaults"]["paper_start_date"])])[0], "Paper Start Date / 默认开始日期")),
                    "paper_end_date": self._stringify_optional_date(self._parse_optional_date_field(body.get("paper_end_date", [str(current["ui_defaults"]["paper_end_date"])])[0], "Paper End Date / 默认结束日期")),
                    "paper_recent_trade_limit": str(self._parse_int_field(body.get("paper_recent_trade_limit", [str(current["ui_defaults"]["paper_recent_trade_limit"])])[0], "Paper Recent Trades / 流水条数", minimum=1)),
                },
            }
            if updated["factor_defaults"]["factor_start_date"] > updated["factor_defaults"]["factor_end_date"]:
                raise ValueError("因子开始日期不能晚于结束日期。")
            paper_start = updated["ui_defaults"]["paper_start_date"]
            paper_end = updated["ui_defaults"]["paper_end_date"]
            if paper_start and paper_end and paper_start > paper_end:
                raise ValueError("模拟盘默认开始日期不能晚于结束日期。")
        except (InvalidOperation, ValueError) as exc:
            self.state.push_flash(f"项目配置保存失败：{exc}", audience="config")
            return self._redirect("/project/config")
        self._save_project_config(updated)
        self.state.push_flash("项目配置已保存。", audience="config")
        self._append_task_log(
            category="project",
            action="update_config",
            status="SUCCESS",
            detail="更新了项目默认配置",
            metadata={
                "market": updated["run_defaults"]["market"],
                "broker": updated["run_defaults"]["broker"],
                "paper_account_id": updated["ui_defaults"]["paper_account_id"],
            },
        )
        return self._redirect("/project/config")

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
        return WebResponse(
            status=HTTPStatus.OK,
            content_type=self._guess_content_type(file_path),
            body=file_path.read_bytes(),
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    def _render_selected_artifact(self, artifact: Optional[ArtifactEntry]) -> str:
        if artifact is None:
            return """
            <section class="panel panel--empty">
              <h2>当前没有选中的 Artifact 工件</h2>
              <p>先从归档模块选一份结果，或者直接运行一次策略。</p>
            </section>
            """

        normalized_summary = artifact.summary.get("normalized_summary", {})
        if isinstance(normalized_summary, dict) and normalized_summary:
            metrics = artifact.summary.get("metrics", {})
            if not isinstance(metrics, dict):
                metrics = {}
            artifact_links = artifact.summary.get("artifacts", {})
            if not isinstance(artifact_links, dict):
                artifact_links = {}
            metric_tiles = "".join(
                self._summary_tile(str(key).replace("_", " ").title(), value, "工件里提取出的关键指标")
                for key, value in list(metrics.items())[:6]
            ) or self._summary_tile("Metrics / 指标", "暂无", "当前工件没有额外结构化指标")
            artifact_link_html = "".join(
                f'<a class="button button--ghost" href="/artifact-file?path={quote(self._artifact_query_path(str(path)))}" target="_blank" rel="noreferrer">{escape(str(name).upper())}</a>'
                for name, path in artifact_links.items()
                if str(path).strip()
            ) or '<span class="muted">暂无额外工件链接</span>'
            return f"""
            <section class="panel panel--selected">
              <div class="panel__header">
                <div>
                  <p class="eyebrow">Artifact Workspace</p>
                  <h2>{escape(artifact.display_name)}</h2>
                </div>
                <a class="button button--ghost" href="/artifact-file?path={quote(artifact.relative_path)}" target="_blank" rel="noreferrer">打开 JSON 工件</a>
              </div>
              <div class="panel__header">
                <div>
                  <p class="eyebrow">Normalized Summary</p>
                  <h3>Normalized Summary / 统一摘要</h3>
                </div>
              </div>
              <div class="summary-grid">
                {self._summary_tile("Subject / 对象", normalized_summary.get("subject_name") or normalized_summary.get("subject_id") or "N/A", "统一结果视图中的主体名称")}
                {self._summary_tile("Decision / 结论", normalized_summary.get("decision", "N/A"), "统一的保留/复核/淘汰结论")}
                {self._summary_tile("Score / 评分", normalized_summary.get("score", "N/A"), "如果该结果带评分，这里显示统一分数")}
                {self._summary_tile("Return / 收益", normalized_summary.get("return", "N/A"), "统一收益口径")}
                {self._summary_tile("Excess Return / 超额收益", normalized_summary.get("excess_return", "N/A"), "统一超额收益口径")}
                {self._summary_tile("Max Drawdown / 最大回撤", normalized_summary.get("max_drawdown", "N/A"), "统一回撤口径")}
              </div>
              <div class="panel__split">
                <div>
                  <h3>Rationale / 依据</h3>
                  <p>{escape(str(normalized_summary.get("rationale", "暂无摘要说明")))}</p>
                </div>
                <div>
                  <h3>Metrics / 指标</h3>
                  <div class="summary-grid">{metric_tiles}</div>
                </div>
              </div>
              <div class="panel__split">
                <div>
                  <h3>Artifact Links / 工件链接</h3>
                  <div class="panel__actions panel__actions--inline">{artifact_link_html}</div>
                </div>
                <div>
                  <h3>Payload / 原始工件</h3>
                  <p class="muted">这份结果已经有统一摘要，页面优先展示标准字段；完整细节仍可通过 JSON 工件查看。</p>
                </div>
              </div>
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
              <p class="eyebrow">Artifact Workspace</p>
              <h2>{escape(artifact.display_name)}</h2>
            </div>
            <a class="button button--ghost" href="/artifact-file?path={quote(artifact.relative_path)}" target="_blank" rel="noreferrer">打开 JSON 工件</a>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Market / 市场", summary.get("market", "N/A"), "结果所属市场")}
            {self._summary_tile("Mode / 模式", summary.get("runtime_mode", "N/A"), "回测、模拟或实时语义")}
            {self._summary_tile("Return / 收益", summary.get("total_return", "N/A"), "当前工件记录的收益口径")}
            {self._summary_tile("Final NAV / 期末净值", summary.get("final_nav", "N/A"), "账户或组合最终净值")}
            {self._summary_tile("Buy Fills / 买入成交", summary.get("buy_fill_count", "0"), "成功买入的成交笔数")}
            {self._summary_tile("Sell Fills / 卖出成交", summary.get("sell_fill_count", "0"), "成功卖出的成交笔数")}
          </div>
          {chart_html}
          <div class="panel__split">
            <div>
              <h3>Final Positions / 期末持仓</h3>
              <ul class="position-list">{positions_html or '<li class="muted">暂无持仓</li>'}</ul>
            </div>
            <div>
              <h3>Daily Preview / 每日预览</h3>
              {daily_html}
            </div>
          </div>
        </section>
        """

    def _start_background_task(self, target: Any, *args: Any) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()

    def _run_strategy_job(
        self,
        job_id: str,
        markets: List[Market],
        symbols_by_market: Dict[str, List[str]],
        execution_mode: ExecutionMode,
        runtime_mode: RuntimeMode,
        cash: Decimal,
        detail_limit: int,
        history_limit: int,
        beta_window: int,
        top_n: int,
        as_of_date: Optional[date],
        forward_days: int,
        broker_name: Optional[str],
        route_orders: bool,
        broker_account_id: Optional[str],
        selected_strategy_ids: Dict[str, Optional[str]],
    ) -> None:
        try:
            run_results: List[Dict[str, Any]] = []
            total_markets = max(len(markets), 1)
            for index, market in enumerate(markets, start=1):
                symbols = list(symbols_by_market.get(market.value, []))
                start_progress = int(10 + ((index - 1) / total_markets) * 70)
                self._ops_store().update_active_job(
                    job_id,
                    progress_pct=start_progress,
                    stage="RUNNING_MARKET",
                    detail=f"正在运行 {market.value} 市场 ({index}/{total_markets})。",
                    metadata={
                        "current_market": market.value,
                        "total_markets": total_markets,
                        "completed_markets": index - 1,
                        "selected_symbols": symbols[:24],
                    },
                )
                run_result = run_market(
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
                        broker_name=broker_name,
                        route_orders=route_orders,
                        broker_account_id=broker_account_id,
                        selected_preset_id=selected_strategy_ids.get(market.value),
                    )
                history_offset = len(self.state.last_run_results) + len(run_results)
                run_result["run_instance_id"] = f"{job_id}:{index}:{market.value}:{history_offset}"
                run_results.append(run_result)
                end_progress = int(10 + (index / total_markets) * 70)
                self._ops_store().update_active_job(
                    job_id,
                    progress_pct=end_progress,
                    stage="MARKET_DONE",
                    detail=f"{market.value} 市场运行完成。",
                    metadata={
                        "current_market": market.value,
                        "total_markets": total_markets,
                        "completed_markets": index,
                    },
                )

            self._ops_store().update_active_job(
                job_id,
                progress_pct=95,
                stage="FINALIZING",
                detail="正在整理运行结果和写入工件。",
            )
            self.state.last_run_results = (self.state.last_run_results + run_results)[-MAX_RECENT_RUN_RESULTS:]
            paper_results = [result for result in run_results if result.get("paper_account")]
            if paper_results:
                self.state.last_local_paper_account = paper_results[-1]["paper_account"]
            if route_orders and paper_results:
                trade_count = sum(len(result.get("paper_trade_records", [])) for result in paper_results)
                self.state.push_flash(f"本地模拟盘已记账，新增 {trade_count} 条买卖记录。", audience="workbench")
            self.state.push_flash(f"已运行 {len(run_results)} 个市场的本地策略。", audience="workbench")
            self._append_task_log(
                category="runtime",
                action="strategy_run",
                status="SUCCESS",
                detail=f"运行 {len(run_results)} 个市场，execution={execution_mode.value}，runtime={runtime_mode.value}",
                metadata={
                    "markets": ",".join(market.value for market in markets),
                    "broker": broker_name or "NONE",
                    "route_orders": route_orders,
                    "account_id": broker_account_id or "",
                },
            )
            self._ops_store().finish_job(
                job_id,
                "SUCCESS",
                detail=f"已完成 {len(run_results)} 个市场运行",
                metadata={"market_count": len(run_results), "trade_count": sum(len(result.get("paper_trade_records", [])) for result in paper_results)},
            )
        except Exception as exc:
            self._ops_store().finish_job(job_id, "FAILED", str(exc))
            self.state.push_flash(f"策略运行失败：{exc}", audience="workbench")
            self._append_task_log(
                category="runtime",
                action="strategy_run",
                status="FAILED",
                detail=f"策略运行失败：{exc}",
                metadata={"markets": ",".join(market.value for market in markets)},
            )

    def _run_factor_backtest_job(
        self,
        job_id: str,
        market: Market,
        selected_factors: List[str],
        start_date: date,
        end_date: date,
        holding_sessions: int,
        detail_limit: int,
        history_limit: int,
        top_n: int,
        initial_cash: Decimal,
        turnover_cap: Decimal,
        rebalance_buffer: Decimal,
        factor_tilts: Dict[str, Decimal],
    ) -> None:
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
                initial_cash=initial_cash,
                turnover_cap=turnover_cap,
                rebalance_buffer=rebalance_buffer,
                factor_tilts=factor_tilts,
                progress_callback=lambda progress_pct, stage, detail, metadata=None: self._ops_store().update_active_job(
                    job_id,
                    progress_pct=progress_pct,
                    stage=stage,
                    detail=detail,
                    metadata=metadata,
                ),
            )
            self._ops_store().update_active_job(
                job_id,
                progress_pct=95,
                stage="FINALIZING",
                detail="正在汇总因子回测结果。",
            )
            self.state.last_factor_backtest_result = result
            factor_names = "、".join(self._factor_label(factor_name) for factor_name in result["summary"]["selected_factors"])
            decision = result.get("attribution", {}).get("scorecard", {}).get("decision", "REVIEW")
            self.state.push_flash(f"{market.value} 策略实验已完成：{factor_names} | 结论 {decision}", audience="workbench")
            self._append_task_log(
                category="research",
                action="factor_backtest",
                status="SUCCESS",
                detail=f"{market.value} 策略实验完成：{factor_names}",
                metadata={"market": market.value, "factors": ",".join(result["summary"]["selected_factors"])},
            )
            self._ops_store().finish_job(
                job_id,
                "SUCCESS",
                detail=f"{market.value} 策略实验完成",
                metadata={"observations": result["summary"].get("observations", 0)},
            )
        except Exception as exc:
            self._ops_store().finish_job(job_id, "FAILED", str(exc))
            self.state.push_flash(f"因子回测失败：{exc}", audience="workbench")
            self._append_task_log(
                category="research",
                action="factor_backtest",
                status="FAILED",
                detail=f"因子回测失败：{exc}",
                metadata={"market": market.value},
            )

    def _render_factor_backtest_artifact(self, artifact: ArtifactEntry, summary: Dict[str, Any]) -> str:
        return self._render_strategy_lab_workspace(
            artifact.summary,
            title=artifact.display_name,
            eyebrow="Artifact Workspace",
            artifact_href=f"/artifact-file?path={quote(artifact.relative_path)}",
        )

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
            top_names = "、".join(
                str(item.get("name", item.get("instrument_id", "")))
                for item in result.get("recommended_stocks", [])[:3]
            ) or "暂无推荐"
            cards.append(
                f"""
                <article class="result-card">
                  <p class="eyebrow">{escape(str(result.get('market', '')))} / {escape(str(result.get('effective_runtime_mode', result.get('runtime_mode', ''))))}</p>
                  <h3>{escape(str(result.get('strategy_id', 'N/A')))}</h3>
                  <p>Trade Date / 交易日: {escape(str(result.get('trade_date', 'N/A')))}</p>
                  <p>Review / 审核: {escape(str(result.get('review', {}).get('verdict', 'N/A')))} | Trades / 成交 {len(result.get('paper_trade_records', []))}</p>
                  <p>{escape(top_names)}</p>
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
              <h2>Factor Backtest / 因子回测结果</h2>
              <p>先在下方选择因子、调整权重倍率，再运行一轮实验。这里会显示最近一次收益分析、回测和归因。</p>
            </section>
            """
        return self._render_strategy_lab_workspace(
            self.state.last_factor_backtest_result,
            title="Factor Backtest / 因子回测结果",
            eyebrow="Factor Backtest",
            artifact_href=f"/artifact-file?path={quote(self._artifact_query_path(self.state.last_factor_backtest_result['artifacts']['json']))}",
        )

    def _render_factor_backtest_form(self, view: str = "overview") -> str:
        defaults = self._load_project_config()["factor_defaults"]
        baseline_weights = self._baseline_alpha_weights(Market(str(defaults["factor_market"])))
        default_selected_factors = []
        factor_cards = []
        for factor_name, meta in FACTOR_CATALOG.items():
            baseline_weight = baseline_weights.get(factor_name, Decimal("0"))
            checked_attr = " checked" if baseline_weight != 0 else ""
            if baseline_weight != 0:
                default_selected_factors.append(factor_name)
            factor_cards.append(
                f"""
                <label class="factor-chip">
                  <input type="checkbox" name="factor" value="{escape(factor_name)}"{checked_attr} />
                  <div class="factor-chip__title-row">
                    <span class="factor-chip__title">{escape(meta['label'])}</span>
                    <span class="factor-chip__meta">{escape(factor_name)}</span>
                  </div>
                  <span class="factor-chip__desc">{escape(meta['description'])}</span>
                  <span class="factor-chip__baseline">Baseline / 基线权重: {escape(str(baseline_weight.quantize(Decimal('0.0001'))))}</span>
                  <span class="factor-chip__tilt-label">Tilt / 权重倍率</span>
                  <input class="factor-chip__tilt" type="number" step="0.1" min="0" name="factor_tilt_{escape(factor_name)}" value="1.0" />
                </label>
                """
            )
        return f"""
        <section class="panel panel--form">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Factor Backtest</p>
              <h2>Factor Backtest / 因子回测</h2>
            </div>
          </div>
          <form class="stack" method="post" action="/factor-backtest" id="factor-backtest-form">
            <input type="hidden" name="view" value="{escape(view)}" />
            <div class="grid-form">
              <label>Market / 市场<span class="field-note">选择本次策略实验的市场</span><select name="factor_market"><option value="CN"{' selected' if defaults['factor_market'] == 'CN' else ''}>CN</option><option value="US"{' selected' if defaults['factor_market'] == 'US' else ''}>US</option></select></label>
              <label>Start Date / 开始日期<span class="field-note">滚动回测起点</span><input name="factor_start_date" value="{escape(str(defaults['factor_start_date']))}" /></label>
              <label>End Date / 结束日期<span class="field-note">滚动回测终点</span><input name="factor_end_date" value="{escape(str(defaults['factor_end_date']))}" /></label>
              <label>Holding Sessions / 持有周期<span class="field-note">信号持有交易日数</span><input name="factor_holding_sessions" value="{escape(str(defaults['factor_holding_sessions']))}" /></label>
              <label>Top N / 组合数量<span class="field-note">每轮保留股票数</span><input name="factor_top_n" value="{escape(str(defaults['factor_top_n']))}" /></label>
              <label>Detail Limit / 细节样本<span class="field-note">每轮抓取详细历史的股票数</span><input name="factor_detail_limit" value="{escape(str(defaults['factor_detail_limit']))}" /></label>
              <label>History Limit / 历史窗口<span class="field-note">研究、beta 和趋势使用的 bars</span><input name="factor_history_limit" value="{escape(str(defaults['factor_history_limit']))}" /></label>
              <label>Initial Cash / 回测资金<span class="field-note">组合滚动回测的初始资金</span><input name="factor_initial_cash" value="{escape(str(defaults['factor_initial_cash']))}" /></label>
              <label>Turnover Cap / 换手上限<span class="field-note">组合构建时允许的平均换手上限</span><input name="factor_turnover_cap" value="{escape(str(defaults['factor_turnover_cap']))}" /></label>
              <label>Rebalance Buffer / 调仓缓冲<span class="field-note">缓冲小幅漂移，减少过度交易</span><input name="factor_rebalance_buffer" value="{escape(str(defaults['factor_rebalance_buffer']))}" /></label>
            </div>
            <div class="research-lab__hint">
              <strong>使用说明</strong>
              <span>勾选因子决定是否启用，`Tilt / 权重倍率` 用来放大或削弱该因子的基线权重。系统会自动归一化成一套可运行的策略权重。</span>
            </div>
            <div class="research-lab__selection">
              <strong>当前已选因子</strong>
              <span data-factor-selection-status>正在统计...</span>
            </div>
            <div class="factor-grid">{''.join(factor_cards)}</div>
            <input type="hidden" name="factor_selection_payload" value="{escape(','.join(default_selected_factors))}" data-factor-selection-payload />
            <div class="research-lab__actions">
              <button class="button button--primary" type="submit">运行因子回测</button>
              <span class="field-note">本次会同时输出选股收益分析、组合滚动回测和归因结论。</span>
            </div>
          </form>
        </section>
        """

    def _render_recent_artifact_cards(self, selected_relative_path: Optional[str], view: str = "overview") -> str:
        artifacts = self._recent_artifacts(limit=12)
        cards = []
        for artifact in artifacts:
            active_class = " result-card--active" if artifact.relative_path == selected_relative_path else ""
            cards.append(
                f"""
                <a class="result-card{active_class}" href="{self._view_url(view, query={"artifact": artifact.relative_path})}">
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
              <p class="eyebrow">Artifact Archive</p>
              <h2>最近结果</h2>
            </div>
            <a class="button button--ghost" href="{self._view_url(view)}">刷新归档</a>
          </div>
          <div class="card-grid card-grid--tight">{''.join(cards)}</div>
        </section>
        """

    def _render_indexed_result_cards(self, view: str = "overview") -> str:
        records = self._recent_indexed_results(limit=8)
        if not records:
            return """
            <section class="panel panel--empty">
              <h2>Research Results / 研究结果中心</h2>
              <p>验证研究、策略套件和滚动回测接入结果索引后，这里会显示统一摘要卡片。</p>
            </section>
            """
        research_records = [row for row in records if str(row.get("artifact_kind")) != "local_paper_run"]
        runtime_records = [row for row in records if str(row.get("artifact_kind")) == "local_paper_run"]
        sections = []
        if research_records:
            sections.append(
                f"""
                <div class="panel__split">
                  <div>
                    <p class="eyebrow">Research Results</p>
                    <h3>Research Results / 研究结果中心</h3>
                  </div>
                </div>
                <div class="card-grid card-grid--tight">{self._render_indexed_result_card_grid(research_records, view=view)}</div>
                """
            )
        if runtime_records:
            sections.append(
                f"""
                <div class="panel__split">
                  <div>
                    <p class="eyebrow">Runtime Results</p>
                    <h3>Runtime Results / 运行结果</h3>
                  </div>
                </div>
                <div class="card-grid card-grid--tight">{self._render_indexed_result_card_grid(runtime_records, view=view)}</div>
                """
            )
        return f"""
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Indexed Results</p>
              <h2>Indexed Results / 索引结果中心</h2>
            </div>
          </div>
          {''.join(sections)}
        </section>
        """

    def _render_indexed_result_card_grid(self, records: Iterable[Dict[str, Any]], view: str = "overview") -> str:
        cards = []
        for row in records:
            summary = row.get("summary", {}) if isinstance(row.get("summary"), dict) else {}
            artifacts = row.get("artifacts", {}) if isinstance(row.get("artifacts"), dict) else {}
            json_path = str(artifacts.get("json", "") or "")
            href = self._view_url(view, query={"artifact": self._artifact_query_path(json_path)}) if json_path else "#"
            cards.append(
                f"""
                <a class="result-card" href="{href}">
                  <p class="eyebrow">{escape(str(row.get('artifact_kind', 'result')))} / {escape(str(row.get('market', 'N/A')))}</p>
                  <h3>{escape(str(summary.get('subject_name') or summary.get('subject_id') or row.get('result_id', 'N/A')))}</h3>
                  <p>Decision / 结论: {escape(str(summary.get('decision', 'N/A')))} | Score / 评分 {escape(str(summary.get('score', 'N/A')))}</p>
                  <p>Return / 收益: {escape(str(summary.get('return', 'N/A')))} | Excess / 超额: {escape(str(summary.get('excess_return', 'N/A')))}</p>
                </a>
                """
            )
        return "".join(cards)

    def _render_local_paper_panel(self, query: Dict[str, List[str]], view: str = "paper", subview: str = "main") -> str:
        ui_defaults = self._load_project_config()["ui_defaults"]
        filter_account_id = query.get("paper_account_id", [str(ui_defaults["paper_account_id"])])[0].strip() or None
        filter_start_date = query.get("paper_start_date", [str(ui_defaults["paper_start_date"])])[0].strip() or None
        filter_end_date = query.get("paper_end_date", [str(ui_defaults["paper_end_date"])])[0].strip() or None
        recent_trade_limit = int(str(ui_defaults.get("paper_recent_trade_limit", "18")))
        ledger = LocalPaperLedger()
        if filter_account_id:
            overview = ledger.account_overview(filter_account_id, recent_trade_limit=recent_trade_limit, start_date=filter_start_date, end_date=filter_end_date)
        else:
            overview = self.state.last_local_paper_account or ledger.latest_account_overview(recent_trade_limit=recent_trade_limit, start_date=filter_start_date, end_date=filter_end_date)
        if overview is None:
            return """
            <section class="panel panel--empty">
              <h2>模拟盘账户</h2>
              <p>选择 `LOCAL_PAPER` 并勾选路由后，这里会显示账户资金、持仓和最近买卖流水。</p>
            </section>
            """
        overview = self._enrich_local_paper_overview(overview)
        account_options = "".join(
            f"<option value=\"{escape(account_id)}\"{' selected' if account_id == overview.get('account_id') else ''}>{escape(account_id)}</option>"
            for account_id in ledger.list_accounts()
        )
        nav_chart_html = self._render_local_paper_nav_chart(overview.get("nav_history", []))
        today_summary = overview.get("today_summary", {})
        total_unrealized = overview.get("total_unrealized_pnl", "0")
        trade_rows = []
        for trade in overview.get("recent_trades", [])[:10]:
            side_class = "tag tag--buy" if trade.get("side") == "BUY" else "tag tag--sell"
            trade_rows.append(
                f"""
                <tr>
                  <td>{escape(str(trade.get('trade_date', '')))}</td>
                  <td><span class="{side_class}">{escape(str(trade.get('side', '')))}</span></td>
                  <td>{escape(str(trade.get('instrument_id', '')))}</td>
                  <td>{escape(str(trade.get('filled_qty', '')))}</td>
                  <td>{escape(str(trade.get('realized_price') or trade.get('estimated_price') or ''))}</td>
                  <td>{escape(str(trade.get('cash_delta', '')))}</td>
                </tr>
                """
            )
        trade_table = "".join(trade_rows) if trade_rows else "<tr><td colspan='6'>暂无成交记录</td></tr>"
        latest_paper_run_html = self._render_paper_execution_timeline(overview)
        current_strategy_html = self._render_current_strategy_panel(overview)
        if subview == "holdings":
            body_html = self._render_paper_holdings_page(overview)
        elif subview == "trades":
            body_html = self._render_paper_trades_page(view, overview, account_options, trade_table)
        else:
            body_html = self._render_paper_main_page(
                overview=overview,
                total_unrealized=total_unrealized,
                today_summary=today_summary,
                current_strategy_html=current_strategy_html,
                latest_paper_run_html=latest_paper_run_html,
                nav_chart_html=nav_chart_html,
            )
        return f"""
        <section class="paper-page paper-page--{escape(subview)}">
          {body_html}
        </section>
        """

    def _render_paper_main_page(
        self,
        *,
        overview: Dict[str, Any],
        total_unrealized: str,
        today_summary: Dict[str, Any],
        current_strategy_html: str,
        latest_paper_run_html: str,
        nav_chart_html: str,
    ) -> str:
        account_status = "Invested / 持仓中" if int(str(overview.get("position_count", 0) or 0)) > 0 else "Flat / 空仓"
        return f"""
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Local Paper Workspace</p>
              <h2>Account Conclusion / 账户结论</h2>
              <p class="muted">这个页面只聚焦当前账户的结论、状态和执行工作区，不再混入项目总览。</p>
            </div>
            <form method="post" action="/local-paper/reset">
              <input type="hidden" name="view" value="paper" />
              <input type="hidden" name="account_id" value="{escape(str(overview.get('account_id', '')))}" />
              <button class="button button--ghost" type="submit">Reset Account / 重置当前账户</button>
            </form>
          </div>
          <div class="paper-identity">
            <div class="paper-identity__intro">
              <p class="eyebrow">Account Status</p>
              <h3>{escape(str(overview.get("account_id", "N/A")))}</h3>
              <p class="muted">市场 {escape(str(overview.get("market", "N/A")))} | 账户状态 {escape(account_status)}</p>
            </div>
            <div class="summary-grid">
              {self._summary_tile("Latest NAV / 最新净值", overview.get("latest_nav", "0"), "账户当前最新估算净值")}
              {self._summary_tile("Cumulative Return / 累计收益", overview.get("cumulative_return", "0"), "相对起始资金累计收益")}
              {self._summary_tile("Positions / 持仓数", overview.get("position_count", "0"), "当前持仓标的数量")}
              {self._summary_tile("Trades / 总成交", overview.get("trade_count", "0"), "累计成交记录数")}
            </div>
          </div>
          {current_strategy_html}
          {latest_paper_run_html}
          {nav_chart_html}
          <div class="paper-section">
            <div class="panel__header panel__header--section">
              <div>
                <p class="eyebrow">Account Snapshot</p>
                <h3>Account Snapshot / 账户摘要</h3>
              </div>
            </div>
            <div class="summary-grid">
              {self._summary_tile("Account / 账户", overview.get("account_id", "N/A"), "当前模拟盘账户 ID")}
              {self._summary_tile("Market / 市场", overview.get("market", "N/A"), "账户所属市场")}
              {self._summary_tile("Cash / 现金", overview.get("cash", "0"), "可用现金余额")}
              {self._summary_tile("Buying Power / 可买额度", overview.get("buying_power", "0"), "当前理论可用购买力")}
              {self._summary_tile("Filtered Trades / 筛选成交", overview.get("filtered_trade_count", "0"), "当前筛选窗口内的成交数")}
              {self._summary_tile("Unrealized PnL / 未实现盈亏", total_unrealized, "当前持仓按最近价格估算的浮盈浮亏")}
              {self._summary_tile("Mark Source / 估值来源", overview.get("mark_source", "N/A"), "实时行情失败时会退回最近成交价")}
            </div>
          </div>
        </section>
        """

    def _render_paper_holdings_page(self, overview: Dict[str, Any]) -> str:
        return f"""
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Holdings</p>
              <h2>Holdings / 持仓</h2>
            </div>
          </div>
          <div class="paper-section">
            <div class="panel__header panel__header--section">
              <div>
                <p class="eyebrow">Holdings Detail</p>
                <h3>Holdings Detail / 持仓详情</h3>
              </div>
            </div>
            {self._render_position_detail_table(overview.get("position_rows", []))}
          </div>
          <div class="paper-section">
            <div class="panel__header panel__header--section">
              <div>
                <p class="eyebrow">Sector Exposure</p>
                <h3>Sector Exposure / 行业暴露</h3>
              </div>
            </div>
            {self._render_sector_exposure_table(overview.get("sector_exposure_rows", []))}
          </div>
        </section>
        """

    def _render_paper_trades_page(self, view: str, overview: Dict[str, Any], account_options: str, trade_table: str) -> str:
        return f"""
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Trades</p>
              <h2>Trades / 交易</h2>
            </div>
          </div>
          <div class="paper-section">
            <div class="panel__header panel__header--section">
              <div>
                <p class="eyebrow">Account Workspace</p>
                <h3>Account Workspace / 账户工作区</h3>
              </div>
            </div>
            <form class="grid-form grid-form--paper-filter" method="get" action="{self._view_url(view)}">
              <input type="hidden" name="subview" value="trades" />
              <label>Account / 账户<span class="field-note">选择要查看的模拟盘</span><select name="paper_account_id">{account_options}</select></label>
              <label>Start Date / 开始日期<span class="field-note">流水过滤起点</span><input name="paper_start_date" value="{escape(str(overview.get('filter_start_date') or ''))}" placeholder="2026-04-01" /></label>
              <label>End Date / 结束日期<span class="field-note">流水过滤终点</span><input name="paper_end_date" value="{escape(str(overview.get('filter_end_date') or ''))}" placeholder="2026-04-30" /></label>
              <div class="grid-form__actions">
                <button class="button button--ghost" type="submit">筛选流水</button>
              </div>
            </form>
            <div class="paper-section">
              <div class="panel__header panel__header--section">
                <div>
                  <p class="eyebrow">Recent Trades</p>
                  <h3>Recent Trades / 最近成交</h3>
                </div>
              </div>
              <table class="data-table">
                <thead><tr><th>Date / 日期</th><th>Side / 方向</th><th>Instrument / 标的</th><th>Qty / 数量</th><th>Price / 价格</th><th>Cash / 现金变动</th></tr></thead>
                <tbody>{trade_table}</tbody>
              </table>
            </div>
          </div>
        </section>
        """

    def _render_paper_execution_timeline(self, overview: Dict[str, Any]) -> str:
        latest_paper_run = self._latest_paper_run_result(
            account_id=str(overview.get("account_id") or "").strip() or None,
            market=str(overview.get("market") or "").strip().upper() or None,
        )
        if not latest_paper_run:
            return """
            <section class="panel panel--empty">
              <h2>Execution Timeline / 执行时间线</h2>
              <p>最近还没有写入模拟盘的运行结果。</p>
            </section>
            """
        run_summary = latest_paper_run.get("paper_run_summary", {}) if isinstance(latest_paper_run.get("paper_run_summary"), dict) else {}
        run_paths = latest_paper_run.get("paper_paths", {}) if isinstance(latest_paper_run.get("paper_paths"), dict) else {}
        run_href = ""
        if run_paths.get("run_json"):
            run_href = f'<a class="button button--ghost" href="/artifact-file?path={quote(self._artifact_query_path(str(run_paths["run_json"])))}" target="_blank" rel="noreferrer">打开最近运行工件</a>'
        return f"""
        <section class="paper-section timeline-stack">
          <div class="panel__header panel__header--section">
            <div>
              <p class="eyebrow">Execution Timeline</p>
              <h3>Execution Timeline / 执行时间线</h3>
            </div>
          </div>
          <div class="panel__split panel__split--compact paper-workspace__context timeline-entry">
            <div class="timeline-entry__marker"></div>
            <div>
              <h3>Recent Run Context / 最近运行上下文</h3>
              <p class="muted">这里仅保留最近一次写入模拟盘的账户上下文，辅助理解当前状态，而不是替代结果页。</p>
              <div class="summary-grid">
                {self._summary_tile("Strategy / 策略", run_summary.get("strategy_id", "N/A"), "最近一次写入模拟盘的策略 ID")}
                {self._summary_tile("As Of / 记账时间", run_summary.get("as_of", "N/A"), "本次模拟盘记账对应的执行时间")}
                {self._summary_tile("Trades / 成交数", run_summary.get("trade_count", "0"), "本次运行新增的成交记录数")}
                {self._summary_tile("Positions / 持仓数", run_summary.get("position_count", "0"), "本次运行后的持仓数量")}
              </div>
              <div class="panel__actions panel__actions--inline">
                {run_href}
              </div>
            </div>
          </div>
          {self._render_local_paper_nav_chart(overview.get("nav_history", []))}
        </section>
        """

    def _render_current_strategy_panel(self, overview: Dict[str, Any]) -> str:
        market = str(overview.get("market", "US") or "US").upper()
        state = self._strategy_state_store().load_market_state(market)
        champion = state.get("champion_preset_id") or "N/A"
        challenger = state.get("challenger_preset_id") or "N/A"
        champion_preset_id = str(state.get("champion_preset_id") or "").strip()
        challenger_preset_id = str(state.get("challenger_preset_id") or "").strip()
        current_execution = state.get("current_execution_preset_id") or champion_preset_id or "N/A"
        action_forms = []
        if champion_preset_id and champion_preset_id != current_execution:
            action_forms.append(
                self._render_current_strategy_action_form(
                    market=market,
                    preset_id=champion_preset_id,
                    preset_label="Champion / 冠军策略",
                    overview=overview,
                )
            )
        if challenger_preset_id and challenger_preset_id != current_execution and challenger_preset_id != champion_preset_id:
            action_forms.append(
                self._render_current_strategy_action_form(
                    market=market,
                    preset_id=challenger_preset_id,
                    preset_label="Challenger / 挑战者策略",
                    overview=overview,
                )
            )
        actions_html = "".join(action_forms)
        return f"""
        <section class="paper-section paper-current-strategy">
          <div class="panel__header panel__header--section">
            <div>
              <p class="eyebrow">Current Strategy</p>
              <h3>Current Strategy / 当前策略</h3>
            </div>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Current Execution / 当前执行策略", current_execution, "当前正在执行的预设")}
            {self._summary_tile("Champion / 冠军策略", champion, "当前市场的 champion 预设")}
            {self._summary_tile("Challenger / 挑战者策略", challenger, "当前市场的 challenger 预设")}
            {self._summary_tile("Market / 市场", market, "当前策略状态所属市场")}
          </div>
          {f'<div class="panel__actions panel__actions--inline">{actions_html}</div>' if actions_html else ''}
        </section>
        """

    def _render_current_strategy_action_form(self, *, market: str, preset_id: str, preset_label: str, overview: Dict[str, Any]) -> str:
        paper_account_id = str(overview.get("account_id") or "").strip()
        paper_start_date = str(overview.get("filter_start_date") or "").strip()
        paper_end_date = str(overview.get("filter_end_date") or "").strip()
        return f"""
        <form method="post" action="/strategy-state/current" class="inline-form">
          <input type="hidden" name="view" value="paper" />
          <input type="hidden" name="subview" value="main" />
          <input type="hidden" name="market" value="{escape(market)}" />
          <input type="hidden" name="preset_id" value="{escape(preset_id)}" />
          <input type="hidden" name="paper_account_id" value="{escape(paper_account_id)}" />
          <input type="hidden" name="paper_start_date" value="{escape(paper_start_date)}" />
          <input type="hidden" name="paper_end_date" value="{escape(paper_end_date)}" />
          <div class="inline-form__copy">
            <strong>{escape(preset_label)}</strong>
            <span class="muted">{escape(preset_id)}</span>
          </div>
          <button class="button button--ghost" type="submit">设为当前执行策略</button>
        </form>
        """

    def _render_sector_exposure_table(self, rows: Iterable[Dict[str, Any]]) -> str:
        table_rows = []
        for row in list(rows)[:10]:
            table_rows.append(
                f"""
                <tr>
                  <td>{escape(str(row.get('sector', 'UNKNOWN')))}</td>
                  <td>{escape(str(row.get('weight_pct', '0')))}%</td>
                  <td>{escape(str(row.get('market_value', '0')))}</td>
                </tr>
                """
            )
        rows_html = "".join(table_rows) if table_rows else "<tr><td colspan='3'>当前没有行业暴露数据</td></tr>"
        return f"""
        <table class="data-table">
          <thead><tr><th>Sector / 行业</th><th>Weight / 权重</th><th>Market Value / 市值</th></tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        """

    def _render_local_paper_nav_chart(self, nav_history: Iterable[Dict[str, Any]]) -> str:
        points = list(nav_history)
        if len(points) < 2:
            return """
            <div class="chart-block chart-block--mini">
              <div class="chart-block__header">
                <h3>Estimated NAV / 估算净值</h3>
              </div>
              <div class="muted">至少需要两次记账后才会显示曲线。</div>
            </div>
            """
        values = [Decimal(str(item.get("nav", "0"))) for item in points]
        min_value = min(values)
        max_value = max(values)
        span = max(max_value - min_value, Decimal("1"))
        width = 640
        height = 140
        svg_points = []
        for index, value in enumerate(values):
            x = (width / max(len(values) - 1, 1)) * index
            normalized = (value - min_value) / span
            y = float(Decimal(height - 18) - (normalized * Decimal(height - 36))) + 9.0
            svg_points.append(f"{x:.2f},{y:.2f}")
        first_label = points[0].get("trade_date", "")
        last_label = points[-1].get("trade_date", "")
        return f"""
        <div class="chart-block chart-block--mini">
          <div class="chart-block__header">
            <h3>Estimated NAV / 估算净值</h3>
            <span class="muted">{escape(str(first_label))} -> {escape(str(last_label))}</span>
          </div>
          <svg class="sparkline" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="Estimated NAV chart">
            <polyline fill="none" stroke="url(#navGradient)" stroke-width="4" points="{' '.join(svg_points)}"></polyline>
            <defs>
              <linearGradient id="navGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#7dd3fc"></stop>
                <stop offset="100%" stop-color="#34d399"></stop>
              </linearGradient>
            </defs>
          </svg>
        </div>
        """

    def _render_position_detail_table(self, positions: Iterable[Dict[str, Any]]) -> str:
        rows = []
        for row in list(positions)[:10]:
            rows.append(
                f"""
                <tr>
                  <td>{escape(str(row.get('instrument_id', '')))}</td>
                  <td>{escape(str(row.get('sector', 'UNKNOWN')))}</td>
                  <td>{escape(str(row.get('qty', '0')))}</td>
                  <td>{escape(str(row.get('avg_cost', '0')))}</td>
                  <td>{escape(str(row.get('current_price', '0')))}</td>
                  <td>{escape(str(row.get('market_value', '0')))}</td>
                  <td>{escape(str(row.get('weight_pct', '0')))}%</td>
                  <td>{escape(str(row.get('unrealized_pnl', '0')))}</td>
                </tr>
                """
            )
        table_rows = "".join(rows) if rows else "<tr><td colspan='8'>暂无持仓明细</td></tr>"
        return f"""
        <table class="data-table">
          <thead><tr><th>Instrument / 标的</th><th>Sector / 行业</th><th>Qty / 数量</th><th>Cost / 成本</th><th>Mark / 现价</th><th>Value / 市值</th><th>Weight / 权重</th><th>PnL / 盈亏</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
        """

    def _enrich_local_paper_overview(self, overview: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(overview)
        positions = list(enriched.get("positions", []))
        filtered_trades = list(enriched.get("filtered_trades", []))
        latest_nav = Decimal(str(enriched.get("latest_nav", "0") or "0"))
        cash = Decimal(str(enriched.get("cash", "0") or "0"))
        price_seed: Dict[str, Decimal] = {}
        name_map: Dict[str, str] = {}
        for trade in reversed(filtered_trades):
            instrument_id = str(trade.get("instrument_id", ""))
            if not instrument_id:
                continue
            if instrument_id not in price_seed:
                price_raw = trade.get("realized_price") or trade.get("estimated_price") or trade.get("price")
                if price_raw not in (None, "", "None"):
                    price_seed[instrument_id] = Decimal(str(price_raw))
            if instrument_id not in name_map and trade.get("name"):
                name_map[instrument_id] = str(trade.get("name"))

        live_price_map: Dict[str, Decimal] = {}
        sector_map: Dict[str, str] = {}
        live_name_map: Dict[str, str] = {}
        mark_source = "ledger"
        live_error = None
        instrument_ids = [str(position.get("instrument_id", "")) for position in positions if position.get("instrument_id")]
        if instrument_ids:
            try:
                market = Market(str(enriched.get("market", "US")))
                symbols = [instrument_id.split(".", 1)[1] if "." in instrument_id else instrument_id for instrument_id in instrument_ids]
                snapshot = build_market_snapshot(
                    market,
                    symbols=symbols,
                    detail_limit=max(len(symbols), 8),
                    history_limit=90,
                )
                for instrument_id in instrument_ids:
                    instrument = snapshot.data_provider.get_instrument(instrument_id)
                    latest_bar = snapshot.data_provider.get_latest_bar(instrument_id, snapshot.as_of)
                    live_price_map[instrument_id] = latest_bar.close
                    sector_map[instrument_id] = str(
                        instrument.attributes.get("sector")
                        or instrument.attributes.get("industry")
                        or instrument.attributes.get("sector_name")
                        or "UNKNOWN"
                    )
                    live_name_map[instrument_id] = self._instrument_name_safe(instrument, instrument_id)
                if live_price_map:
                    mark_source = "live"
            except Exception as exc:
                live_error = str(exc)

        sector_market_value: Dict[str, Decimal] = {}
        position_rows: List[Dict[str, Any]] = []
        total_unrealized = Decimal("0")
        total_position_value = Decimal("0")
        max_weight = Decimal("0")
        for position in positions:
            instrument_id = str(position.get("instrument_id", ""))
            qty = Decimal(str(position.get("qty", "0") or "0"))
            avg_cost = Decimal(str(position.get("avg_cost", "0") or "0"))
            current_price = live_price_map.get(instrument_id, price_seed.get(instrument_id, avg_cost))
            market_value = (qty * current_price).quantize(Decimal("0.0001"))
            cost_basis = (qty * avg_cost).quantize(Decimal("0.0001"))
            unrealized = (market_value - cost_basis).quantize(Decimal("0.0001"))
            total_unrealized += unrealized
            total_position_value += market_value
            weight = Decimal("0")
            if latest_nav > 0:
                weight = (market_value / latest_nav).quantize(Decimal("0.0001"))
            max_weight = max(max_weight, weight)
            pnl_pct = Decimal("0")
            if cost_basis > 0:
                pnl_pct = ((unrealized / cost_basis) * Decimal("100")).quantize(Decimal("0.01"))
            sector = sector_map.get(instrument_id, "UNKNOWN")
            sector_market_value[sector] = sector_market_value.get(sector, Decimal("0")) + market_value
            position_rows.append(
                {
                    **position,
                    "name": live_name_map.get(instrument_id, name_map.get(instrument_id, instrument_id)),
                    "sector": sector,
                    "current_price": str(current_price.quantize(Decimal("0.0001"))),
                    "market_value": str(market_value),
                    "cost_basis": str(cost_basis),
                    "unrealized_pnl": str(unrealized),
                    "pnl_pct": str(pnl_pct),
                    "weight_pct": str((weight * Decimal("100")).quantize(Decimal("0.01"))),
                }
            )

        sector_rows = []
        for sector, market_value in sorted(sector_market_value.items(), key=lambda item: item[1], reverse=True):
            weight = Decimal("0")
            if latest_nav > 0:
                weight = (market_value / latest_nav).quantize(Decimal("0.0001"))
            sector_rows.append(
                {
                    "sector": sector,
                    "market_value": str(market_value.quantize(Decimal("0.0001"))),
                    "weight": str(weight),
                    "weight_pct": str((weight * Decimal("100")).quantize(Decimal("0.01"))),
                }
            )

        nav_values = [Decimal(str(item.get("nav", "0") or "0")) for item in enriched.get("nav_history", [])]
        peak_nav = max(nav_values) if nav_values else latest_nav
        drawdown = Decimal("0")
        if peak_nav > 0 and latest_nav > 0:
            drawdown = ((latest_nav / peak_nav) - Decimal("1")).quantize(Decimal("0.0001"))

        today_trade_date = ""
        if filtered_trades:
            today_trade_date = max(str(trade.get("trade_date", "")) for trade in filtered_trades)
        today_trades = [trade for trade in filtered_trades if str(trade.get("trade_date", "")) == today_trade_date] if today_trade_date else []
        gross_buy = sum((abs(Decimal(str(trade.get("cash_delta", "0") or "0"))) for trade in today_trades if trade.get("side") == "BUY"), Decimal("0"))
        gross_sell = sum((Decimal(str(trade.get("cash_delta", "0") or "0")) for trade in today_trades if trade.get("side") == "SELL"), Decimal("0"))
        net_cash_flow = (gross_sell - gross_buy).quantize(Decimal("0.0001"))
        today_summary = {
            "trade_date": today_trade_date or "N/A",
            "buy_count": len([trade for trade in today_trades if trade.get("side") == "BUY"]),
            "sell_count": len([trade for trade in today_trades if trade.get("side") == "SELL"]),
            "gross_buy_notional": str(gross_buy.quantize(Decimal("0.0001"))),
            "gross_sell_notional": str(gross_sell.quantize(Decimal("0.0001"))),
            "net_cash_flow": str(net_cash_flow),
        }

        risk_alerts: List[Dict[str, str]] = []
        cash_ratio = Decimal("0")
        if latest_nav > 0:
            cash_ratio = (cash / latest_nav).quantize(Decimal("0.0001"))
        if max_weight > Decimal("0.35"):
            dominant = max(position_rows, key=lambda item: Decimal(str(item.get("weight_pct", "0"))))
            risk_alerts.append(
                {
                    "level": "warn",
                    "title": "仓位集中 / Concentration",
                    "detail": f"{dominant['instrument_id']} 持仓占净值 {dominant['weight_pct']}%，超过 35% 提醒线。",
                }
            )
        if sector_rows and Decimal(str(sector_rows[0]["weight"])) > Decimal("0.45"):
            risk_alerts.append(
                {
                    "level": "warn",
                    "title": "行业集中 / Sector Exposure",
                    "detail": f"{sector_rows[0]['sector']} 暴露 {sector_rows[0]['weight_pct']}%，行业过于集中。",
                }
            )
        if cash_ratio < Decimal("0.05") and latest_nav > 0:
            risk_alerts.append(
                {
                    "level": "info",
                    "title": "现金偏低 / Low Cash",
                    "detail": f"当前现金占净值 {str((cash_ratio * Decimal('100')).quantize(Decimal('0.01')))}%，后续调仓余量较小。",
                }
            )
        if drawdown <= Decimal("-0.05"):
            risk_alerts.append(
                {
                    "level": "warn",
                    "title": "净值回撤 / Drawdown",
                    "detail": f"当前相对历史高点回撤 {str((abs(drawdown) * Decimal('100')).quantize(Decimal('0.01')))}%。",
                }
            )
        latest_run = self.state.last_run_results[-1] if self.state.last_run_results else None
        if latest_run and latest_run.get("review", {}).get("verdict") not in {None, "PASS"}:
            risk_alerts.append(
                {
                    "level": "warn",
                    "title": "审核未通过 / Review Flag",
                    "detail": "最近一次策略审核不是 PASS，建议先检查 review comments 再继续自动执行。",
                }
            )
        if live_error:
            risk_alerts.append(
                {
                    "level": "info",
                    "title": "行情降级 / Price Fallback",
                    "detail": f"实时价格刷新失败，当前估值改用最近成交价或成本价。原因：{live_error[:80]}",
                }
            )

        enriched["position_rows"] = position_rows
        enriched["sector_exposure_rows"] = sector_rows
        enriched["today_summary"] = today_summary
        enriched["risk_alerts"] = risk_alerts
        enriched["total_unrealized_pnl"] = str(total_unrealized.quantize(Decimal("0.0001")))
        enriched["total_position_value"] = str(total_position_value.quantize(Decimal("0.0001")))
        enriched["mark_source"] = mark_source
        return enriched

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
              <p class="eyebrow">Collaboration Console</p>
              <h2>和我交互</h2>
            </div>
          </div>
          <div class="chat-thread">{''.join(messages) if messages else '<div class="muted">还没有消息，先发一条试试。</div>'}</div>
          <form class="stack" method="post" action="/chat">
            <textarea name="message" rows="3" placeholder="输入一句话，先做本地回显占位..."></textarea>
            <button class="button button--primary" type="submit">发送消息</button>
          </form>
        </section>
        """

    def _render_flash_messages(self, audience: Optional[str] = None) -> str:
        if not self.state.flash_messages:
            return ""
        normalized_audience = str(audience or "").strip().lower()
        messages: List[str] = []
        remaining: List[Dict[str, str]] = []
        for raw_entry in self.state.flash_messages:
            if isinstance(raw_entry, dict):
                message = str(raw_entry.get("message", ""))
                entry_audience = str(raw_entry.get("audience", "")).strip().lower()
            else:
                message = str(raw_entry)
                entry_audience = ""
            if not entry_audience or entry_audience == normalized_audience:
                if message:
                    messages.append(message)
            else:
                remaining.append({"message": message, "audience": entry_audience})
        self.state.flash_messages.clear()
        self.state.flash_messages.extend(remaining)
        if not messages:
            return ""
        items = "".join(f"<li>{escape(message)}</li>" for message in messages)
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
          <thead><tr><th>Date / 日期</th><th>NAV / 净值</th><th>Fills / 成交数</th></tr></thead>
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
          <thead><tr><th>Date / 日期</th><th>Return / 收益</th><th>Excess / 超额</th><th>Win Rate / 胜率</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
        """

    def _render_rolling_backtest_daily_preview(self, daily: Iterable[Dict[str, Any]]) -> str:
        rows = []
        for row in list(daily)[-8:]:
            rows.append(
                f"""
                <tr>
                  <td>{escape(str(row.get('trade_date', '')))}</td>
                  <td>{escape(str(row.get('period_return', '')))}</td>
                  <td>{escape(str(row.get('cumulative_portfolio_return', '')))}</td>
                  <td>{escape(str(row.get('turnover', '')))}</td>
                  <td>{escape(str(row.get('total_fees', '')))}</td>
                </tr>
                """
            )
        table_rows = "".join(rows) if rows else "<tr><td colspan='5'>暂无滚动回测数据</td></tr>"
        return f"""
        <table class="data-table">
          <thead><tr><th>Date / 日期</th><th>Daily / 单期收益</th><th>Cumulative / 累计收益</th><th>Turnover / 换手</th><th>Fees / 费用</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
        """

    def _render_strategy_lab_nav_chart(self, daily: Iterable[Dict[str, Any]]) -> str:
        points = list(daily)
        if len(points) < 2:
            return """
            <div class="chart-block chart-block--mini">
              <div class="chart-block__header">
                <h3>Backtest NAV / 回测净值曲线</h3>
              </div>
              <div class="muted">至少需要两期以上的滚动回测结果才会显示净值曲线。</div>
            </div>
            """
        values = [Decimal(str(item.get("end_of_day_nav", "0") or "0")) for item in points]
        min_value = min(values)
        max_value = max(values)
        span = max(max_value - min_value, Decimal("1"))
        width = 720
        height = 180
        svg_points = []
        for index, value in enumerate(values):
            x = (width / max(len(values) - 1, 1)) * index
            normalized = (value - min_value) / span
            y = float(Decimal(height - 24) - (normalized * Decimal(height - 52))) + 12.0
            svg_points.append(f"{x:.2f},{y:.2f}")
        first_label = points[0].get("trade_date", "")
        last_label = points[-1].get("trade_date", "")
        return f"""
        <div class="chart-block">
          <div class="chart-block__header">
            <h3>Backtest NAV / 回测净值曲线</h3>
            <span class="muted">{escape(str(first_label))} -> {escape(str(last_label))}</span>
          </div>
          <svg class="sparkline sparkline--large" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="Backtest NAV chart">
            <polyline fill="none" stroke="url(#labNavGradient)" stroke-width="4" points="{' '.join(svg_points)}"></polyline>
            <defs>
              <linearGradient id="labNavGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#7dd3fc"></stop>
                <stop offset="100%" stop-color="#a78bfa"></stop>
              </linearGradient>
            </defs>
          </svg>
        </div>
        """

    def _render_alpha_mix_table(self, rows: Iterable[Dict[str, Any]]) -> str:
        table_rows = []
        for row in rows:
            table_rows.append(
                f"""
                <tr>
                  <td>{escape(str(row.get('family', '')))}</td>
                  <td>{escape(str(row.get('net_weight', '')))}</td>
                  <td>{escape(str(row.get('gross_weight', '')))}</td>
                  <td>{escape(str(row.get('share_of_gross', '')))}</td>
                </tr>
                """
            )
        body = "".join(table_rows) if table_rows else "<tr><td colspan='4'>暂无 alpha mix 数据</td></tr>"
        return f"""
        <table class="data-table">
          <thead><tr><th>Family / 因子家族</th><th>Net / 净权重</th><th>Gross / 总暴露</th><th>Share / 占比</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
        """

    def _render_regime_summary_table(self, rows: Iterable[Dict[str, Any]]) -> str:
        table_rows = []
        for row in rows:
            table_rows.append(
                f"""
                <tr>
                  <td>{escape(str(row.get('regime', '')))}</td>
                  <td>{escape(str(row.get('observations', '0')))}</td>
                  <td>{escape(str(row.get('average_period_return', '')))}</td>
                  <td>{escape(str(row.get('average_excess_period_return', '')))}</td>
                  <td>{escape(str(row.get('win_rate', '')))}</td>
                </tr>
                """
            )
        body = "".join(table_rows) if table_rows else "<tr><td colspan='5'>暂无 regime 归因数据</td></tr>"
        return f"""
        <table class="data-table">
          <thead><tr><th>Regime / 市场状态</th><th>Obs / 样本</th><th>Return / 平均收益</th><th>Excess / 平均超额</th><th>Win Rate / 胜率</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
        """

    def _render_selected_factor_rows(self, rows: Iterable[Dict[str, Any]]) -> str:
        cards = []
        for row in rows:
            cards.append(
                f"""
                <article class="summary-tile">
                  <span>{escape(str(row.get('label', '')))}</span>
                  <strong>{escape(str(row.get('effective_weight', '')))}</strong>
                  <small>Tilt / 倍率 {escape(str(row.get('tilt', '1.0')))} | Base / 基线 {escape(str(row.get('base_weight', '0')))}</small>
                </article>
                """
            )
        return f"<div class=\"summary-grid\">{''.join(cards) if cards else self._summary_tile('Factors / 因子', '暂无', '当前没有选中的有效因子')}</div>"

    def _build_iteration_notes(
        self,
        scorecard: Dict[str, Any],
        regime_rows: List[Dict[str, Any]],
        summary: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        notes: List[Dict[str, str]] = []
        decision = str(scorecard.get("decision", "REVIEW"))
        if decision == "KEEP":
            notes.append(
                {
                    "level": "good",
                    "title": "继续跟踪 / Keep",
                    "detail": "这套参数当前收益、超额和风险指标相对均衡，可以作为下一轮参数微调的基础版本。",
                }
            )
        elif decision == "DROP":
            notes.append(
                {
                    "level": "warn",
                    "title": "考虑淘汰 / Drop",
                    "detail": "当前实验净收益、超额和回撤同时偏弱，优先把研究资源投到别的参数组。",
                }
            )
        else:
            notes.append(
                {
                    "level": "info",
                    "title": "需要复核 / Review",
                    "detail": "当前更像是有局部 edge 但还不够稳，建议继续压换手或收紧风险暴露后再比较。",
                }
            )
        turnover = Decimal(str(summary.get("average_turnover", "0") or "0"))
        if turnover > Decimal("0.20"):
            notes.append(
                {
                    "level": "warn",
                    "title": "先压换手",
                    "detail": "平均换手偏高，建议先提高 rebalance buffer 或降低动量因子的权重倍率。",
                }
            )
        positive_regimes = [row for row in regime_rows if Decimal(str(row.get("average_excess_period_return", "0") or "0")) > 0]
        if positive_regimes and len(positive_regimes) < len(regime_rows):
            weak_regime = min(
                regime_rows,
                key=lambda row: Decimal(str(row.get("average_excess_period_return", "0") or "0")),
            )
            notes.append(
                {
                    "level": "info",
                    "title": "状态分化",
                    "detail": f"当前在 {weak_regime.get('regime', 'RANGE')} 状态下表现更弱，下一轮可以针对这一状态单独做权重收缩或防御约束。",
                }
            )
        warnings = scorecard.get("warnings", [])
        if warnings:
            notes.append(
                {
                    "level": "info",
                    "title": "本轮警示",
                    "detail": "；".join(str(item) for item in warnings[:3]),
                }
            )
        return notes

    def _render_strategy_lab_workspace(
        self,
        payload: Dict[str, Any],
        title: str,
        eyebrow: str,
        artifact_href: Optional[str] = None,
    ) -> str:
        summary = payload.get("summary", {})
        signal_validation = payload.get("signal_validation", {})
        attribution = payload.get("attribution", {})
        rolling_backtest = payload.get("rolling_backtest", {})
        factor_rows = summary.get("selected_factor_rows", [])
        alpha_mix_rows = attribution.get("alpha_mix", [])
        regime_rows = attribution.get("regime_summary", [])
        scorecard = attribution.get("scorecard", {})
        iteration_notes = attribution.get("iteration_notes", [])
        nav_chart_html = self._render_strategy_lab_nav_chart(rolling_backtest.get("daily", []))
        action_html = (
            f'<a class="button button--ghost" href="{escape(artifact_href)}" target="_blank" rel="noreferrer">打开 JSON 工件</a>'
            if artifact_href
            else ""
        )
        strengths = "".join(f"<li>{escape(str(item))}</li>" for item in scorecard.get("strengths", [])) or "<li class='muted'>暂无明显强项</li>"
        warnings = "".join(f"<li>{escape(str(item))}</li>" for item in scorecard.get("warnings", [])) or "<li class='muted'>暂无显著警示</li>"
        notes_html = "".join(
            f"<article class=\"alert-card alert-card--{escape(str(note.get('level', 'info')))}\"><strong>{escape(str(note.get('title', '提示')))}</strong><p>{escape(str(note.get('detail', '')))}</p></article>"
            for note in iteration_notes
        ) or "<article class=\"alert-card alert-card--good\"><strong>迭代建议</strong><p>当前还没有生成额外建议。</p></article>"
        return f"""
        <section class="panel panel--selected">
          <div class="panel__header">
            <div>
              <p class="eyebrow">{escape(eyebrow)}</p>
              <h2>{escape(title)}</h2>
            </div>
            {action_html}
          </div>
          <div class="summary-grid">
            {self._summary_tile("Market / 市场", summary.get("market", "N/A"), "本次实验的目标市场")}
            {self._summary_tile("Window / 区间", f"{summary.get('start_date', '')} -> {summary.get('end_date', '')}", "滚动回测时间窗口")}
            {self._summary_tile("Total Return / 总收益", summary.get("total_return", "N/A"), "组合滚动回测的累计收益")}
            {self._summary_tile("Excess Return / 超额收益", summary.get("rolling_excess_return", "N/A"), "相对基准的累计超额")}
            {self._summary_tile("Sharpe / 夏普", summary.get("sharpe_ratio", "N/A"), "风险调整后的收益质量")}
            {self._summary_tile("Max Drawdown / 最大回撤", summary.get("max_drawdown", "N/A"), "净值相对峰值的最大回撤")}
            {self._summary_tile("Avg Turnover / 平均换手", summary.get("average_turnover", "N/A"), "组合平均换手水平")}
            {self._summary_tile("Fee Drag / 费用拖累", summary.get("fee_drag", "N/A"), "费用占初始资金的拖累")}
            {self._summary_tile("Signal Excess / 选股超额", summary.get("average_excess_return", "N/A"), "单期选股相对基准的平均超额")}
            {self._summary_tile("Signal Win Rate / 选股胜率", summary.get("average_win_rate", "N/A"), "单期样本正超额占比")}
            {self._summary_tile("Observations / 样本数", summary.get("observations", "0"), "选股收益分析的有效样本数")}
            {self._summary_tile("Decision / 结论", scorecard.get("decision", "N/A"), "本轮实验的保留/复核/淘汰建议")}
          </div>
          {nav_chart_html}
          <div class="panel__split">
            <div>
              <h3>Factor Setup / 因子配置</h3>
              {self._render_selected_factor_rows(factor_rows)}
            </div>
            <div>
              <h3>Scorecard / 实验评分卡</h3>
              <div class="scorecard">
                <div class="summary-grid">
                  {self._summary_tile("Score / 综合分", scorecard.get("score", "N/A"), "把收益、回撤、超额、换手和费用压成一个实验打分")}
                  {self._summary_tile("Rationale / 依据", scorecard.get("rationale", "N/A"), "本轮结论的核心数字摘要")}
                </div>
                <div class="panel__split panel__split--compact">
                  <div>
                    <h4>Strengths / 优势</h4>
                    <ul class="insight-list">{strengths}</ul>
                  </div>
                  <div>
                    <h4>Warnings / 警示</h4>
                    <ul class="insight-list">{warnings}</ul>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="panel__split">
            <div>
              <h3>Regime Attribution / 市场状态归因</h3>
              {self._render_regime_summary_table(regime_rows)}
            </div>
            <div>
              <h3>Alpha Mix / 因子家族暴露</h3>
              {self._render_alpha_mix_table(alpha_mix_rows)}
            </div>
          </div>
          <div class="panel__split">
            <div>
              <h3>Signal Validation / 选股收益分析</h3>
              {self._render_factor_backtest_daily_preview(signal_validation.get("daily", payload.get("daily", [])))}
            </div>
            <div>
              <h3>Rolling Backtest / 滚动回测摘录</h3>
              {self._render_rolling_backtest_daily_preview(rolling_backtest.get("daily", []))}
            </div>
          </div>
          <div>
            <h3>Next Iteration / 下一轮迭代建议</h3>
            <div class="alert-grid">{notes_html}</div>
          </div>
        </section>
        """

    def _render_chart_block(self, artifact_relative_path: str, summary: Dict[str, Any]) -> str:
        chart_path = self._chart_for_artifact(artifact_relative_path)
        if chart_path is None:
            return ""
        return f"""
        <div class="chart-block">
          <div class="chart-block__header">
            <h3>Equity Curve / 净值曲线</h3>
            <a href="/artifact-file?path={quote(chart_path.relative_to(ARTIFACT_ROOT).as_posix())}" target="_blank" rel="noreferrer">打开 PNG 图表</a>
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

    def _recent_indexed_results(self, limit: int = 8) -> List[Dict[str, Any]]:
        try:
            return list_results(ARTIFACT_ROOT, limit=limit)
        except Exception:
            return []

    def _paper_run_matches_context(
        self,
        row: Dict[str, Any],
        *,
        account_id: Optional[str] = None,
        market: Optional[str] = None,
    ) -> bool:
        normalized_account_id = str(account_id or "").strip()
        normalized_market = str(market or "").strip().upper()
        paper_summary = row.get("paper_run_summary", {}) if isinstance(row.get("paper_run_summary"), dict) else {}
        paper_account = row.get("paper_account", {}) if isinstance(row.get("paper_account"), dict) else {}
        row_account_id = str(
            paper_summary.get("account_id")
            or row.get("account_id")
            or paper_account.get("account_id")
            or ""
        ).strip()
        row_market = str(
            row.get("market")
            or paper_summary.get("market")
            or paper_account.get("market")
            or ""
        ).strip().upper()
        if normalized_account_id and row_account_id:
            return row_account_id == normalized_account_id
        if normalized_market and row_market:
            return row_market == normalized_market
        return True

    def _latest_paper_run_result(self, *, account_id: Optional[str] = None, market: Optional[str] = None) -> Optional[Dict[str, Any]]:
        for row in reversed(self.state.last_run_results):
            if row.get("paper_run_summary") and self._paper_run_matches_context(row, account_id=account_id, market=market):
                return row
        indexed_runs = self._recent_indexed_results(limit=8)
        for row in indexed_runs:
            if str(row.get("artifact_kind")) != "local_paper_run":
                continue
            if not self._paper_run_matches_context(row, account_id=account_id, market=market):
                continue
            paper_run_summary = row.get("paper_run_summary", {}) if isinstance(row.get("paper_run_summary"), dict) else {}
            artifacts = row.get("artifacts", {}) if isinstance(row.get("artifacts"), dict) else {}
            return {
                "paper_run_summary": paper_run_summary,
                "paper_paths": {
                    "run_json": artifacts.get("json"),
                    "run_markdown": artifacts.get("markdown"),
                    "ledger": artifacts.get("ledger"),
                    "account": artifacts.get("account"),
                },
            }
        return None

    def _symbol_catalog(self, market: Market) -> List[Dict[str, str]]:
        cache_key = market.value
        cached = self._symbol_catalog_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            entries = load_symbol_directory(market)
        except Exception:
            entries = []
        catalog = [
            {"symbol": str(symbol).upper(), "name": str(name or "").strip()}
            for symbol, name in entries
            if str(symbol).strip()
        ]
        self._symbol_catalog_cache[cache_key] = catalog
        return catalog

    def _parse_symbol_values(self, raw_symbols: str) -> List[str]:
        seen = set()
        parsed: List[str] = []
        for item in str(raw_symbols or "").split(","):
            normalized = item.strip().upper()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(normalized)
        return parsed

    def _render_symbol_picker(self, prefix: str, market: Market, field_name: str, raw_symbols: str) -> str:
        selected_symbols = self._parse_symbol_values(raw_symbols)
        catalog_map = {row["symbol"]: row["name"] for row in self._symbol_catalog(market)}
        selected_rows = "".join(
            f"""
            <button class="symbol-chip" type="button" data-symbol-remove value="{escape(symbol)}">
              <span class="symbol-chip__main">{escape(symbol)}</span>
              <small>{escape(catalog_map.get(symbol, '已选标的') or '已选标的')}</small>
              <span class="symbol-chip__action">移除</span>
            </button>
            """
            for symbol in selected_symbols
        ) or '<span class="muted">当前未限制股票池，默认跑全市场。</span>'
        return f"""
        <div class="symbol-picker" data-symbol-picker data-market="{escape(market.value)}" data-picker-id="{escape(prefix)}">
          <div class="symbol-picker__header">
            <strong>Search / 搜索股票</strong>
            <span class="symbol-picker__caption">输入代码或公司名，回车前就会实时匹配</span>
          </div>
          <div class="symbol-picker__toolbar">
            <div class="symbol-picker__search-shell">
              <span class="symbol-picker__search-label">Ticker / 名称</span>
              <input class="symbol-picker__search" type="search" placeholder="例如 AAPL、Apple、600036、招商银行" data-symbol-search />
            </div>
            <div class="symbol-picker__actions">
              <button class="button button--primary symbol-picker__button" type="button" data-symbol-search-button>立即搜索</button>
              <button class="button button--ghost symbol-picker__button" type="button" data-symbol-select-visible>选择当前结果</button>
              <button class="button button--ghost symbol-picker__button" type="button" data-symbol-clear>清空</button>
            </div>
          </div>
          <div class="symbol-picker__status" data-symbol-status>输入关键字后会显示匹配股票。</div>
          <div class="symbol-picker__workspace">
            <section class="symbol-pane">
              <div class="symbol-pane__header">
                <strong>Search Results / 搜索结果</strong>
                <span>点击左侧结果即可加入右侧已选列表</span>
              </div>
              <div class="symbol-picker__options" data-symbol-results>
                <div class="muted">输入关键字后会显示匹配股票。</div>
              </div>
            </section>
            <section class="symbol-pane">
              <div class="symbol-pane__header">
                <strong>Selected / 已选股票</strong>
                <span>右侧展示当前股票池，点击单个项目可移除</span>
              </div>
              <div class="symbol-picker__selected" data-symbol-selected>{selected_rows}</div>
            </section>
          </div>
          <input type="hidden" name="{escape(field_name)}" value="{escape(','.join(selected_symbols))}" data-symbol-hidden />
          <p class="field-note" data-symbol-summary>{'已选 ' + str(len(selected_symbols)) + ' 只' if selected_symbols else '留空表示全市场'}</p>
        </div>
        """

    def _render_strategy_preset_picker(self, market: Market, field_name: str) -> str:
        options = ['<option value="">Market default / 使用市场默认</option>']
        for preset in strategy_presets_for_market(market):
            options.append(
                f'<option value="{escape(preset.preset_id)}">{escape(preset.display_name)} ({escape(preset.preset_id)})</option>'
            )
        return f"""
        <label>Selected Strategy / 选择策略<span class="field-note">{escape(market.value)} 市场可选预设</span>
          <select name="{escape(field_name)}">
            {''.join(options)}
          </select>
        </label>
        """

    def _render_job_progress_panel(self, active_job: Optional[Dict[str, Any]], panel_id: str) -> str:
        progress_pct = 0
        if isinstance(active_job, dict):
            default_progress = 100 if str(active_job.get("status", "")) in {"SUCCESS", "FAILED", "BLOCKED", "MANUAL_RELEASED", "STALE"} else 0
            progress_pct = int(active_job.get("progress_pct", default_progress))
        stage = str(active_job.get("stage", active_job.get("status", "IDLE"))) if isinstance(active_job, dict) else "IDLE"
        detail = str(active_job.get("detail", "当前没有运行中的后台任务。")) if isinstance(active_job, dict) else "当前没有运行中的后台任务。"
        kind = str(active_job.get("kind", "N/A")) if isinstance(active_job, dict) else "N/A"
        started_at = str(active_job.get("started_at", "")) if isinstance(active_job, dict) else ""
        panel_class = "job-progress job-progress--active" if active_job and str(active_job.get("status", "RUNNING")) == "RUNNING" else "job-progress"
        return f"""
        <section class="panel panel--progress {panel_class}" id="{escape(panel_id)}" data-job-progress-panel>
          <div class="panel__header">
            <div>
              <p class="eyebrow">Task Progress</p>
              <h2>任务进度</h2>
            </div>
            <span class="status-pill" data-job-kind>{escape(kind)}</span>
          </div>
          <div class="job-progress__meta">
            <span data-job-stage>{escape(stage)}</span>
            <span data-job-started>{escape(started_at or '未运行')}</span>
          </div>
          <div class="job-progress__bar">
            <span data-job-progress-fill style="width: {progress_pct}%;"></span>
          </div>
          <div class="job-progress__meta">
            <strong data-job-progress-label>{progress_pct}%</strong>
            <span data-job-detail>{escape(detail)}</span>
          </div>
        </section>
        """

    def _symbols_for_market(self, market: Market, body: Dict[str, List[str]]) -> List[str]:
        field = "symbols_cn" if market == Market.CN else "symbols_us"
        raw_symbols = body.get(field, [""])[0]
        return self._parse_symbol_values(raw_symbols)

    def _markets_from_form(self, raw_market: str) -> List[Market]:
        if raw_market == "ALL":
            return [Market.CN, Market.US]
        return [Market(raw_market)]

    def _safe_artifact_path(self, relative_path: str) -> Optional[Path]:
        artifact_root = ARTIFACT_ROOT.resolve()
        raw_path = Path(relative_path)
        candidate = raw_path.resolve() if raw_path.is_absolute() else (artifact_root / relative_path).resolve()
        if artifact_root not in candidate.parents and candidate != artifact_root:
            return None
        return candidate

    def _artifact_query_path(self, artifact_path: str) -> str:
        path = Path(artifact_path)
        if path.is_absolute():
            try:
                return path.relative_to(ARTIFACT_ROOT.resolve()).as_posix()
            except ValueError:
                return artifact_path
        return artifact_path

    def _html_page(
        self,
        content: str,
        title: str = DEFAULT_PAGE_TITLE,
        primary_view: str = "paper",
        subview: str = "default",
    ) -> WebResponse:
        template = self._load_template("dashboard.html")
        body = Template(template).safe_substitute(
            page_title=escape(title),
            content=content,
            body_class="dashboard-app",
            primary_view=escape(primary_view),
            subview=escape(subview),
        )
        return WebResponse(
            status=HTTPStatus.OK,
            content_type="text/html; charset=utf-8",
            body=body.encode("utf-8"),
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    def _dashboard_view(self, query: Dict[str, List[str]]) -> str:
        raw_view = query.get("view", ["overview"])[0].strip().lower()
        if raw_view in {"overview", "workbench", "results", "paper", "optimize", "run"}:
            return raw_view
        return "overview"

    def _primary_view_for_view(self, view: str) -> str:
        return PRIMARY_VIEW_ALIASES.get(view, "paper")

    def _primary_subview_for_view(self, primary_view: str, query: Dict[str, List[str]]) -> str:
        tabs = PRIMARY_VIEW_TABS.get(primary_view, [])
        default_subview = tabs[0][0] if tabs else "default"
        raw_subview = query.get("subview", [default_subview])[0].strip().lower()
        if primary_view == "paper":
            raw_subview = PAPER_SUBVIEW_ALIASES.get(raw_subview, raw_subview)
        if primary_view == "results":
            raw_subview = RESULTS_SUBVIEW_ALIASES.get(raw_subview, raw_subview)
        tab_ids = {tab_id for tab_id, _ in tabs}
        return raw_subview if raw_subview in tab_ids else default_subview

    def _strategy_state_store(self) -> StrategyStateStore:
        return StrategyStateStore(ARTIFACT_ROOT)

    def _view_url(self, view: str, path: str = "/", query: Optional[Dict[str, str]] = None) -> str:
        params = [("view", view)]
        if query:
            params.extend((key, value) for key, value in query.items() if value not in {None, ""})
        query_string = "&".join(f"{key}={quote(str(value), safe='/')}" for key, value in params)
        return f"{path}?{query_string}"

    def _requested_view(self, body: Dict[str, List[str]], default: str = "overview") -> str:
        raw_view = body.get("view", [default])[0].strip().lower()
        if raw_view in {"overview", "workbench", "results", "paper", "optimize", "run"}:
            return raw_view
        return default

    def _render_page_shell(
        self,
        active_page: str,
        title: str,
        eyebrow: str,
        description: str,
        body: str,
        subview: str = "default",
        query: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        status_active_page = active_page if active_page in {"paper", "optimize", "run", "results"} else "paper"
        return f"""
        <main class="app-shell app-shell--paper-first">
          {self._render_status_bar(status_active_page)}
          <div class="app-shell__frame">
            <aside class="side-nav">
              <div class="side-nav__panel">
                <p class="eyebrow">Section Tabs</p>
                <h2>{escape(title.split(' / ')[0])}</h2>
                {self._render_section_tabs(active_page, subview, query=query)}
              </div>
            </aside>
            <section class="page-shell">
              <header class="page-header">
                <div>
                  <p class="eyebrow">{escape(eyebrow)}</p>
                  <h1>{escape(title)}</h1>
                  <p class="page-header__copy hero__copy">{escape(description)}</p>
                </div>
              </header>
              <div class="page-shell__body">
                {body}
              </div>
            </section>
          </div>
          {self._render_interactive_script()}
        </main>
        """

    def _render_primary_nav(self, active_page: str) -> str:
        items = [
            ("paper", "/?view=paper", "模拟盘", "账户、流水与执行结果"),
            ("optimize", "/?view=optimize", "策略优化", "因子回测与实验迭代"),
            ("run", "/?view=run", "策略运行", "提交运行与查看反馈"),
            ("results", "/?view=results", "结果中心", "研究与运行结果索引"),
        ]
        links = "".join(
            f"""
            <a class="primary-nav__link{' primary-nav__link--active' if key == active_page else ''}" href="{href}">
              <strong>{escape(label)}</strong>
              <span>{escape(description)}</span>
            </a>
            """
            for key, href, label, description in items
        )
        return f"""
        <div class="status-strip__nav-shell">
          <p class="eyebrow">Primary Navigation</p>
          <nav class="primary-nav" aria-label="Primary Navigation">
            {links}
          </nav>
        </div>
        """

    def _render_section_tabs(
        self,
        primary_view: str,
        subview: str,
        query: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        tabs = PRIMARY_VIEW_TABS.get(primary_view, [])
        if not tabs:
            return ""
        preserved_query: Dict[str, str] = {}
        if primary_view == "paper" and query:
            for key in ("paper_account_id", "paper_start_date", "paper_end_date"):
                value = query.get(key, [""])[0].strip()
                if value:
                    preserved_query[key] = value
        links = "".join(
            f"""
            <a class="section-tabs__link{' section-tabs__link--active' if tab_id == subview else ''}" href="{self._view_url(primary_view, query={**preserved_query, 'subview': tab_id})}" data-subview="{escape(tab_id)}">
              <strong>{escape(label)}</strong>
            </a>
            """
            for tab_id, label in tabs
        )
        return f"""
        <nav class="section-tabs" aria-label="{escape(primary_view)} section tabs" data-primary-view="{escape(primary_view)}" data-subview="{escape(subview)}">
          {links}
        </nav>
        """

    def _render_overview_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        flash_html = self._render_flash_messages("overview")
        body = f"""
          {flash_html}
          {self._render_morning_briefing()}
        """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title="Morning Brief / 今日总览",
                eyebrow="Morning Brief",
                description="30 秒看完今天的状态、最近研究、最近运行和常用入口。",
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _strategy_default_preset_id(self, market: Market) -> str:
        state = self._strategy_state_store().load_market_state(market)
        current_execution_preset_id = str(state.get("current_execution_preset_id") or "").strip()
        if current_execution_preset_id:
            try:
                lookup_strategy_preset(market, current_execution_preset_id)
                return current_execution_preset_id
            except KeyError:
                pass
        presets = strategy_presets_for_market(market)
        return presets[0].preset_id if presets else ""

    def _render_strategy_preset_picker(self, market: Market, field_name: str, selected_preset_id: Optional[str] = None) -> str:
        default_preset_id = selected_preset_id or self._strategy_default_preset_id(market)
        defaults = self._load_project_config()["run_defaults"]
        recommended_account_id = self._recommended_account_id(str(defaults["market"]))
        return f"""
        <label>Selected Strategy / 选择策略<span class="field-note">{escape(market.value)} 市场可选预设</span>
          <select name="{escape(field_name)}">
            {''.join(
                f'<option value="{escape(preset.preset_id)}"{" selected" if preset.preset_id == default_preset_id else ""}>{escape(preset.display_name)} ({escape(preset.preset_id)})</option>'
                for preset in strategy_presets_for_market(market)
            )}
          </select>
        </label>
        """

    def _render_strategy_run_form(self, view: str = "run") -> str:
        config = self._load_project_config()
        defaults = config["run_defaults"]
        recommended_account_id = self._recommended_account_id(str(defaults["market"]))
        cn_picker = self._render_symbol_picker(
            "run-cn",
            Market.CN,
            "symbols_cn",
            str(defaults["symbols_cn"]),
        )
        us_picker = self._render_symbol_picker(
            "run-us",
            Market.US,
            "symbols_us",
            str(defaults["symbols_us"]),
        )
        return f"""
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Strategy Run</p>
              <h2>Strategy Run / 策略运行</h2>
            </div>
          </div>
          <form class="stack" method="post" action="/run" id="run-form" data-async-job-form="strategy_run">
            <input type="hidden" name="view" value="{escape(view)}" />
            <div class="grid-form">
              <label>Market / 市场<span class="field-note">默认策略运行市场</span><select id="run-market-select" name="market"><option value="ALL"{' selected' if defaults['market'] == 'ALL' else ''}>ALL</option><option value="CN"{' selected' if defaults['market'] == 'CN' else ''}>CN</option><option value="US"{' selected' if defaults['market'] == 'US' else ''}>US</option></select></label>
              {self._render_strategy_preset_picker(Market.CN, "selected_strategy_cn")}
              {self._render_strategy_preset_picker(Market.US, "selected_strategy_us")}
              <label>Runtime / 运行语义<span class="field-note">默认实时/回放语义</span><select name="runtime_mode"><option value="PAPER"{' selected' if defaults['runtime_mode'] == 'PAPER' else ''}>PAPER</option><option value="BACKTEST"{' selected' if defaults['runtime_mode'] == 'BACKTEST' else ''}>BACKTEST</option><option value="LIVE"{' selected' if defaults['runtime_mode'] == 'LIVE' else ''}>LIVE</option></select></label>
              <label>Execution / 执行模式<span class="field-note">默认 advisory 或 auto</span><select name="execution_mode"><option value="ADVISORY"{' selected' if defaults['execution_mode'] == 'ADVISORY' else ''}>ADVISORY</option><option value="AUTO"{' selected' if defaults['execution_mode'] == 'AUTO' else ''}>AUTO</option></select></label>
              <label>Broker / 接入口<span class="field-note">默认 broker 类型</span><select name="broker"><option value="NONE"{' selected' if defaults['broker'] == 'NONE' else ''}>NONE</option><option value="LOCAL_PAPER"{' selected' if defaults['broker'] == 'LOCAL_PAPER' else ''}>LOCAL_PAPER</option></select></label>
              <label>Cash / 初始资金<span class="field-note">新账户起始现金</span><input name="cash" value="{escape(str(defaults['cash']))}" /></label>
              <label>Paper Account ID / 模拟盘账户<span class="field-note">默认本地模拟盘 ID</span><input id="run-broker-account-id" name="broker_account_id" value="{escape(str(defaults['broker_account_id']))}" data-recommended-account="{escape(recommended_account_id)}" /><span class="field-note field-note--accent" id="run-broker-account-recommendation">推荐账户名: {escape(recommended_account_id)}</span></label>
              <label>Top N / 选股数<span class="field-note">默认组合容量</span><input name="top_n" value="{escape(str(defaults['top_n']))}" /></label>
              <label>Detail Limit / 细节样本<span class="field-note">默认详细抓取数量</span><input name="detail_limit" value="{escape(str(defaults['detail_limit']))}" /></label>
              <label>History Limit / 历史窗口<span class="field-note">默认研究窗口 bars</span><input name="history_limit" value="{escape(str(defaults['history_limit']))}" /></label>
              <label>Beta Window / Beta 窗口<span class="field-note">默认 beta 估算区间</span><input name="beta_window" value="{escape(str(defaults['beta_window']))}" /></label>
              <label>Forward Days / 前瞻天数<span class="field-note">默认 forward report 持有天数</span><input name="forward_days" value="{escape(str(defaults['forward_days']))}" /></label>
              <label>As Of Date / 历史日期<span class="field-note">留空表示最近有效交易日</span><input name="as_of_date" value="{escape(str(defaults['as_of_date']))}" placeholder="2026-03-15" /></label>
              <label class="checkbox-field"><input type="checkbox" name="route_orders"{' checked' if defaults.get('route_orders') else ''} />Route Orders / 默认写入模拟盘</label>
            </div>
            <div class="field-group field-group--full">
              <span>A 股 Symbols / A 股股票池</span>
              <span class="field-note">默认 A 股自选池，留空表示全市场</span>
              {cn_picker}
            </div>
            <div class="field-group field-group--full">
              <span>美股 Symbols / 美股股票池</span>
              <span class="field-note">默认美股自选池，留空表示全市场</span>
              {us_picker}
            </div>
            <div class="research-lab__actions">
              <button class="button button--primary" type="submit">提交策略运行</button>
              <span class="field-note">提交后会启动后台运行，并刷新最近执行反馈。</span>
            </div>
          </form>
        </section>
        """

    def _render_current_defaults_panel(self) -> str:
        config = self._load_project_config()
        run_defaults = config["run_defaults"]
        factor_defaults = config["factor_defaults"]
        ui_defaults = config["ui_defaults"]
        return f"""
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Current Defaults</p>
              <h2>Current Defaults / 当前默认配置</h2>
            </div>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Run Market / 运行市场", run_defaults.get("market", "N/A"), "默认策略运行市场")}
            {self._summary_tile("Runtime / 运行语义", run_defaults.get("runtime_mode", "N/A"), "默认运行语义")}
            {self._summary_tile("Execution / 执行模式", run_defaults.get("execution_mode", "N/A"), "默认执行模式")}
            {self._summary_tile("Broker / 接入口", run_defaults.get("broker", "N/A"), "默认 broker 类型")}
            {self._summary_tile("Cash / 初始资金", run_defaults.get("cash", "N/A"), "默认起始现金")}
            {self._summary_tile("Account / 模拟盘", ui_defaults.get("paper_account_id", "N/A"), "默认模拟盘账户")}
            {self._summary_tile("Factor Market / 因子市场", factor_defaults.get("factor_market", "N/A"), "默认因子回测市场")}
            {self._summary_tile("Factor Window / 回测区间", f"{factor_defaults.get('factor_start_date', 'N/A')} -> {factor_defaults.get('factor_end_date', 'N/A')}", "默认因子回测日期窗口")}
            {self._summary_tile("Holding / 持有周期", factor_defaults.get("factor_holding_sessions", "N/A"), "默认持有交易日数")}
            {self._summary_tile("Turnover Cap / 换手上限", factor_defaults.get("factor_turnover_cap", "N/A"), "默认组合换手上限")}
          </div>
        </section>
        """

    def _render_recent_execution_panel(self) -> str:
        system_status = self._build_system_status()
        display_job = system_status.get("display_job") if isinstance(system_status.get("display_job"), dict) else None
        active_job_label = "N/A"
        if display_job:
            active_job_label = str(display_job.get("kind") or display_job.get("job_kind") or display_job.get("status") or "N/A")
            stage = str(display_job.get("stage") or "").strip()
            if stage:
                active_job_label = f"{active_job_label} / {stage}"
        latest_run = self.state.last_run_results[-1] if self.state.last_run_results else {}
        latest_factor = self.state.last_factor_backtest_result if isinstance(self.state.last_factor_backtest_result, dict) else {}
        latest_factor_summary = latest_factor.get("summary", {}) if isinstance(latest_factor.get("summary"), dict) else {}
        return f"""
        <section class="panel workbench-panel--wide">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Recent Execution</p>
              <h2>Recent Execution / 最近执行反馈</h2>
            </div>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Run Status / 运行状态", "READY" if latest_run else "EMPTY", "最近一次策略运行是否已有结果")}
            {self._summary_tile("Backtest Status / 回测状态", "READY" if latest_factor else "EMPTY", "最近一次因子回测是否已有结果")}
            {self._summary_tile("Task Status / 当前任务", active_job_label, "当前后台任务状态")}
            {self._summary_tile("Run Count / 运行次数", len(self.state.last_run_results), "本次会话内的运行数量")}
            {self._summary_tile("Backtest Market / 回测市场", latest_factor_summary.get("market", "N/A") if latest_factor_summary else "N/A", "最近一次因子回测市场")}
          </div>
          <div class="workbench-feedback-grid">
            {self._render_run_results()}
            {self._render_factor_backtest_results()}
            {self._render_job_progress_panel(display_job, "workbench-job-progress")}
          </div>
        </section>
        """

    def _optimize_result_kind_label(self, artifact_kind: str) -> str:
        labels = {
            "factor_backtest": "Factor Backtest / 因子回测",
            "strategy_suite": "Strategy Suite / 策略套件",
            "rolling_backtest": "Rolling Backtest / 滚动回测",
            "validation": "Validation / 验证",
        }
        return labels.get(artifact_kind, f"{artifact_kind.replace('_', ' ').title()} / {artifact_kind or 'Result'}")

    def _optimize_record_from_state(self) -> Optional[Dict[str, Any]]:
        latest_factor = self.state.last_factor_backtest_result if isinstance(self.state.last_factor_backtest_result, dict) else None
        if not latest_factor:
            return None
        summary = latest_factor.get("summary", {}) if isinstance(latest_factor.get("summary"), dict) else {}
        artifacts = latest_factor.get("artifacts", {}) if isinstance(latest_factor.get("artifacts"), dict) else {}
        artifact_path = str(artifacts.get("json", "") or "").strip() or None
        return {
            "record_id": "factor_backtest:latest",
            "artifact_kind": "factor_backtest",
            "title": str(summary.get("subject_name") or summary.get("subject_id") or "Factor Backtest / 因子回测"),
            "market": str(summary.get("market", "N/A")),
            "summary": summary,
            "artifact_path": self._artifact_query_path(artifact_path) if artifact_path else None,
            "artifact_href": f"/artifact-file?path={quote(self._artifact_query_path(artifact_path))}" if artifact_path else None,
            "payload": latest_factor,
            "sort_key": "9999-12-31",
        }

    def _optimize_record_from_index(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        artifact_kind = str(row.get("artifact_kind", "") or "").strip()
        if artifact_kind == "local_paper_run":
            return None
        summary = row.get("summary", {}) if isinstance(row.get("summary"), dict) else {}
        artifacts = row.get("artifacts", {}) if isinstance(row.get("artifacts"), dict) else {}
        artifact_path = str(artifacts.get("json", "") or "").strip() or None
        return {
            "record_id": str(row.get("result_id") or artifact_path or summary.get("subject_name") or "optimize-result"),
            "artifact_kind": artifact_kind or "factor_backtest",
            "title": str(summary.get("subject_name") or summary.get("subject_id") or row.get("result_id", "N/A")),
            "market": str(row.get("market", summary.get("market", "N/A"))),
            "summary": summary,
            "artifact_path": self._artifact_query_path(artifact_path) if artifact_path else None,
            "artifact_href": f"/artifact-file?path={quote(self._artifact_query_path(artifact_path))}" if artifact_path else None,
            "payload": None,
            "sort_key": str(row.get("sort_date") or row.get("recorded_at") or row.get("result_id") or ""),
        }

    def _optimize_history_records(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        latest_state_record = self._optimize_record_from_state()
        if latest_state_record:
            records.append(latest_state_record)
        for row in self._recent_indexed_results(limit=64):
            record = self._optimize_record_from_index(row)
            if record:
                records.append(record)
        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            dedupe_key = str(record.get("artifact_path") or record.get("record_id") or record.get("title") or "")
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            deduped.append(record)
        return deduped[:12]

    def _optimize_resolve_selected_record(
        self,
        records: List[Dict[str, Any]],
        artifact_query: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if artifact_query:
            decoded_query = self._artifact_query_path(unquote(artifact_query))
            for record in records:
                if record.get("artifact_path") == decoded_query or record.get("record_id") == decoded_query:
                    return record
            return None
        return records[0] if records else None

    def _optimize_detail_payload(self, record: Dict[str, Any]) -> Dict[str, Any]:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else None
        if payload is None and record.get("artifact_path"):
            loaded = read_json_artifact(ARTIFACT_ROOT, str(record["artifact_path"]))
            payload = loaded if isinstance(loaded, dict) else {}
        if payload is None:
            payload = {}
        if isinstance(payload.get("strategies"), list) and payload.get("strategies"):
            strategy = next((item for item in payload["strategies"] if isinstance(item, dict)), {})
            summary = {
                "market": record.get("market", "N/A"),
                "subject_name": strategy.get("display_name") or record.get("title") or "Strategy Suite / 策略套件",
                "subject_id": strategy.get("preset_id") or record.get("summary", {}).get("subject_id"),
                "start_date": payload.get("start_date") or record.get("summary", {}).get("start_date") or "N/A",
                "end_date": payload.get("end_date") or record.get("summary", {}).get("end_date") or "N/A",
                "total_return": strategy.get("total_return", "N/A"),
                "rolling_excess_return": strategy.get("excess_return", "N/A"),
                "sharpe_ratio": strategy.get("scorecard", {}).get("score", "N/A") if isinstance(strategy.get("scorecard"), dict) else "N/A",
                "max_drawdown": strategy.get("max_drawdown", "N/A"),
                "average_turnover": strategy.get("average_turnover", "N/A"),
                "fee_drag": strategy.get("fee_drag", "N/A"),
                "average_excess_return": strategy.get("average_excess_return", strategy.get("excess_return", "N/A")),
                "average_win_rate": strategy.get("average_win_rate", "N/A"),
                "observations": strategy.get("observations", len(strategy.get("regime_summary", [])) if isinstance(strategy.get("regime_summary"), list) else 0),
            }
            return {
                "summary": summary,
                "attribution": {
                    "scorecard": strategy.get("scorecard", {}) if isinstance(strategy.get("scorecard"), dict) else {},
                    "alpha_mix": strategy.get("alpha_mix", []) if isinstance(strategy.get("alpha_mix"), list) else [],
                    "regime_summary": strategy.get("regime_summary", []) if isinstance(strategy.get("regime_summary"), list) else [],
                    "iteration_notes": strategy.get("iteration_notes", []) if isinstance(strategy.get("iteration_notes"), list) else [],
                },
                "rolling_backtest": payload.get("rolling_backtest", {}) if isinstance(payload.get("rolling_backtest"), dict) else {},
                "signal_validation": payload.get("signal_validation", {}) if isinstance(payload.get("signal_validation"), dict) else {},
                "recommended_presets": payload.get("recommended_presets", []) if isinstance(payload.get("recommended_presets"), list) else [],
                "watchlist_presets": payload.get("watchlist_presets", []) if isinstance(payload.get("watchlist_presets"), list) else [],
            }
        normalized_summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        if not normalized_summary and isinstance(payload.get("normalized_summary"), dict):
            normalized_summary = payload.get("normalized_summary", {})
        return {
            "summary": normalized_summary or record.get("summary", {}),
            "attribution": payload.get("attribution", {}) if isinstance(payload.get("attribution"), dict) else {},
            "rolling_backtest": payload.get("rolling_backtest", {}) if isinstance(payload.get("rolling_backtest"), dict) else {},
            "signal_validation": payload.get("signal_validation", {}) if isinstance(payload.get("signal_validation"), dict) else {},
            "recommended_presets": payload.get("recommended_presets", []) if isinstance(payload.get("recommended_presets"), list) else [],
            "watchlist_presets": payload.get("watchlist_presets", []) if isinstance(payload.get("watchlist_presets"), list) else [],
        }

    def _optimize_candidate_presets(self, payload: Dict[str, Any], market: str) -> Dict[str, Any]:
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        recommended = [str(item) for item in payload.get("recommended_presets", []) if str(item).strip()]
        watchlist = [str(item) for item in payload.get("watchlist_presets", []) if str(item).strip()]
        strategy_state = self._strategy_state_store().load_market_state(market)
        champion = recommended[0] if recommended else str(summary.get("subject_id") or strategy_state.get("champion_preset_id") or strategy_state.get("current_execution_preset_id") or "N/A")
        challenger = (
            recommended[1]
            if len(recommended) > 1
            else watchlist[0]
            if watchlist
            else str(strategy_state.get("challenger_preset_id") or champion)
        )
        current_strategy = str(strategy_state.get("current_execution_preset_id") or champion or "N/A")
        return {
            "champion": champion,
            "challenger": challenger,
            "current_strategy": current_strategy,
            "recommended": recommended,
            "watchlist": watchlist,
        }

    def _render_optimize_candidate_panel(self, payload: Dict[str, Any]) -> str:
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        market = str(summary.get("market", "N/A"))
        candidates = self._optimize_candidate_presets(payload, market)
        recommended_text = ", ".join(candidates["recommended"]) or "N/A"
        watchlist_text = ", ".join(candidates["watchlist"]) or "N/A"
        return f"""
        <section class="panel optimize-candidate-panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Strategy State</p>
              <h2>Champion / Challenger</h2>
            </div>
          </div>
          <div class="summary-grid optimize-candidate-grid">
            {self._summary_tile("Champion Candidate / 冠军候选", candidates["champion"], "从 recommended_presets 或当前状态推导")}
            {self._summary_tile("Challenger Candidate / 挑战者候选", candidates["challenger"], "从 watchlist_presets 或当前状态推导")}
            {self._summary_tile("Current Strategy / 当前策略", candidates["current_strategy"], "送回当前策略前的参考对象")}
          </div>
          <p class="muted">recommended_presets: {escape(recommended_text)}</p>
          <p class="muted">watchlist_presets: {escape(watchlist_text)}</p>
          <div class="research-lab__actions">
            <a class="button button--ghost" href="#" aria-disabled="true">send to current strategy</a>
          </div>
        </section>
        """

    def _render_optimize_history_cards(self, records: List[Dict[str, Any]]) -> str:
        if not records:
            return """
            <section class="panel panel--empty">
              <h2>Optimization Timeline / 优化时间线</h2>
              <p>先跑一次因子回测或策略套件，历史卡片才会出现。</p>
            </section>
            """
        cards = []
        for record in records:
            summary = record.get("summary", {}) if isinstance(record.get("summary"), dict) else {}
            artifact_href = record.get("artifact_href")
            title = str(record.get("title") or summary.get("subject_name") or summary.get("subject_id") or "Optimization Result")
            body_lines = [
                f"<p>Decision / 结论: {escape(str(summary.get('decision', 'N/A')))} | Score / 评分: {escape(str(summary.get('score', 'N/A')))}</p>",
                f"<p>Return / 收益: {escape(str(summary.get('return', 'N/A')))} | Market / 市场: {escape(str(record.get('market', summary.get('market', 'N/A'))))}</p>",
            ]
            if summary.get("excess_return") is not None:
                body_lines.append(f"<p>Excess / 超额: {escape(str(summary.get('excess_return', 'N/A')))}</p>")
            if artifact_href:
                body_lines.append(f'<p><a href="{escape(str(artifact_href))}" target="_blank" rel="noreferrer">Open Artifact / 打开工件</a></p>')
            cards.append(
                f"""
                <article class="timeline-entry">
                  <div class="timeline-entry__marker"></div>
                  <div class="result-card optimize-history-card">
                    <p class="eyebrow">{escape(self._optimize_result_kind_label(str(record.get('artifact_kind', 'result'))))}</p>
                    <h3>{escape(title)}</h3>
                    {''.join(body_lines)}
                  </div>
                </article>
                """
            )
        return f"""
        <section class="panel optimize-history-panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Optimization Timeline</p>
              <h2>Optimization Timeline / 优化时间线</h2>
            </div>
          </div>
          <div class="timeline-stack">
            {''.join(cards)}
          </div>
        </section>
        """

    def _render_optimize_create_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        flash_html = self._render_flash_messages("optimize")
        factor_form_html = self._render_factor_backtest_form(view="optimize")
        body = f"""
          {flash_html}
          <section class="module" id="module-optimize-create">
            <div class="module__header">
              <p class="eyebrow">Module 03</p>
              <h2>实验创建</h2>
              <p class="hero__copy">这里只保留实验创建表单，避免优化页再次变成工作台大杂烩。</p>
            </div>
            {factor_form_html}
          </section>
        """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title="Strategy Optimize / 策略优化",
                eyebrow="Strategy Optimize",
                description="创建新的因子回测或实验，不展示历史与结果摘要。",
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _render_optimize_history_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        flash_html = self._render_flash_messages("optimize")
        records = self._optimize_history_records()
        body = f"""
          {flash_html}
          {self._render_optimize_history_cards(records)}
        """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title="Strategy Optimize / 策略优化",
                eyebrow="Strategy Optimize",
                description="只看最近的策略实验和套件结果，按时间顺序浏览卡片。",
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _render_optimize_detail_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        flash_html = self._render_flash_messages("optimize")
        records = self._optimize_history_records()
        selected_record = self._optimize_resolve_selected_record(records, query.get("artifact", [None])[0])
        if selected_record is None:
            body = f"""
              {flash_html}
              <section class="panel panel--empty">
                <h2>Experiment Detail / 实验详情</h2>
                <p>先运行一次实验或选择一个历史工件后，这里才会显示详情。</p>
              </section>
            """
        else:
            payload = self._optimize_detail_payload(selected_record)
            title = str(payload.get("summary", {}).get("subject_name") or selected_record.get("title") or "Experiment Detail / 实验详情")
            artifact_href = selected_record.get("artifact_href")
            result_panel = self._render_strategy_lab_workspace(
                payload,
                title=title,
                eyebrow="Selected Experiment",
                artifact_href=artifact_href,
            )
            body = f"""
              {flash_html}
              {result_panel}
              {self._render_optimize_candidate_panel(payload)}
            """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title="Strategy Optimize / 策略优化",
                eyebrow="Strategy Optimize",
                description="查看单个实验的完整结果和推荐策略候选。",
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _render_optimize_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        if subview == "history":
            return self._render_optimize_history_page(query, primary_view=primary_view, subview=subview)
        if subview == "detail":
            return self._render_optimize_detail_page(query, primary_view=primary_view, subview=subview)
        return self._render_optimize_create_page(query, primary_view=primary_view, subview=subview)

    def _render_morning_briefing(self) -> str:
        system_status = self._build_system_status()
        display_job = system_status.get("display_job") if isinstance(system_status.get("display_job"), dict) else None
        latest_research = self.state.last_factor_backtest_result if isinstance(self.state.last_factor_backtest_result, dict) else {}
        latest_runtime = self.state.last_run_results[-1] if self.state.last_run_results else self._latest_paper_run_result() or {}
        latest_research_summary = latest_research.get("summary", {}) if isinstance(latest_research.get("summary"), dict) else {}
        latest_research_scorecard = (
            latest_research.get("attribution", {}).get("scorecard", {})
            if isinstance(latest_research.get("attribution"), dict)
            else {}
        )
        latest_runtime_summary = latest_runtime.get("paper_run_summary", {}) if isinstance(latest_runtime.get("paper_run_summary"), dict) else latest_runtime
        latest_runtime_review = (
            latest_runtime.get("review", {}).get("verdict")
            if isinstance(latest_runtime.get("review"), dict)
            else None
        )
        active_job_label = "N/A"
        if display_job:
            active_job_label = str(display_job.get("kind") or display_job.get("job_kind") or display_job.get("status") or "N/A")
            stage = str(display_job.get("stage") or "").strip()
            if stage:
                active_job_label = f"{active_job_label} / {stage}"
        return f"""
        <section class="summary-strip">
          <div class="summary-strip__header">
            <div>
              <p class="eyebrow">Morning Brief / 今日总览</p>
              <h2>30 秒看完今天情况</h2>
            </div>
            <p class="hero__copy">只保留当前状态、最近研究、最近运行和常用跳转，避免 overview 再次膨胀成缩小版工作台。</p>
          </div>
          <div class="summary-grid">
            {self._summary_tile("System / 当前状态", system_status.get("overall_status", "N/A"), "来自项目健康检查的总状态")}
            {self._summary_tile("Review / 最近审核", system_status.get("latest_review", "N/A"), "最近一次运行的审核结论")}
            {self._summary_tile("Artifacts / 工件", system_status.get("artifact_count", 0), "当前可见的归档数量")}
            {self._summary_tile("Jobs / 当前任务", active_job_label, "最近心跳或最近完成的后台任务")}
            {self._summary_tile("Paper / 模拟盘", system_status.get("paper_account_count", 0), "已注册的本地模拟盘账户数")}
          </div>
        </section>
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Latest Research / 最近研究结果</p>
              <h2>{escape(str(latest_research_summary.get("subject_name", "暂无最近研究结果")))}</h2>
            </div>
            <a class="button button--ghost" href="/?view=workbench">Open Workbench / 打开工作台</a>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Market / 市场", latest_research_summary.get("market", "N/A"), "最近一次实验的市场")}
            {self._summary_tile("Return / 累计收益", latest_research_summary.get("total_return", "N/A"), "实验摘要里的总收益")}
            {self._summary_tile("Decision / 结论", latest_research_scorecard.get("decision", "N/A"), "评分卡给出的建议")}
            {self._summary_tile("Score / 评分", latest_research_scorecard.get("score", "N/A"), "本轮实验综合评分")}
          </div>
          <p class="muted">Window / 窗口: {escape(str(latest_research_summary.get("start_date", "N/A")))} -> {escape(str(latest_research_summary.get("end_date", "N/A")))}</p>
        </section>
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Latest Runtime / 最近运行结果</p>
              <h2>{escape(str(latest_runtime_summary.get("strategy_id", latest_runtime_summary.get("paper_run_summary", {}).get("strategy_id", "暂无最近运行结果"))))}</h2>
            </div>
            <a class="button button--ghost" href="/?view=paper">Open Paper / 打开模拟盘</a>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Market / 市场", latest_runtime.get("market", latest_runtime_summary.get("market", "N/A")), "最近一次运行覆盖的市场")}
            {self._summary_tile("Runtime / 运行模式", latest_runtime.get("effective_runtime_mode", latest_runtime.get("runtime_mode", latest_runtime_summary.get("runtime_mode", "N/A"))), "最近一次运行的语义")}
            {self._summary_tile("Review / 审核", latest_runtime_review or latest_runtime_summary.get("decision", "N/A"), "最近一次运行的审核或记录状态")}
            {self._summary_tile("Trades / 成交", len(latest_runtime.get("paper_trade_records", [])) if isinstance(latest_runtime.get("paper_trade_records"), list) else latest_runtime_summary.get("trade_count", "0"), "最近一次运行里的成交数")}
          </div>
          <p class="muted">Trade Date / 交易日: {escape(str(latest_runtime.get("trade_date", latest_runtime_summary.get("as_of", "N/A"))))}</p>
        </section>
        <section class="panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Quick Actions / 快捷入口</p>
              <h2>跳到常用工作区</h2>
            </div>
          </div>
          <div class="quick-actions">
            <a class="quick-link" href="/?view=workbench">
              <strong>Research Workbench / 研究工作台</strong>
              <span>去做因子实验和回测。</span>
            </a>
            <a class="quick-link" href="/?view=results">
              <strong>Research Results / 研究结果</strong>
              <span>查看统一索引和归档结果。</span>
            </a>
            <a class="quick-link" href="/?view=paper">
              <strong>Local Paper / 模拟盘</strong>
              <span>查看账户、成交和净值。</span>
            </a>
            <a class="quick-link" href="/project/ops">
              <strong>Ops / 运维中心</strong>
              <span>查看后台任务和系统健康。</span>
            </a>
          </div>
        </section>
        """

    def _run_result_ref(self, result: Dict[str, Any]) -> str:
        trade_date = str(result.get("trade_date") or result.get("paper_run_summary", {}).get("as_of") or "").strip()
        market = str(result.get("market") or "").strip()
        strategy_id = str(result.get("strategy_id") or result.get("paper_run_summary", {}).get("strategy_id") or "").strip()
        run_instance_id = str(result.get("run_instance_id") or "").strip()
        return "|".join(part for part in (trade_date, market, strategy_id, run_instance_id or self._run_result_signature(result)) if part)

    def _run_result_signature(self, result: Dict[str, Any]) -> str:
        try:
            payload = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        except TypeError:
            payload = str(result)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def _run_history_records(self) -> List[Dict[str, Any]]:
        return list(reversed(self.state.last_run_results))

    def _resolve_selected_run_result(self, query: Dict[str, List[str]]) -> Optional[Dict[str, Any]]:
        run_ref = str(query.get("run_ref", [""])[0]).strip()
        records = self._run_history_records()
        if run_ref:
            for result in records:
                if self._run_result_ref(result) == run_ref:
                    return result
            return None
        return records[0] if records else None

    def _render_run_history_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        flash_html = self._render_flash_messages("workbench")
        records = self._run_history_records()
        if not records:
            body = f"""
              {flash_html}
              <section class="panel panel--empty">
                <h2>Run History / 运行历史</h2>
                <p>先提交一次策略运行后，这里会按时间顺序列出历史记录。</p>
              </section>
            """
        else:
            cards = []
            for index, result in enumerate(records, start=1):
                paper_summary = result.get("paper_run_summary", {}) if isinstance(result.get("paper_run_summary"), dict) else {}
                run_ref = self._run_result_ref(result)
                trade_count = len(result.get("paper_trade_records", [])) or paper_summary.get("trade_count", 0)
                cards.append(
                    f"""
                    <article class="result-card">
                      <p class="eyebrow">Run {index}</p>
                      <h3>{escape(str(result.get('strategy_id') or paper_summary.get('strategy_id') or 'N/A'))}</h3>
                      <p>Market / 市场: {escape(str(result.get('market', 'N/A')))} | Trade Date / 交易日: {escape(str(result.get('trade_date', paper_summary.get('as_of', 'N/A'))))}</p>
                      <p>Review / 审核: {escape(str(result.get('review', {}).get('verdict', 'N/A')))} | Trades / 成交 {escape(str(trade_count))}</p>
                      <p><a href="{escape(self._view_url('run', query={'subview': 'detail', 'run_ref': run_ref}))}">Open Detail / 打开详情</a></p>
                    </article>
                    """
                )
            body = f"""
              {flash_html}
              <section class="panel">
                <div class="panel__header">
                  <div>
                    <p class="eyebrow">Run History</p>
                    <h2>Run History / 运行历史</h2>
                  </div>
                </div>
                <div class="card-grid">{''.join(cards)}</div>
              </section>
            """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title="Strategy Run / 策略运行",
                eyebrow="Strategy Run",
                description="查看历史运行的时间顺序列表，并进入单个运行详情。",
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _render_run_detail_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        flash_html = self._render_flash_messages("workbench")
        selected_run = self._resolve_selected_run_result(query)
        if selected_run is None:
            body = f"""
              {flash_html}
              <section class="panel panel--empty">
                <h2>Run Detail / 运行详情</h2>
                <p>先执行一次策略运行后，这里会展示选中的信号、交易建议、审核和模拟盘影响。</p>
              </section>
            """
        else:
            signals = selected_run.get("signals", []) if isinstance(selected_run.get("signals"), list) else []
            trade_suggestions = selected_run.get("trade_suggestions", []) if isinstance(selected_run.get("trade_suggestions"), list) else []
            review = selected_run.get("review", {}) if isinstance(selected_run.get("review"), dict) else {}
            paper_account = selected_run.get("paper_account", {}) if isinstance(selected_run.get("paper_account"), dict) else {}
            paper_run_summary = selected_run.get("paper_run_summary", {}) if isinstance(selected_run.get("paper_run_summary"), dict) else {}
            signal_cards = "".join(
                f"""
                <article class="result-card">
                  <h3>{escape(str(signal.get('instrument_id', 'N/A')))}</h3>
                  <p>Score / 评分: {escape(str(signal.get('score', 'N/A')))}</p>
                  <p>Reason / 原因: {escape(str(signal.get('reason', 'N/A')))}</p>
                  <p>Beta / Beta: {escape(str(signal.get('beta', 'N/A')))}</p>
                </article>
                """
                for signal in signals
                if isinstance(signal, dict)
            ) or "<p class='muted'>暂无选中信号。</p>"
            suggestion_cards = "".join(
                f"""
                <article class="result-card">
                  <h3>{escape(str(suggestion.get('instrument_id', 'N/A')))}</h3>
                  <p>Side / 方向: {escape(str(suggestion.get('side', 'N/A')))} | Qty / 数量: {escape(str(suggestion.get('qty', 'N/A')))}</p>
                  <p>Rationale / 理由: {escape(str(suggestion.get('rationale', 'N/A')))}</p>
                </article>
                """
                for suggestion in trade_suggestions
                if isinstance(suggestion, dict)
            ) or "<p class='muted'>暂无交易建议。</p>"
            account_effect = f"""
            <div class="summary-grid">
              {self._summary_tile("Account / 账户", paper_account.get("account_id", "N/A"), "本次运行写入的模拟盘账户")}
              {self._summary_tile("Latest NAV / 最新净值", paper_account.get("latest_nav", paper_run_summary.get("latest_nav", "N/A")), "运行后的模拟盘净值")}
              {self._summary_tile("Cash / 现金", paper_account.get("cash", paper_run_summary.get("cash", "N/A")), "运行后的可用现金")}
              {self._summary_tile("Buying Power / 购买力", paper_account.get("buying_power", paper_run_summary.get("buying_power", "N/A")), "运行后的购买力")}
              {self._summary_tile("Positions / 持仓数", paper_account.get("position_count", paper_run_summary.get("position_count", "N/A")), "运行后的持仓数量")}
              {self._summary_tile("Trades / 成交数", paper_account.get("trade_count", paper_run_summary.get("trade_count", "N/A")), "运行后的成交数量")}
            </div>
            """
            body = f"""
              {flash_html}
              <section class="panel">
                <div class="panel__header">
                  <div>
                    <p class="eyebrow">Run Detail</p>
                    <h2>Run Detail / 运行详情</h2>
                  </div>
                </div>
                <div class="summary-grid">
                  {self._summary_tile("Strategy / 策略", selected_run.get("strategy_id", "N/A"), "选中的策略 ID")}
                  {self._summary_tile("Market / 市场", selected_run.get("market", "N/A"), "选中的市场")}
                  {self._summary_tile("Trade Date / 交易日", selected_run.get("trade_date", paper_run_summary.get("as_of", "N/A")), "本次运行日期")}
                  {self._summary_tile("Review / 审核", review.get("verdict", "N/A"), "运行审核结论")}
                </div>
              </section>
              <section class="panel">
                <div class="panel__header">
                  <div>
                    <p class="eyebrow">Selected Signals</p>
                    <h2>Selected Signals / 选中信号</h2>
                  </div>
                </div>
                <div class="card-grid">{signal_cards}</div>
              </section>
              <section class="panel">
                <div class="panel__header">
                  <div>
                    <p class="eyebrow">Trade Suggestions</p>
                    <h2>Trade Suggestions / 交易建议</h2>
                  </div>
                </div>
                <div class="card-grid">{suggestion_cards}</div>
              </section>
              <section class="panel">
                <div class="panel__header">
                  <div>
                    <p class="eyebrow">Review</p>
                    <h2>Review / 审核</h2>
                  </div>
                </div>
                <p><strong>{escape(str(review.get('verdict', 'N/A')))}</strong></p>
                <p>{escape('；'.join(str(item) for item in review.get('comments', []))) if isinstance(review.get('comments'), list) and review.get('comments') else '暂无审核评论'}</p>
              </section>
              <section class="panel">
                <div class="panel__header">
                  <div>
                    <p class="eyebrow">Simulated Account Effect</p>
                    <h2>Simulated Account Effect / 模拟盘影响</h2>
                  </div>
                </div>
                {account_effect}
              </section>
            """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title="Strategy Run / 策略运行",
                eyebrow="Strategy Run",
                description="查看选中运行的信号、交易建议、审核和模拟盘影响。",
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _render_run_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        if subview == "history":
            return self._render_run_history_page(query, primary_view=primary_view, subview=subview)
        if subview == "detail":
            return self._render_run_detail_page(query, primary_view=primary_view, subview=subview)
        flash_html = self._render_flash_messages("workbench")
        body = f"""
          {flash_html}
          <section class="module" id="module-run-create">
            <div class="module__header">
              <p class="eyebrow">Module 03</p>
              <h2>策略运行</h2>
              <p class="hero__copy">这里只保留策略运行表单，方便快速提交和切换策略预设。</p>
            </div>
            {self._render_strategy_run_form(view=primary_view)}
          </section>
        """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title="Strategy Run / 策略运行",
                eyebrow="Strategy Run",
                description="提交策略运行，不混入历史、默认值或其他工作台内容。",
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _render_workbench_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        flash_html = self._render_flash_messages("workbench")
        strategy_run_html = self._render_strategy_run_form(view="workbench")
        factor_form_html = self._render_factor_backtest_form(view="workbench")
        current_defaults_html = self._render_current_defaults_panel()
        recent_execution_html = self._render_recent_execution_panel()
        page_title = "Strategy Optimize / 策略优化"
        page_eyebrow = "Strategy Optimize"
        page_description = "围绕因子回测和参数实验的优化工作台。"
        body = f"""
          {flash_html}
          <section class="module" id="module-research">
            <div class="module__header">
              <p class="eyebrow">Module 03</p>
              <h2>研究工作台</h2>
              <p class="hero__copy">在这里集中做策略运行、因子回测、默认配置检查和最近执行反馈，不再和 overview 混在一起。</p>
            </div>
            <div class="workbench-grid">
              {strategy_run_html}
              {factor_form_html}
              {current_defaults_html}
              {recent_execution_html}
            </div>
          </section>
        """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title=page_title,
                eyebrow=page_eyebrow,
                description=page_description,
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _render_results_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        flash_html = self._render_flash_messages("results")
        all_records = self._recent_indexed_results(limit=None)
        strategy_state = self._strategy_state_store().load_state()
        result_groups = build_result_center_groups(all_records, strategy_state=strategy_state)
        records = result_groups.get(subview, result_groups["archive"])
        selected_artifact = self._resolve_selected_result_artifact(records, query.get("artifact", [None])[0])
        selected_path = selected_artifact.relative_path if selected_artifact else None
        subview_config = self._result_center_subview_config(subview)
        body = f"""
          {flash_html}
          <section class="panel result-center">
            <div class="panel__header">
              <div>
                <p class="eyebrow">{escape(subview_config["eyebrow"])}</p>
                <h2>{escape(subview_config["section_title"])}</h2>
              </div>
            </div>
            <div class="result-center__summary summary-grid">
              {self._summary_tile("Visible / 可见结果", len(records), subview_config["summary_hint"])}
              {self._summary_tile("Archive / 总归档", len(result_groups["archive"]), "结果中心总索引数量")}
            </div>
            {self._render_result_center_records(records, subview, selected_path)}
          </section>
          <section class="panel">
            <div class="panel__header">
              <div>
                <p class="eyebrow">Result Detail</p>
                <h2>Result Detail / 结果详情</h2>
              </div>
            </div>
            {self._render_selected_artifact(selected_artifact)}
          </section>
        """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title=subview_config["page_title"],
                eyebrow=subview_config["eyebrow"],
                description=subview_config["description"],
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _result_center_subview_config(self, subview: str) -> Dict[str, str]:
        configs = {
            "champions": {
                "page_title": "Champion / 冠军",
                "eyebrow": "Champion Results",
                "section_title": "Champion Results / 冠军结果中心",
                "description": "只展示当前官方 champion，或者最新 KEEP 结果晋升出的冠军结果。",
                "summary_hint": "当前子页只展示 champion 分组。",
            },
            "challengers": {
                "page_title": "Challenger / 挑战者",
                "eyebrow": "Challenger Results",
                "section_title": "Challenger Results / 挑战者结果中心",
                "description": "只展示最新 REVIEW 候选，或者策略状态里显式指定的 challenger。",
                "summary_hint": "当前子页只展示 challenger 分组。",
            },
            "drops": {
                "page_title": "Drop / 淘汰",
                "eyebrow": "Drop Results",
                "section_title": "Drop Results / 淘汰结果中心",
                "description": "只展示 decision 为 DROP 的结果。",
                "summary_hint": "当前子页只展示 DROP 分组。",
            },
            "archive": {
                "page_title": "Archive / 归档",
                "eyebrow": "Archive Results",
                "section_title": "Archive Results / 全量结果归档",
                "description": "只展示全部结果归档，不再按 research/runtime 混合分栏。",
                "summary_hint": "当前子页展示全部归档记录。",
            },
        }
        return configs.get(subview, configs["archive"])

    def _render_result_center_records(self, records: List[Dict[str, Any]], subview: str, selected_path: Optional[str]) -> str:
        if not records:
            return """
            <section class="panel panel--empty">
              <h2>当前分组没有匹配结果</h2>
              <p>这个子页暂时没有可展示的结果，请检查策略状态或结果索引。</p>
            </section>
            """
        rows_html = []
        for row in records:
            summary = row.get("summary", {}) if isinstance(row.get("summary"), dict) else {}
            artifacts = row.get("artifacts", {}) if isinstance(row.get("artifacts"), dict) else {}
            json_path = self._artifact_query_path(str(artifacts.get("json", "") or ""))
            href = self._view_url("results", query={"subview": subview, "artifact": json_path}) if json_path else self._view_url("results", query={"subview": subview})
            selected_class = " result-row--active" if json_path and json_path == selected_path else ""
            rows_html.append(
                f"""
                <a class="result-row{selected_class}" href="{href}">
                  <span class="result-row__subject">{escape(str(summary.get('subject_name') or summary.get('subject_id') or row.get('result_id', 'N/A')))}</span>
                  <span>{escape(str(summary.get('result_type') or row.get('artifact_kind', 'N/A')))}</span>
                  <span>{escape(str(row.get('market', summary.get('market', 'N/A'))))}</span>
                  <span>{escape(str(summary.get('decision', 'N/A')))}</span>
                  <span>{escape(str(summary.get('score', 'N/A')))}</span>
                  <span>{escape(str(summary.get('return', 'N/A')))}</span>
                  <span>{escape(str(row.get('sort_date') or summary.get('end_date') or summary.get('trade_date') or 'N/A'))}</span>
                </a>
                """
            )
        return f"""
        <section class="panel result-center__list">
          <div class="result-group">
            <div class="result-group__header">
              <div>
                <p class="eyebrow">{escape(subview.title())}</p>
                <h3>{escape(self._result_center_subview_config(subview)["section_title"])}</h3>
              </div>
              <p class="muted">{escape(self._result_center_subview_config(subview)["summary_hint"])}</p>
            </div>
            <div class="result-table" role="table" aria-label="{escape(self._result_center_subview_config(subview)['section_title'])}">
              <div class="result-table__head" role="row">
                <span>Subject / 对象</span>
                <span>Type / 类型</span>
                <span>Market / 市场</span>
                <span>Decision / 结论</span>
                <span>Score / 评分</span>
                <span>Return / 收益</span>
                <span>Date / 日期</span>
              </div>
              <div class="result-table__body">{''.join(rows_html)}</div>
            </div>
          </div>
        </section>
        """

    def _result_filters_from_query(self, query: Dict[str, List[str]]) -> Dict[str, str]:
        return {
            "result_group": query.get("result_group", ["all"])[0].strip().lower() or "all",
            "result_type": query.get("result_type", ["all"])[0].strip() or "all",
            "market": query.get("market", ["all"])[0].strip().upper() or "all",
            "recent_window": query.get("recent_window", ["all"])[0].strip().lower() or "all",
            "date_from": query.get("date_from", [""])[0].strip(),
            "date_to": query.get("date_to", [""])[0].strip(),
        }

    def _result_group_for_row(self, row: Dict[str, Any]) -> str:
        return "runtime" if str(row.get("artifact_kind")) == "local_paper_run" else "research"

    def _result_type_for_row(self, row: Dict[str, Any]) -> str:
        summary = row.get("summary", {}) if isinstance(row.get("summary"), dict) else {}
        return str(summary.get("result_type") or row.get("artifact_kind") or "unknown")

    def _result_date_string(self, row: Dict[str, Any]) -> str:
        summary = row.get("summary", {}) if isinstance(row.get("summary"), dict) else {}
        for candidate in (
            row.get("sort_date"),
            summary.get("as_of"),
            summary.get("end_date"),
            summary.get("trade_date"),
        ):
            value = str(candidate or "").strip()
            if value:
                return value
        return ""

    def _parse_result_date(self, raw_value: str) -> Optional[date]:
        value = str(raw_value or "").strip()
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).date()
        except ValueError:
            pass
        if len(value) >= 10:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
        return None

    def _filter_result_records(self, records: List[Dict[str, Any]], filters: Dict[str, str]) -> List[Dict[str, Any]]:
        filtered = list(records)
        if filters["result_group"] in {"research", "runtime"}:
            filtered = [row for row in filtered if self._result_group_for_row(row) == filters["result_group"]]
        if filters["result_type"] != "all":
            filtered = [row for row in filtered if self._result_type_for_row(row) == filters["result_type"]]
        if filters["market"] != "ALL":
            filtered = [row for row in filtered if str(row.get("market", "")).upper() == filters["market"]]

        dated_rows = [(row, self._parse_result_date(self._result_date_string(row))) for row in filtered]
        recent_window = filters["recent_window"]
        if recent_window.endswith("d") and recent_window[:-1].isdigit():
            latest_seen = max((parsed for _, parsed in dated_rows if parsed is not None), default=None)
            if latest_seen is not None:
                window_days = int(recent_window[:-1])
                threshold = latest_seen - timedelta(days=window_days)
                filtered = [row for row, parsed in dated_rows if parsed is None or parsed >= threshold]
                dated_rows = [(row, self._parse_result_date(self._result_date_string(row))) for row in filtered]

        date_from = self._parse_result_date(filters["date_from"])
        if date_from is not None:
            filtered = [row for row, parsed in dated_rows if parsed is None or parsed >= date_from]
            dated_rows = [(row, self._parse_result_date(self._result_date_string(row))) for row in filtered]
        date_to = self._parse_result_date(filters["date_to"])
        if date_to is not None:
            filtered = [row for row, parsed in dated_rows if parsed is None or parsed <= date_to]
        return filtered

    def _artifact_entry_from_relative_path(self, relative_path: str) -> Optional[ArtifactEntry]:
        normalized_path = self._artifact_query_path(relative_path)
        safe_path = self._safe_artifact_path(normalized_path)
        if safe_path is None or not safe_path.exists():
            return None
        try:
            summary = read_json_artifact(ARTIFACT_ROOT, normalized_path)
        except Exception:
            return None
        if not isinstance(summary, dict):
            return None
        return ArtifactEntry(
            relative_path=normalized_path,
            display_name=safe_path.name,
            mtime=safe_path.stat().st_mtime,
            summary=summary,
        )

    def _resolve_selected_result_artifact(self, records: List[Dict[str, Any]], artifact_query: Optional[str]) -> Optional[ArtifactEntry]:
        requested_path = self._artifact_query_path(unquote(artifact_query)) if artifact_query else None
        candidate_paths: List[str] = []
        if requested_path:
            candidate_paths.append(requested_path)
        for row in records:
            artifacts = row.get("artifacts", {}) if isinstance(row.get("artifacts"), dict) else {}
            json_path = str(artifacts.get("json", "") or "").strip()
            if json_path and json_path not in candidate_paths:
                candidate_paths.append(json_path)
        for path in candidate_paths:
            entry = self._artifact_entry_from_relative_path(path)
            if entry is not None:
                return entry
            if requested_path and path == requested_path:
                return None
        return None

    def _result_query_params(self, filters: Dict[str, str], artifact: Optional[str] = None) -> Dict[str, str]:
        params = {
            "result_group": filters["result_group"] if filters["result_group"] != "all" else "",
            "result_type": filters["result_type"] if filters["result_type"] != "all" else "",
            "market": filters["market"] if filters["market"] != "ALL" else "",
            "recent_window": filters["recent_window"] if filters["recent_window"] != "all" else "",
            "date_from": filters["date_from"],
            "date_to": filters["date_to"],
        }
        if artifact:
            params["artifact"] = artifact
        return params

    def _render_results_filter_bar(self, filters: Dict[str, str], records: List[Dict[str, Any]]) -> str:
        result_types = sorted({self._result_type_for_row(row) for row in records if self._result_type_for_row(row)})
        result_type_options = ['<option value="all">All / 全部</option>'] + [
            f'<option value="{escape(result_type)}"{" selected" if filters["result_type"] == result_type else ""}>{escape(result_type)}</option>'
            for result_type in result_types
        ]
        return f"""
        <section class="panel result-filter-bar">
          <form class="grid-form result-filter-bar__form" method="get" action="/">
            <input type="hidden" name="view" value="results" />
            <label>Result Group / 结果分组
              <select name="result_group">
                <option value="all"{' selected' if filters['result_group'] == 'all' else ''}>All / 全部</option>
                <option value="research"{' selected' if filters['result_group'] == 'research' else ''}>Research / 研究</option>
                <option value="runtime"{' selected' if filters['result_group'] == 'runtime' else ''}>Runtime / 运行</option>
              </select>
            </label>
            <label>Result Type / 结果类型
              <select name="result_type">{''.join(result_type_options)}</select>
            </label>
            <label>Market / 市场
              <select name="market">
                <option value="ALL"{' selected' if filters['market'] == 'ALL' else ''}>All / 全部</option>
                <option value="CN"{' selected' if filters['market'] == 'CN' else ''}>CN</option>
                <option value="US"{' selected' if filters['market'] == 'US' else ''}>US</option>
              </select>
            </label>
            <label>Recent Window / 最近窗口
              <select name="recent_window">
                <option value="all"{' selected' if filters['recent_window'] == 'all' else ''}>All / 全部</option>
                <option value="7d"{' selected' if filters['recent_window'] == '7d' else ''}>7d</option>
                <option value="30d"{' selected' if filters['recent_window'] == '30d' else ''}>30d</option>
                <option value="90d"{' selected' if filters['recent_window'] == '90d' else ''}>90d</option>
              </select>
            </label>
            <label>Date From / 开始日期
              <input type="date" name="date_from" value="{escape(filters['date_from'])}" />
            </label>
            <label>Date To / 结束日期
              <input type="date" name="date_to" value="{escape(filters['date_to'])}" />
            </label>
            <div class="grid-form__actions result-filter-bar__actions">
              <button class="button button--primary" type="submit">Apply Filters / 应用筛选</button>
            </div>
          </form>
        </section>
        """

    def _render_result_center(self, records: List[Dict[str, Any]], filters: Dict[str, str], selected_path: Optional[str]) -> str:
        if not records:
            return """
            <section class="panel panel--empty">
              <h2>Research Results / 研究结果中心</h2>
              <p>当前筛选条件下没有匹配结果，请调整分组、类型、市场或日期窗口。</p>
            </section>
            """
        research_records = [row for row in records if self._result_group_for_row(row) == "research"]
        runtime_records = [row for row in records if self._result_group_for_row(row) == "runtime"]
        return f"""
        <section class="panel result-center">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Canonical Result Center</p>
              <h2>Indexed Results / 索引结果中心</h2>
            </div>
          </div>
          <div class="result-center__grid">
            {self._render_result_group_table("Research Results / 研究结果中心", "研究输出、回测和策略套件", research_records, filters, selected_path)}
            {self._render_result_group_table("Runtime Results / 运行结果", "模拟盘与运行归档", runtime_records, filters, selected_path)}
          </div>
        </section>
        """

    def _render_result_group_table(
        self,
        title: str,
        description: str,
        records: List[Dict[str, Any]],
        filters: Dict[str, str],
        selected_path: Optional[str],
    ) -> str:
        if not records:
            rows_html = '<div class="result-row result-row--empty"><span class="muted">当前分组没有匹配结果。</span></div>'
        else:
            rendered_rows = []
            for row in records:
                summary = row.get("summary", {}) if isinstance(row.get("summary"), dict) else {}
                artifacts = row.get("artifacts", {}) if isinstance(row.get("artifacts"), dict) else {}
                json_path = self._artifact_query_path(str(artifacts.get("json", "") or ""))
                href = self._view_url("results", query=self._result_query_params(filters, artifact=json_path if json_path else None))
                selected_class = " result-row--active" if json_path and json_path == selected_path else ""
                rendered_rows.append(
                    f"""
                    <a class="result-row{selected_class}" href="{href}">
                      <span class="result-row__subject">{escape(str(summary.get('subject_name') or summary.get('subject_id') or row.get('result_id', 'N/A')))}</span>
                      <span>{escape(self._result_type_for_row(row))}</span>
                      <span>{escape(str(row.get('market', 'N/A')))}</span>
                      <span>{escape(str(summary.get('decision', 'N/A')))}</span>
                      <span>{escape(str(summary.get('score', 'N/A')))}</span>
                      <span>{escape(str(summary.get('return', 'N/A')))}</span>
                      <span>{escape(self._result_date_string(row) or 'N/A')}</span>
                    </a>
                    """
                )
            rows_html = "".join(rendered_rows)
        return f"""
        <section class="result-group">
          <div class="result-group__header">
            <div>
              <p class="eyebrow">{escape(title.split(' / ')[0])}</p>
              <h3>{escape(title)}</h3>
            </div>
            <p class="muted">{escape(description)}</p>
          </div>
          <div class="result-table" role="table" aria-label="{escape(title)}">
            <div class="result-table__head" role="row">
              <span>Subject / 对象</span>
              <span>Type / 类型</span>
              <span>Market / 市场</span>
              <span>Decision / 结论</span>
              <span>Score / 评分</span>
              <span>Return / 收益</span>
              <span>Date / 日期</span>
            </div>
            <div class="result-table__body">{rows_html}</div>
          </div>
        </section>
        """

    def _render_paper_page(self, query: Dict[str, List[str]], primary_view: str, subview: str) -> WebResponse:
        flash_html = self._render_flash_messages("paper")
        local_paper_html = self._render_local_paper_panel(query, view="paper", subview=subview)
        body = f"""
          {flash_html}
          {local_paper_html}
        """
        return self._html_page(
            self._render_page_shell(
                primary_view,
                title="Local Paper / 模拟盘",
                eyebrow="Local Paper",
                description="以账户为中心查看模拟盘结论、状态、风险与执行明细。",
                body=body,
                subview=subview,
                query=query,
            ),
            primary_view=primary_view,
            subview=subview,
        )

    def _render_project_overview(self) -> str:
        latest_result = self.state.last_run_results[-1] if self.state.last_run_results else {}
        latest_research = self.state.last_factor_backtest_result.get("summary", {}) if self.state.last_factor_backtest_result else {}
        latest_research_decision = (
            self.state.last_factor_backtest_result.get("attribution", {}).get("scorecard", {}).get("decision", "N/A")
            if self.state.last_factor_backtest_result
            else "N/A"
        )
        local_account = self.state.last_local_paper_account or LocalPaperLedger().latest_account_overview()
        recent_artifacts = self._recent_artifacts(limit=8)
        latest_review = latest_result.get("review", {}).get("verdict", "N/A") if latest_result else "N/A"
        latest_market = latest_result.get("market", "N/A") if latest_result else "N/A"
        latest_strategy = latest_result.get("strategy_id", "N/A") if latest_result else "N/A"
        paper_trade_count = local_account.get("trade_count", "0") if local_account else "0"
        return f"""
        <section class="summary-strip">
          <div class="summary-strip__header">
            <div>
              <p class="eyebrow">Project Overview</p>
              <h2>项目总览</h2>
            </div>
          </div>
          <div class="summary-grid">
            {self._summary_tile("Latest Market / 最近市场", latest_market, "最近一次策略运行的市场")}
            {self._summary_tile("Latest Strategy / 最近策略", latest_strategy, "最近一次运行的策略 ID")}
            {self._summary_tile("Review Verdict / 审核结果", latest_review, "最近一次运行的 Review 结论")}
            {self._summary_tile("Run Count / 本次会话运行数", len(self.state.last_run_results), "当前页面会话内已保存的运行结果")}
            {self._summary_tile("Paper Trades / 模拟盘成交", paper_trade_count, "本地模拟盘累计成交记录")}
            {self._summary_tile("Research Return / 实验收益", latest_research.get("total_return", "N/A"), "最近一次策略实验的累计收益")}
            {self._summary_tile("Research Decision / 实验结论", latest_research_decision, "最近一次实验的保留或复核方向")}
            {self._summary_tile("Artifacts / 工件数", len(recent_artifacts), "最近归档模块中可见的工件数量")}
          </div>
        </section>
        """

    def _render_status_bar(self, active_page: str) -> str:
        system_status = self._build_system_status()
        latest_result = self.state.last_run_results[-1] if self.state.last_run_results else {}
        local_account = self.state.last_local_paper_account or LocalPaperLedger().latest_account_overview()
        recent_artifacts = self._recent_artifacts(limit=12)
        task_logs = self._load_task_logs()
        return f"""
        <section class="status-strip">
          <div class="status-strip__brand">
            <div>
              <p class="eyebrow">Project Status</p>
              <strong>Stock Quantification</strong>
            </div>
            <span class="status-strip__pill">Server Time / {escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</span>
          </div>
          <div class="status-strip__metrics">
            <span class="status-strip__pill">Status / {escape(str(system_status.get('overall_status', 'N/A')))}</span>
            <span class="status-strip__pill">Review / {escape(str(latest_result.get('review', {}).get('verdict', 'N/A')))}</span>
            <span class="status-strip__pill">Paper / {escape(str(local_account.get('account_id', 'N/A') if local_account else 'N/A'))}</span>
            <span class="status-strip__pill">Artifacts / {len(recent_artifacts)}</span>
            <span class="status-strip__pill">Logs / {len(task_logs)}</span>
          </div>
          {self._render_primary_nav(active_page)}
        </section>
        """

    def _recommended_account_id(self, market_value: str) -> str:
        normalized = str(market_value or "ALL").upper()
        if normalized == "CN":
            return "web-paper-cn"
        if normalized == "US":
            return "web-paper-us"
        return "web-paper-all"

    def _render_interactive_script(self) -> str:
        return """
        <script>
        (function () {
          const recommendationMap = { ALL: "web-paper-all", CN: "web-paper-cn", US: "web-paper-us" };

          function setup(selectId, inputId, hintId) {
            const marketSelect = document.getElementById(selectId);
            const accountInput = document.getElementById(inputId);
            const hint = document.getElementById(hintId);
            if (!marketSelect || !accountInput || !hint) {
              return;
            }

            let lastRecommended = accountInput.dataset.recommendedAccount || recommendationMap[marketSelect.value] || recommendationMap.ALL;

            function updateRecommendation(forceUpdate) {
              const nextRecommended = recommendationMap[marketSelect.value] || recommendationMap.ALL;
              const currentValue = accountInput.value.trim();
              hint.textContent = "推荐账户名: " + nextRecommended;
              if (forceUpdate || !currentValue || currentValue === lastRecommended) {
                accountInput.value = nextRecommended;
              }
              accountInput.dataset.recommendedAccount = nextRecommended;
              lastRecommended = nextRecommended;
            }

            updateRecommendation(false);
            marketSelect.addEventListener("change", function () {
              updateRecommendation(false);
            });
          }

          function updateJobPanels(activeJob) {
            const panels = document.querySelectorAll("[data-job-progress-panel]");
            panels.forEach(function (panel) {
              const kindNode = panel.querySelector("[data-job-kind]");
              const stageNode = panel.querySelector("[data-job-stage]");
              const startedNode = panel.querySelector("[data-job-started]");
              const fillNode = panel.querySelector("[data-job-progress-fill]");
              const labelNode = panel.querySelector("[data-job-progress-label]");
              const detailNode = panel.querySelector("[data-job-detail]");
              if (!kindNode || !stageNode || !startedNode || !fillNode || !labelNode || !detailNode) {
                return;
              }
              if (activeJob) {
                const progress = Number(
                  activeJob.progress_pct != null
                    ? activeJob.progress_pct
                    : ((activeJob.status && activeJob.status !== "RUNNING") ? 100 : 0)
                );
                if ((activeJob.status || "RUNNING") === "RUNNING") {
                  panel.classList.add("job-progress--active");
                } else {
                  panel.classList.remove("job-progress--active");
                }
                kindNode.textContent = activeJob.kind || "RUNNING";
                stageNode.textContent = activeJob.stage || activeJob.status || "RUNNING";
                startedNode.textContent = activeJob.started_at || activeJob.finished_at || "运行中";
                fillNode.style.width = progress + "%";
                labelNode.textContent = progress + "%";
                detailNode.textContent = activeJob.detail || "后台任务运行中。";
              } else {
                panel.classList.remove("job-progress--active");
                kindNode.textContent = "N/A";
                stageNode.textContent = "IDLE";
                startedNode.textContent = "未运行";
                fillNode.style.width = "0%";
                labelNode.textContent = "0%";
                detailNode.textContent = "当前没有运行中的后台任务。";
              }
            });
          }

          function pollJobStatus() {
            return fetch("/api/project/status", { headers: { "Accept": "application/json" } })
              .then(function (response) { return response.json(); })
              .then(function (payload) {
                updateJobPanels(payload.display_job || payload.active_job || null);
                return payload;
              })
              .catch(function () {
                return null;
              });
          }

          function syncSymbolPicker(picker) {
            const hiddenInput = picker.querySelector("[data-symbol-hidden]");
            const summaryNode = picker.querySelector("[data-symbol-summary]");
            const selected = Array.from(picker._selectedSymbols || []);
            if (hiddenInput) {
              hiddenInput.value = selected.join(",");
            }
            if (summaryNode) {
              summaryNode.textContent = selected.length
                ? ("已选 " + selected.length + " 只: " + selected.slice(0, 8).join("、"))
                : "留空表示全市场";
            }
          }

          function renderSelectedSymbols(picker) {
            const container = picker.querySelector("[data-symbol-selected]");
            const nameMap = picker._selectedNames || new Map();
            const selected = Array.from(picker._selectedSymbols || []);
            if (!container) {
              return;
            }
            if (!selected.length) {
              container.innerHTML = '<span class="muted">当前未限制股票池，默认跑全市场。</span>';
              return;
            }
            container.innerHTML = selected.map(function (symbol) {
              const name = nameMap.get(symbol) || "已选标的";
              return '<button class="symbol-chip" type="button" data-symbol-remove value="' + symbol + '"><span class="symbol-chip__main">' + symbol + '</span><small>' + name + '</small><span class="symbol-chip__action">移除</span></button>';
            }).join("");
            container.querySelectorAll("[data-symbol-remove]").forEach(function (button) {
              button.addEventListener("click", function () {
                picker._selectedSymbols.delete(button.value);
                syncSymbolPicker(picker);
                renderSelectedSymbols(picker);
                fetchSymbolResults(picker);
              });
            });
          }

          function renderSymbolResults(picker, items) {
            const resultsNode = picker.querySelector("[data-symbol-results]");
            const statusNode = picker.querySelector("[data-symbol-status]");
            if (!resultsNode) {
              return;
            }
            if (!items.length) {
              if (statusNode) {
                statusNode.textContent = "没有匹配结果，请换一个代码或名称试试。";
              }
              resultsNode.innerHTML = '<div class="muted">没有匹配结果。</div>';
              return;
            }
            if (statusNode) {
              statusNode.textContent = "已找到 " + items.length + " 只匹配股票，可直接点击结果完成选择。";
            }
            resultsNode.innerHTML = items.map(function (item) {
              const selected = picker._selectedSymbols.has(item.symbol) ? ' symbol-search-result--selected' : '';
              const action = picker._selectedSymbols.has(item.symbol) ? '已选中，点击移除' : '点击添加';
              return '<button class="symbol-search-result' + selected + '" type="button" data-symbol-result value="' + item.symbol + '"><strong>' + item.symbol + '</strong><small>' + (item.name || item.symbol) + '</small><span class="symbol-search-result__action">' + action + '</span></button>';
            }).join("");
            resultsNode.querySelectorAll("[data-symbol-result]").forEach(function (button) {
              button.addEventListener("click", function () {
                const symbol = button.value;
                if (picker._selectedSymbols.has(symbol)) {
                  picker._selectedSymbols.delete(symbol);
                } else {
                  picker._selectedSymbols.add(symbol);
                }
                const nameNode = button.querySelector("small");
                if (nameNode) {
                  picker._selectedNames.set(symbol, nameNode.textContent || symbol);
                }
                syncSymbolPicker(picker);
                renderSelectedSymbols(picker);
                renderSymbolResults(picker, items);
              });
            });
          }

          function fetchSymbolResults(picker) {
            const searchInput = picker.querySelector("[data-symbol-search]");
            const statusNode = picker.querySelector("[data-symbol-status]");
            const keyword = encodeURIComponent(((searchInput && searchInput.value) || "").trim());
            const market = picker.dataset.market || "US";
            if (statusNode) {
              statusNode.textContent = "正在搜索，请稍等...";
            }
            fetch("/api/symbol-search?market=" + market + "&q=" + keyword + "&limit=40", {
              headers: { "Accept": "application/json" }
            })
              .then(function (response) { return response.json(); })
              .then(function (payload) {
                const items = Array.isArray(payload.items) ? payload.items : [];
                items.forEach(function (item) {
                  if (item && item.symbol) {
                    picker._selectedNames.set(item.symbol, item.name || item.symbol);
                  }
                });
                picker._visibleItems = items;
                renderSymbolResults(picker, items);
              })
              .catch(function () {
                const resultsNode = picker.querySelector("[data-symbol-results]");
                if (statusNode) {
                  statusNode.textContent = "搜索失败，请稍后重试。";
                }
                if (resultsNode) {
                  resultsNode.innerHTML = '<div class="muted">搜索服务暂时不可用。</div>';
                }
              });
          }

          function setupSymbolPicker(picker) {
            const searchInput = picker.querySelector("[data-symbol-search]");
            const searchButton = picker.querySelector("[data-symbol-search-button]");
            const selectVisibleButton = picker.querySelector("[data-symbol-select-visible]");
            const clearButton = picker.querySelector("[data-symbol-clear]");
            const hiddenInput = picker.querySelector("[data-symbol-hidden]");
            picker._selectedSymbols = new Set(((hiddenInput && hiddenInput.value) || "").split(",").map(function (item) {
              return item.trim();
            }).filter(Boolean));
            picker._selectedNames = new Map();
            picker._visibleItems = [];
            if (searchInput) {
              let debounceTimer = null;
              searchInput.addEventListener("keydown", function (event) {
                if (event.key === "Enter") {
                  event.preventDefault();
                  fetchSymbolResults(picker);
                }
              });
              searchInput.addEventListener("input", function () {
                if (debounceTimer) {
                  window.clearTimeout(debounceTimer);
                }
                debounceTimer = window.setTimeout(function () {
                  fetchSymbolResults(picker);
                }, 150);
              });
            }
            if (searchButton) {
              searchButton.addEventListener("click", function () {
                fetchSymbolResults(picker);
              });
            }
            if (selectVisibleButton) {
              selectVisibleButton.addEventListener("click", function () {
                (picker._visibleItems || []).forEach(function (item) {
                  if (item && item.symbol) {
                    picker._selectedSymbols.add(item.symbol);
                    picker._selectedNames.set(item.symbol, item.name || item.symbol);
                  }
                });
                syncSymbolPicker(picker);
                renderSelectedSymbols(picker);
                renderSymbolResults(picker, picker._visibleItems || []);
              });
            }
            if (clearButton) {
              clearButton.addEventListener("click", function () {
                picker._selectedSymbols.clear();
                syncSymbolPicker(picker);
                renderSelectedSymbols(picker);
                renderSymbolResults(picker, picker._visibleItems || []);
              });
            }
            syncSymbolPicker(picker);
            renderSelectedSymbols(picker);
            fetchSymbolResults(picker);
          }

          function setupAsyncJobForm(form) {
            if (!form) {
              return;
            }
            let pollingTimer = null;
            form.addEventListener("submit", function (event) {
              event.preventDefault();
              document.querySelectorAll("[data-symbol-picker]").forEach(syncSymbolPicker);
              syncFactorSelection(form);
              updateJobPanels({
                kind: form.dataset.asyncJobForm || "RUNNING",
                stage: "SUBMITTING",
                started_at: "提交中",
                progress_pct: 2,
                detail: "请求已提交，等待后台接管任务。"
              });
              if (pollingTimer) {
                window.clearInterval(pollingTimer);
              }
              pollingTimer = window.setInterval(pollJobStatus, 1000);
              fetch(form.action, {
                method: form.method || "POST",
                body: new FormData(form),
                redirect: "follow"
              }).then(function (response) {
                if (response.redirected) {
                  window.location.href = response.url;
                  return null;
                }
                return response.text().then(function () {
                  window.location.reload();
                  return null;
                });
              }).catch(function () {
                if (pollingTimer) {
                  window.clearInterval(pollingTimer);
                  pollingTimer = null;
                }
                updateJobPanels({
                  kind: form.dataset.asyncJobForm || "RUNNING",
                  stage: "FAILED",
                  started_at: "提交失败",
                  progress_pct: 0,
                  detail: "任务提交失败，请检查后台日志。"
                });
              });
            });
          }

          function syncFactorSelection(form) {
            if (!form) {
              return;
            }
            const payloadInput = form.querySelector("[data-factor-selection-payload]");
            const statusNode = form.querySelector("[data-factor-selection-status]");
            const selected = Array.from(form.querySelectorAll('input[name="factor"]:checked')).map(function (node) {
              return node.value;
            });
            if (payloadInput) {
              payloadInput.value = selected.join(",");
            }
            if (statusNode) {
              statusNode.textContent = selected.length
                ? ("已选 " + selected.length + " 个因子: " + selected.join("、"))
                : "当前没有选中因子，运行前至少保留 1 个。";
            }
          }

          function setupFactorLab(form) {
            if (!form) {
              return;
            }
            const checkboxes = form.querySelectorAll('input[name="factor"]');
            checkboxes.forEach(function (node) {
              node.addEventListener("change", function () {
                syncFactorSelection(form);
              });
            });
            form.addEventListener("submit", function () {
              syncFactorSelection(form);
            });
            syncFactorSelection(form);
          }

          function boot() {
            setup("run-market-select", "run-broker-account-id", "run-broker-account-recommendation");
            setup("config-market-select", "config-broker-account-id", "config-broker-account-recommendation");
            document.querySelectorAll("[data-symbol-picker]").forEach(setupSymbolPicker);
            setupAsyncJobForm(document.getElementById("run-form"));
            setupFactorLab(document.getElementById("factor-backtest-form"));
            pollJobStatus();
            window.setInterval(pollJobStatus, 5000);
          }

          if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", boot);
          } else {
            boot();
          }
        }());
        </script>
        """

    def _load_project_config(self) -> Dict[str, Dict[str, Any]]:
        payload = read_json_artifact(ARTIFACT_ROOT, PROJECT_CONFIG_RELATIVE_PATH)
        merged = deepcopy(DEFAULT_PROJECT_CONFIG)
        if not isinstance(payload, dict):
            return self._sanitize_project_config(merged)
        for section, defaults in merged.items():
            values = payload.get(section)
            if isinstance(values, dict):
                defaults.update(values)
        return self._sanitize_project_config(merged)

    def _sanitize_project_config(self, payload: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        sanitized = deepcopy(DEFAULT_PROJECT_CONFIG)
        run_source = payload.get("run_defaults", {})
        factor_source = payload.get("factor_defaults", {})
        ui_source = payload.get("ui_defaults", {})
        sanitized["run_defaults"].update(
            {
                "market": self._normalize_choice(run_source.get("market"), {"ALL", "CN", "US"}, DEFAULT_PROJECT_CONFIG["run_defaults"]["market"]),
                "runtime_mode": self._normalize_choice(run_source.get("runtime_mode"), {item.value for item in RuntimeMode}, DEFAULT_PROJECT_CONFIG["run_defaults"]["runtime_mode"]),
                "execution_mode": self._normalize_choice(run_source.get("execution_mode"), {item.value for item in ExecutionMode}, DEFAULT_PROJECT_CONFIG["run_defaults"]["execution_mode"]),
                "broker": self._normalize_choice(run_source.get("broker"), {"NONE", "LOCAL_PAPER"}, DEFAULT_PROJECT_CONFIG["run_defaults"]["broker"]),
                "cash": self._normalize_decimal_string(run_source.get("cash"), DEFAULT_PROJECT_CONFIG["run_defaults"]["cash"], minimum=Decimal("0.0001")),
                "broker_account_id": str(run_source.get("broker_account_id") or DEFAULT_PROJECT_CONFIG["run_defaults"]["broker_account_id"]).strip() or DEFAULT_PROJECT_CONFIG["run_defaults"]["broker_account_id"],
                "top_n": self._normalize_int_string(run_source.get("top_n"), DEFAULT_PROJECT_CONFIG["run_defaults"]["top_n"], minimum=1),
                "detail_limit": self._normalize_int_string(run_source.get("detail_limit"), DEFAULT_PROJECT_CONFIG["run_defaults"]["detail_limit"], minimum=1),
                "history_limit": self._normalize_int_string(run_source.get("history_limit"), DEFAULT_PROJECT_CONFIG["run_defaults"]["history_limit"], minimum=1),
                "beta_window": self._normalize_int_string(run_source.get("beta_window"), DEFAULT_PROJECT_CONFIG["run_defaults"]["beta_window"], minimum=1),
                "forward_days": self._normalize_int_string(run_source.get("forward_days"), DEFAULT_PROJECT_CONFIG["run_defaults"]["forward_days"], minimum=0),
                "as_of_date": self._normalize_optional_date_string(run_source.get("as_of_date"), DEFAULT_PROJECT_CONFIG["run_defaults"]["as_of_date"]),
                "symbols_cn": str(run_source.get("symbols_cn") or "").strip(),
                "symbols_us": str(run_source.get("symbols_us") or "").strip(),
                "route_orders": self._normalize_bool_value(run_source.get("route_orders"), DEFAULT_PROJECT_CONFIG["run_defaults"]["route_orders"]),
            }
        )
        sanitized["factor_defaults"].update(
            {
                "factor_market": self._normalize_choice(factor_source.get("factor_market"), {"CN", "US"}, DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_market"]),
                "factor_start_date": self._normalize_date_string(factor_source.get("factor_start_date"), DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_start_date"]),
                "factor_end_date": self._normalize_date_string(factor_source.get("factor_end_date"), DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_end_date"]),
                "factor_holding_sessions": self._normalize_int_string(factor_source.get("factor_holding_sessions"), DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_holding_sessions"], minimum=1),
                "factor_top_n": self._normalize_int_string(factor_source.get("factor_top_n"), DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_top_n"], minimum=1),
                "factor_detail_limit": self._normalize_int_string(factor_source.get("factor_detail_limit"), DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_detail_limit"], minimum=1),
                "factor_history_limit": self._normalize_int_string(factor_source.get("factor_history_limit"), DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_history_limit"], minimum=1),
                "factor_initial_cash": self._normalize_decimal_string(factor_source.get("factor_initial_cash"), DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_initial_cash"], minimum=Decimal("0.0001")),
                "factor_turnover_cap": self._normalize_decimal_string(factor_source.get("factor_turnover_cap"), DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_turnover_cap"], minimum=Decimal("0")),
                "factor_rebalance_buffer": self._normalize_decimal_string(factor_source.get("factor_rebalance_buffer"), DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_rebalance_buffer"], minimum=Decimal("0")),
            }
        )
        if sanitized["factor_defaults"]["factor_start_date"] > sanitized["factor_defaults"]["factor_end_date"]:
            sanitized["factor_defaults"]["factor_start_date"] = DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_start_date"]
            sanitized["factor_defaults"]["factor_end_date"] = DEFAULT_PROJECT_CONFIG["factor_defaults"]["factor_end_date"]
        sanitized["ui_defaults"].update(
            {
                "paper_account_id": str(ui_source.get("paper_account_id") or DEFAULT_PROJECT_CONFIG["ui_defaults"]["paper_account_id"]).strip() or DEFAULT_PROJECT_CONFIG["ui_defaults"]["paper_account_id"],
                "paper_start_date": self._normalize_optional_date_string(ui_source.get("paper_start_date"), DEFAULT_PROJECT_CONFIG["ui_defaults"]["paper_start_date"]),
                "paper_end_date": self._normalize_optional_date_string(ui_source.get("paper_end_date"), DEFAULT_PROJECT_CONFIG["ui_defaults"]["paper_end_date"]),
                "paper_recent_trade_limit": self._normalize_int_string(ui_source.get("paper_recent_trade_limit"), DEFAULT_PROJECT_CONFIG["ui_defaults"]["paper_recent_trade_limit"], minimum=1),
            }
        )
        if (
            sanitized["ui_defaults"]["paper_start_date"]
            and sanitized["ui_defaults"]["paper_end_date"]
            and sanitized["ui_defaults"]["paper_start_date"] > sanitized["ui_defaults"]["paper_end_date"]
        ):
            sanitized["ui_defaults"]["paper_start_date"] = DEFAULT_PROJECT_CONFIG["ui_defaults"]["paper_start_date"]
            sanitized["ui_defaults"]["paper_end_date"] = DEFAULT_PROJECT_CONFIG["ui_defaults"]["paper_end_date"]
        return sanitized

    def _normalize_bool_value(self, raw_value: Any, default: bool) -> bool:
        if isinstance(raw_value, bool):
            return raw_value
        if raw_value is None:
            return default
        if isinstance(raw_value, (int, float)):
            return bool(raw_value)
        normalized = str(raw_value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        return default

    def _parse_int_field(self, raw_value: Any, field_label: str, minimum: Optional[int] = None) -> int:
        text = str(raw_value).strip()
        try:
            value = int(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_label} 需要是整数。") from exc
        if minimum is not None and value < minimum:
            comparator = "不小于"
            raise ValueError(f"{field_label} 需要{comparator} {minimum}。")
        return value

    def _parse_decimal_field(self, raw_value: Any, field_label: str, minimum: Optional[Decimal] = None) -> Decimal:
        text = str(raw_value).strip()
        try:
            value = Decimal(text)
        except (TypeError, InvalidOperation) as exc:
            raise ValueError(f"{field_label} 需要是数字。") from exc
        if minimum is not None and value < minimum:
            raise ValueError(f"{field_label} 不能小于 {minimum}。")
        return value

    def _parse_required_date_field(self, raw_value: Any, field_label: str) -> date:
        text = str(raw_value).strip()
        if not text:
            raise ValueError(f"{field_label} 不能为空。")
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field_label} 需要使用 YYYY-MM-DD 格式。") from exc

    def _parse_optional_date_field(self, raw_value: Any, field_label: str) -> Optional[date]:
        text = str(raw_value).strip()
        if not text:
            return None
        return self._parse_required_date_field(text, field_label)

    def _normalize_choice(self, raw_value: Any, allowed: set[str], fallback: str) -> str:
        text = str(raw_value or "").strip().upper()
        return text if text in allowed else fallback

    def _normalize_int_string(self, raw_value: Any, fallback: str, minimum: Optional[int] = None) -> str:
        try:
            return str(self._parse_int_field(raw_value, "配置项", minimum=minimum))
        except ValueError:
            return str(fallback)

    def _normalize_decimal_string(self, raw_value: Any, fallback: str, minimum: Optional[Decimal] = None) -> str:
        try:
            return self._stringify_decimal(self._parse_decimal_field(raw_value, "配置项", minimum=minimum))
        except ValueError:
            return str(fallback)

    def _normalize_date_string(self, raw_value: Any, fallback: str) -> str:
        try:
            return self._stringify_date(self._parse_required_date_field(raw_value, "配置项日期"))
        except ValueError:
            return str(fallback)

    def _normalize_optional_date_string(self, raw_value: Any, fallback: str) -> str:
        try:
            return self._stringify_optional_date(self._parse_optional_date_field(raw_value, "配置项日期"))
        except ValueError:
            return str(fallback)

    def _stringify_decimal(self, value: Decimal) -> str:
        return format(value.normalize(), "f") if value != value.to_integral() else format(value.quantize(Decimal("1")), "f")

    def _stringify_date(self, value: date) -> str:
        return value.isoformat()

    def _stringify_optional_date(self, value: Optional[date]) -> str:
        return value.isoformat() if value is not None else ""

    def _save_project_config(self, payload: Dict[str, Dict[str, Any]]) -> str:
        return write_json_artifact(ARTIFACT_ROOT, PROJECT_CONFIG_RELATIVE_PATH, payload)

    def _load_task_logs(self) -> List[Dict[str, Any]]:
        payload = read_json_artifact(ARTIFACT_ROOT, TASK_LOG_RELATIVE_PATH)
        if not isinstance(payload, dict):
            return []
        rows = payload.get("entries", [])
        return rows if isinstance(rows, list) else []

    def _append_task_log(
        self,
        category: str,
        action: str,
        status: str,
        detail: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        entries = self._load_task_logs()
        entries.append(
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "category": category,
                "action": action,
                "status": status,
                "detail": detail,
                "metadata": metadata or {},
            }
        )
        write_json_artifact(ARTIFACT_ROOT, TASK_LOG_RELATIVE_PATH, {"entries": entries[-200:]})
        self._ops_store().append_event(category=category, action=action, status=status, detail=detail, metadata=metadata)

    def _ops_store(self) -> ProjectOpsStore:
        return ProjectOpsStore(ARTIFACT_ROOT)

    def _build_system_status(self) -> Dict[str, Any]:
        ops_state = self._ops_store().load_state()
        latest_result = self.state.last_run_results[-1] if self.state.last_run_results else {}
        latest_review = str(latest_result.get("review", {}).get("verdict", "N/A"))
        recent_artifacts = self._recent_artifacts(limit=24)
        task_logs = self._load_task_logs()
        local_paper_accounts = LocalPaperLedger().list_accounts()
        broker_credentials_ready = bool(
            os.getenv("ALPACA_PAPER_KEY_ID")
            or os.getenv("APCA_API_KEY_ID")
        ) and bool(
            os.getenv("ALPACA_PAPER_SECRET_KEY")
            or os.getenv("APCA_API_SECRET_KEY")
        )
        storage_ready = ARTIFACT_ROOT.exists() and os.access(ARTIFACT_ROOT, os.W_OK)
        web_heartbeat = ops_state.get("heartbeats", {}).get("web")
        components = [
            {
                "name": "artifact_storage",
                "status": "UP" if storage_ready else "DOWN",
                "detail": "artifact 目录可写" if storage_ready else "artifact 目录不存在或不可写",
            },
            {
                "name": "web_heartbeat",
                "status": "UP" if web_heartbeat else "WARN",
                "detail": f"最近心跳 {web_heartbeat}" if web_heartbeat else "还没有写入 web 心跳",
            },
            {
                "name": "broker_credentials",
                "status": "UP" if broker_credentials_ready else "WARN",
                "detail": "Alpaca paper 凭证已配置" if broker_credentials_ready else "未检测到 Alpaca paper 凭证，仅可跑本地模式",
            },
            {
                "name": "task_logs",
                "status": "UP",
                "detail": f"已持久化 {len(task_logs)} 条任务日志",
            },
            {
                "name": "local_paper",
                "status": "UP" if local_paper_accounts else "WARN",
                "detail": f"本地模拟盘账户 {len(local_paper_accounts)} 个",
            },
            {
                "name": "review_verdict",
                "status": "UP" if latest_review in {"PASS", "N/A"} else "WARN",
                "detail": f"最近一次审核结论 {latest_review}",
            },
        ]
        overall_status = "READY"
        if any(component["status"] == "DOWN" for component in components):
            overall_status = "DOWN"
        elif any(component["status"] == "WARN" for component in components):
            overall_status = "WARN"
        active_job = ops_state.get("active_job")
        recent_job = None
        job_history = list(ops_state.get("job_history", []))
        if job_history:
            recent_job = job_history[-1]
        return {
            "checked_at": datetime.utcnow().isoformat(timespec="seconds"),
            "overall_status": overall_status,
            "artifact_count": len(recent_artifacts),
            "task_log_count": len(task_logs),
            "paper_account_count": len(local_paper_accounts),
            "broker_credentials_ready": broker_credentials_ready,
            "latest_review": latest_review,
            "active_job": active_job,
            "recent_job": recent_job,
            "display_job": active_job or recent_job,
            "job_history": job_history,
            "audit_events": list(ops_state.get("audit_events", [])),
            "components": components,
        }

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

    def _selected_factor_overrides(
        self,
        market: Market,
        selected_factors: Iterable[str],
        factor_tilts: Optional[Dict[str, Decimal]] = None,
    ) -> Dict[str, Decimal]:
        base_weights = self._baseline_alpha_weights(market)
        available = [factor_name for factor_name in selected_factors if factor_name in base_weights]
        if not available:
            raise ValueError("至少选择一个当前市场可用的因子")
        total_abs = sum(abs(weight) for weight in base_weights.values())
        adjusted_weights: Dict[str, Decimal] = {}
        for factor_name in available:
            tilt = max(Decimal("0"), (factor_tilts or {}).get(factor_name, Decimal("1")))
            adjusted_weights[factor_name] = (base_weights[factor_name] * tilt).quantize(Decimal("0.0001"))
        selected_abs = sum(abs(adjusted_weights[factor_name]) for factor_name in available)
        scale = (total_abs / selected_abs) if selected_abs else Decimal("1")
        overrides = {factor_name: Decimal("0") for factor_name in base_weights}
        for factor_name in available:
            overrides[factor_name] = (adjusted_weights[factor_name] * scale).quantize(Decimal("0.0001"))
        return overrides

    def _infer_selected_factors_from_body(self, market: Market, body: Dict[str, List[str]]) -> List[str]:
        base_weights = self._baseline_alpha_weights(market)
        inferred = []
        for factor_name, base_weight in base_weights.items():
            field_name = f"factor_tilt_{factor_name}"
            if field_name not in body:
                continue
            raw_value = body.get(field_name, [""])[0].strip()
            if not raw_value:
                continue
            try:
                tilt = Decimal(raw_value)
            except Exception:
                continue
            if tilt <= 0:
                continue
            if base_weight == 0:
                continue
            inferred.append(factor_name)
        return inferred

    def _build_custom_preset(
        self,
        market: Market,
        alpha_overrides: Dict[str, Decimal],
        top_n: int,
        turnover_cap: Decimal,
        rebalance_buffer: Decimal,
    ) -> StrategyPreset:
        return StrategyPreset(
            preset_id=f"{market.value.lower()}_strategy_lab",
            market=market,
            display_name=f"{market.value} 自定义策略实验",
            family="自定义研究",
            description="由前端策略实验台生成的自定义多因子组合。",
            alpha_weights=dict(alpha_overrides),
            policy_overrides={
                "turnover_cap": turnover_cap,
                "rebalance_buffer": rebalance_buffer,
            },
            top_n=top_n,
        )

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
        initial_cash: Decimal,
        turnover_cap: Decimal,
        rebalance_buffer: Decimal,
        factor_tilts: Dict[str, Decimal],
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        selected = [factor_name for factor_name in selected_factors if factor_name in self._baseline_alpha_weights(market)]
        alpha_overrides = self._selected_factor_overrides(market, selected, factor_tilts)
        custom_preset = self._build_custom_preset(
            market=market,
            alpha_overrides=alpha_overrides,
            top_n=top_n,
            turnover_cap=turnover_cap,
            rebalance_buffer=rebalance_buffer,
        )
        trading_dates = self._trading_dates_for_market(market, start_date, end_date)
        snapshot_cache: Dict[date, Any] = {}
        daily_reports: List[Dict[str, Any]] = []

        total_dates = max(len(trading_dates), 1)
        for index, trade_date in enumerate(trading_dates, start=1):
            if progress_callback is not None:
                progress_callback(
                    int(10 + ((index - 1) / total_dates) * 80),
                    "RUNNING_BACKTEST",
                    f"正在处理 {trade_date.isoformat()} 的因子样本 ({index}/{total_dates})。",
                    {"current_trade_date": trade_date.isoformat(), "processed_dates": index - 1, "total_dates": total_dates},
                )
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
            if progress_callback is not None:
                progress_callback(
                    int(10 + (index / total_dates) * 80),
                    "BACKTEST_STEP_DONE",
                    f"{trade_date.isoformat()} 样本处理完成。",
                    {"current_trade_date": trade_date.isoformat(), "processed_dates": index, "total_dates": total_dates},
                )

        if not daily_reports:
            raise ValueError("当前参数下没有可用的回测结果")

        if progress_callback is not None:
            progress_callback(
                76,
                "ROLLING_BACKTEST",
                "正在执行组合级滚动回测、费用统计和净值归因。",
                {"market": market.value, "selected_factors": selected},
            )
        rolling_report = build_rolling_strategy_backtest_report(
            market=market,
            preset=custom_preset,
            start_date=start_date,
            end_date=end_date,
            detail_limit=detail_limit,
            history_limit=history_limit,
            initial_cash=initial_cash,
        )
        serialized_rolling = serialize_rolling_backtest_report(rolling_report)
        regime_summary = summarize_regimes(rolling_report)
        alpha_mix = summarize_alpha_mix(custom_preset)
        scorecard = build_strategy_scorecard(custom_preset, rolling_report, regime_summary)

        average_return = self._average_decimal(daily_reports, "equal_weight_return")
        average_excess_return = self._average_decimal(daily_reports, "excess_return")
        average_win_rate = self._average_decimal(daily_reports, "win_rate")
        best_day = max(daily_reports, key=lambda row: Decimal(str(row["equal_weight_return"])))
        worst_day = min(daily_reports, key=lambda row: Decimal(str(row["equal_weight_return"])))
        rolling_summary = serialized_rolling["summary"]
        factor_rows = []
        baseline_weights = self._baseline_alpha_weights(market)
        for factor_name in selected:
            factor_rows.append(
                {
                    "factor_name": factor_name,
                    "label": self._factor_label(factor_name),
                    "description": self._factor_description(factor_name),
                    "tilt": str((factor_tilts.get(factor_name, Decimal("1"))).quantize(Decimal("0.1"))),
                    "base_weight": str(baseline_weights.get(factor_name, Decimal("0")).quantize(Decimal("0.0001"))),
                    "effective_weight": str(alpha_overrides.get(factor_name, Decimal("0")).quantize(Decimal("0.0001"))),
                }
            )
        summary = {
            "artifact_type": "factor_backtest",
            "market": market.value,
            "runtime_mode": "STRATEGY_LAB",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "holding_sessions": holding_sessions,
            "initial_cash": str(initial_cash.quantize(Decimal("0.0001"))),
            "turnover_cap": str(turnover_cap.quantize(Decimal("0.0001"))),
            "rebalance_buffer": str(rebalance_buffer.quantize(Decimal("0.0001"))),
            "selected_factors": selected,
            "selected_factor_labels": [self._factor_label(factor_name) for factor_name in selected],
            "selected_factor_rows": factor_rows,
            "average_return": str(average_return.quantize(Decimal("0.0001"))),
            "average_excess_return": str(average_excess_return.quantize(Decimal("0.0001"))),
            "average_win_rate": str(average_win_rate.quantize(Decimal("0.0001"))),
            "observations": len(daily_reports),
            "best_trade_date": best_day["trade_date"],
            "best_return": best_day["equal_weight_return"],
            "worst_trade_date": worst_day["trade_date"],
            "worst_return": worst_day["equal_weight_return"],
            "total_return": str(rolling_summary["total_return"]),
            "rolling_excess_return": str(rolling_summary.get("excess_return", "0")),
            "benchmark_total_return": str(rolling_summary.get("benchmark_total_return", "0")),
            "annualized_return": str(rolling_summary.get("annualized_return", "0")),
            "annualized_volatility": str(rolling_summary.get("annualized_volatility", "0")),
            "sharpe_ratio": str(rolling_summary.get("sharpe_ratio", "0")),
            "max_drawdown": str(rolling_summary.get("max_drawdown", "0")),
            "average_turnover": str(rolling_summary.get("average_turnover", "0")),
            "fee_drag": str(rolling_summary.get("fee_drag", "0")),
            "pre_fee_return": str(rolling_summary.get("pre_fee_return", "0")),
            "final_nav": str(rolling_summary.get("final_nav", "0")),
        }
        serialized_regimes = serialize_regime_summaries(regime_summary)
        serialized_alpha_mix = serialize_alpha_mix(alpha_mix)
        serialized_scorecard = serialize_strategy_scorecard(scorecard)
        payload = {
            "summary": summary,
            "daily": daily_reports,
            "signal_validation": {
                "daily": daily_reports,
                "average_return": summary["average_return"],
                "average_excess_return": summary["average_excess_return"],
                "average_win_rate": summary["average_win_rate"],
                "observations": summary["observations"],
            },
            "rolling_backtest": serialized_rolling,
            "attribution": {
                "alpha_mix": serialized_alpha_mix,
                "regime_summary": serialized_regimes,
                "scorecard": serialized_scorecard,
                "iteration_notes": self._build_iteration_notes(serialized_scorecard, serialized_regimes, summary),
            },
        }
        summary["decision"] = serialized_scorecard["decision"]
        digest = hashlib.sha1(
            f"{market.value}|{start_date.isoformat()}|{end_date.isoformat()}|{','.join(selected)}".encode("utf-8")
        ).hexdigest()[:10]
        relative_base = f"{end_date.isoformat()}/{market.value.lower()}_factor_backtest_{digest}"
        json_path = write_json_artifact(ARTIFACT_ROOT, f"{relative_base}.json", payload)
        md_lines = [
            f"# {market.value} Strategy Lab",
            "",
            f"- period: {start_date.isoformat()} to {end_date.isoformat()}",
            f"- selected_factors: {'、'.join(self._factor_label(factor_name) for factor_name in selected)}",
            f"- total_return: {summary['total_return']}",
            f"- excess_return: {summary['rolling_excess_return']}",
            f"- sharpe_ratio: {summary['sharpe_ratio']}",
            f"- max_drawdown: {summary['max_drawdown']}",
            f"- signal_average_excess_return: {summary['average_excess_return']}",
            f"- decision: {serialized_scorecard['decision']}",
        ]
        md_path = write_text_artifact(ARTIFACT_ROOT, f"{relative_base}.md", "\n".join(md_lines) + "\n")
        payload["artifacts"] = {"json": json_path, "markdown": md_path}
        return payload

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

    def _json(self, payload: Any, status: int) -> WebResponse:
        return WebResponse(
            status=status,
            content_type="application/json; charset=utf-8",
            body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def _text(self, text: str, status: int, content_type: str) -> WebResponse:
        return WebResponse(status=status, content_type=content_type, body=text.encode("utf-8"))

    def _redirect(self, location: str) -> WebResponse:
        return WebResponse(status=HTTPStatus.SEE_OTHER, content_type="text/plain; charset=utf-8", body=b"", headers={"Location": location})

    def _summary_tile(self, label: str, value: Any, note: Optional[str] = None) -> str:
        return f"""
        <div class="summary-tile">
          <span>{escape(label)}</span>
          <strong>{escape(str(value))}</strong>
          {f'<small>{escape(note)}</small>' if note else ''}
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
