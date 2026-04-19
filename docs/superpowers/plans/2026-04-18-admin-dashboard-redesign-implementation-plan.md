# Admin Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current crowded all-in-one dashboard into a page-owned admin workbench where overview, experiment execution, result browsing, paper account review, logs, operations, and settings each have a single clear responsibility.

**Architecture:** Keep the existing server-rendered dashboard stack, preserve current POST actions and top-level routes, and introduce dedicated page views through shared shell helpers plus `/?view=...` page selection for the dashboard-owned surfaces. Rebuild the UI around one sidebar navigation system, a status-only top strip, and page-specific report layouts implemented inside `src/stock_quantification/web.py`, `templates/dashboard.html`, and `static/styles.css`.

**Tech Stack:** Python 3, `unittest`, `http.server`, server-rendered HTML in `src/stock_quantification/web.py`, shared HTML template in `templates/dashboard.html`, CSS in `static/styles.css`.

---

## File Structure Lock-In

- `src/stock_quantification/web.py`
  - Keep dispatch, POST handlers, and backend integrations.
  - Add page-view resolution for `overview`, `workbench`, `results`, and `paper`.
  - Replace the old `_render_content()` / `_render_module_nav()` contract with focused page render helpers.
  - Add shared shell helpers and page-specific summary/report sections.
- `templates/dashboard.html`
  - Keep the single outer HTML document template.
  - Add only the body-level hook needed by the redesigned CSS.
- `static/styles.css`
  - Replace the old dark glass theme with a light report-first visual system.
  - Add shared classes for sidebar navigation, status strip, summary rows, report panels, tables, filters, and split layouts.
- `tests/test_web.py`
  - Replace outdated dashboard expectations.
  - Add tests for `/?view=...` routing, page headings, navigation labels, workbench ownership, results ownership, and supporting pages.

## Execution Rules

- Preserve the existing top-level routes: `/`, `/project/config`, `/project/logs`, `/project/ops`, `/run`, `/factor-backtest`, `/local-paper/reset`, `/chat`.
- Preserve existing POST behaviors and redirects unless the redirect target is intentionally updated to the new owning page.
- Add dedicated dashboard-owned pages via `/?view=overview`, `/?view=workbench`, `/?view=results`, and `/?view=paper`.
- Keep the top strip status-only. All page navigation must live in the left sidebar.
- Delete the old module-centric composition (`module-run`, `module-paper`, `module-research`, `module-archive`, `module-collab`) instead of preserving it under new styling.
- Keep verification serial for the final test pass.

## Checkpoints

1. **Checkpoint A: Shared shell and view routing** — one sidebar nav, status-only top strip, `view` selection, and page shell helpers are in place.
2. **Checkpoint B: Overview and Research Workbench** — home becomes a briefing page and experiments move into a dedicated workbench page.
3. **Checkpoint C: Results and Paper pages** — results browsing and local paper account review have separate focused layouts.
4. **Checkpoint D: Supporting pages and regression** — logs, operations, settings, and the visual system align with the new architecture; tests pass.

### Task 1: Introduce Dashboard View Routing and the Shared Application Shell

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing tests for sidebar navigation and `view` routing**

```python
    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_renders_sidebar_navigation(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertIn("Overview / 总览", body)
        self.assertIn("Research Workbench / 研究工作台", body)
        self.assertIn("Research Results / 研究结果", body)
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertNotIn("模块导航", body)

    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_supports_workbench_view(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({"view": ["workbench"]})
        body = response.body.decode("utf-8")
        self.assertIn("研究工作台", body)
        self.assertNotIn("双市场量化项目工作台", body)
```

- [ ] **Step 2: Run the targeted routing tests and confirm they fail on the old dashboard**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_web.WebTests.test_home_page_renders_sidebar_navigation \
  tests.test_web.WebTests.test_home_page_supports_workbench_view -v
```

Expected: FAIL because the current dashboard still renders the old module layout and ignores `view=workbench`.

- [ ] **Step 3: Add view resolution and shared shell helpers in `web.py`**

```python
    def _dashboard_view(self, query: Dict[str, List[str]]) -> str:
        raw = query.get("view", ["overview"])[0].strip().lower()
        if raw in {"overview", "workbench", "results", "paper"}:
            return raw
        return "overview"

    def _render_page_shell(self, active_page: str, title: str, eyebrow: str, description: str, body: str) -> str:
        return f"""
        <main class="app-shell">
          {self._render_status_strip(active_page)}
          <div class="app-shell__frame">
            {self._render_sidebar_nav(active_page)}
            <section class="page-shell">
              <header class="page-header">
                <p class="eyebrow">{escape(eyebrow)}</p>
                <h1>{escape(title)}</h1>
                <p class="page-header__copy">{escape(description)}</p>
              </header>
              {self._render_flash_messages()}
              {body}
            </section>
          </div>
          {self._render_interactive_script()}
        </main>
        """
```

- [ ] **Step 4: Replace the old module nav and top nav helpers**

```python
    def _render_sidebar_nav(self, active_page: str) -> str:
        items = [
            ("overview", "/?view=overview", "Overview / 总览", "状态、结论与下一步"),
            ("workbench", "/?view=workbench", "Research Workbench / 研究工作台", "运行、回测与实验配置"),
            ("results", "/?view=results", "Research Results / 研究结果", "浏览与比较产出"),
            ("paper", "/?view=paper", "Local Paper / 模拟盘", "账户、净值、持仓与成交"),
            ("logs", "/project/logs", "Tasks & Logs / 任务与日志", "执行流水"),
            ("ops", "/project/ops", "Operations / 运维中心", "健康、任务与审计"),
            ("config", "/project/config", "Project Settings / 项目设置", "默认值与页面偏好"),
        ]
```

- [ ] **Step 5: Rewire `render_home()` to select a page view**

```python
    def render_home(self, query: Dict[str, List[str]]) -> WebResponse:
        view = self._dashboard_view(query)
        if view == "workbench":
            return self._html_page(self._render_workbench_page(query), title="Research Workbench")
        if view == "results":
            return self._html_page(self._render_results_page(query), title="Research Results")
        if view == "paper":
            return self._html_page(self._render_paper_page(query), title="Local Paper")
        return self._html_page(self._render_overview_page(query), title="Overview")
```

- [ ] **Step 6: Run the routing tests again**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_web.WebTests.test_home_page_renders_sidebar_navigation \
  tests.test_web.WebTests.test_home_page_supports_workbench_view -v
```

Expected: PASS.

- [ ] **Step 7: Commit the shell-routing checkpoint**

```bash
git add src/stock_quantification/web.py tests/test_web.py
git commit -m "feat: add page-owned dashboard shell routing"
```

### Task 2: Replace the Visual System With a Light Report-First Theme

**Files:**
- Modify: `templates/dashboard.html`
- Modify: `static/styles.css`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write a failing test for the new shell hooks**

```python
    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_home_page_uses_report_shell_css_hooks(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({})
        body = response.body.decode("utf-8")
        self.assertIn('class="app-shell"', body)
        self.assertIn('class="page-shell"', body)
        self.assertIn('class="summary-strip"', body)
        self.assertIn('class="side-nav"', body)
```

- [ ] **Step 2: Run the CSS-hook test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_home_page_uses_report_shell_css_hooks -v
```

Expected: FAIL because the old markup still uses `shell`, `hero`, and `workspace`.

- [ ] **Step 3: Add the body hook in `templates/dashboard.html`**

```html
<body class="dashboard-app">
  ${content}
</body>
```

- [ ] **Step 4: Replace the CSS root tokens and shared layout primitives**

```css
:root {
  color-scheme: light;
  --bg: #f4efe6;
  --panel: rgba(255, 251, 245, 0.92);
  --line: #d8ccbb;
  --text: #1f2933;
  --muted: #667085;
  --accent: #87623f;
  --good: #2f6b4f;
  --warn: #9a6a1f;
  --danger: #a63c32;
  --shadow: 0 12px 32px rgba(70, 52, 34, 0.08);
}

body.dashboard-app {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  background: var(--bg);
}
```

- [ ] **Step 5: Add the shared page-shell classes**

```css
.app-shell__frame {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 18px;
}

.side-nav,
.summary-strip,
.report-panel,
.form-panel {
  border: 1px solid var(--line);
  background: var(--panel);
  box-shadow: var(--shadow);
}
```

- [ ] **Step 6: Run the CSS-hook test again**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_home_page_uses_report_shell_css_hooks -v
```

Expected: PASS.

- [ ] **Step 7: Commit the visual-system checkpoint**

```bash
git add templates/dashboard.html static/styles.css tests/test_web.py
git commit -m "feat: add report-first dashboard visual system"
```

### Task 3: Rebuild Overview as a Morning Briefing Page

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing overview tests**

```python
    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_overview_page_renders_briefing_sections(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({"view": ["overview"]})
        body = response.body.decode("utf-8")
        self.assertIn("Morning Brief / 今日总览", body)
        self.assertIn("Latest Research / 最近研究结果", body)
        self.assertIn("Latest Runtime / 最近运行结果", body)
        self.assertIn("Quick Actions / 快捷入口", body)
        self.assertNotIn("策略实验台", body)
```

- [ ] **Step 2: Run the overview test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_overview_page_renders_briefing_sections -v
```

Expected: FAIL because overview still contains the old experiment-heavy content.

- [ ] **Step 3: Add focused overview render helpers**

```python
    def _render_overview_page(self, query: Dict[str, List[str]]) -> str:
        body = "".join(
            [
                self._render_overview_summary_strip(),
                self._render_overview_latest_results(),
                self._render_overview_runtime_summary(),
                self._render_overview_quick_actions(),
            ]
        )
        return self._render_page_shell(
            "overview",
            "总览",
            "Morning Brief",
            "只回答当前状态、最新结论和下一步去哪里，不在首页承载重操作。",
            body,
        )
```

- [ ] **Step 4: Keep overview lightweight by removing heavy modules**

```python
    def _render_overview_quick_actions(self) -> str:
        return """
        <section class="report-panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Quick Actions</p>
              <h2>快捷入口</h2>
            </div>
          </div>
          <div class="quick-link-grid">
            <a class="quick-link" href="/?view=workbench">去研究工作台</a>
            <a class="quick-link" href="/?view=results">去研究结果</a>
            <a class="quick-link" href="/project/ops">去运维中心</a>
          </div>
        </section>
        """
```

- [ ] **Step 5: Run the overview test again**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_overview_page_renders_briefing_sections -v
```

Expected: PASS.

- [ ] **Step 6: Commit the overview checkpoint**

```bash
git add src/stock_quantification/web.py tests/test_web.py
git commit -m "feat: rebuild overview as morning briefing page"
```

### Task 4: Move Strategy Execution and Factor Backtests Into Research Workbench

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing tests for the workbench ownership boundary**

```python
    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_workbench_page_owns_strategy_and_backtest_actions(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({"view": ["workbench"]})
        body = response.body.decode("utf-8")
        self.assertIn("Research Workbench / 研究工作台", body)
        self.assertIn("Strategy Run / 策略运行", body)
        self.assertIn("Factor Backtest / 因子回测", body)
        self.assertIn("Current Defaults / 当前默认配置", body)
        self.assertNotIn("Result Group / 结果分组", body)
```

- [ ] **Step 2: Run the workbench ownership test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_workbench_page_owns_strategy_and_backtest_actions -v
```

Expected: FAIL because there is no dedicated workbench page yet.

- [ ] **Step 3: Extract the strategy-run form into a workbench section helper**

```python
    def _render_strategy_run_panel(self) -> str:
        return f"""
        <section class="form-panel">
          <div class="panel__header">
            <div>
              <p class="eyebrow">Strategy Run</p>
              <h2>策略运行</h2>
            </div>
          </div>
          <form class="stack" method="post" action="/run">
            {self._render_run_form_fields()}
            <button class="button button--primary" type="submit">提交运行</button>
          </form>
        </section>
        """
```

- [ ] **Step 4: Extract the factor-backtest form and immediate-feedback panels**

```python
    def _render_workbench_page(self, query: Dict[str, List[str]]) -> str:
        body = "".join(
            [
                self._render_workbench_summary_strip(),
                '<div class="split-layout">'
                f"{self._render_strategy_run_panel()}"
                f"{self._render_factor_backtest_panel()}"
                "</div>",
                self._render_workbench_feedback_panel(),
            ]
        )
        return self._render_page_shell(
            "workbench",
            "研究工作台",
            "Research Workbench",
            "发起策略运行、因子回测和参数化实验，并查看当前执行反馈。",
            body,
        )
```

- [ ] **Step 5: Update redirect expectations if workbench becomes the new owning page for invalid experiment forms**

```python
        self.assertEqual(response.headers["Location"], "/?view=workbench")
```

- [ ] **Step 6: Run the workbench test and affected redirect tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_web.WebTests.test_workbench_page_owns_strategy_and_backtest_actions \
  tests.test_web.WebTests.test_handle_run_invalid_form_value_redirects_with_flash \
  tests.test_web.WebTests.test_factor_backtest_invalid_form_value_redirects_with_flash -v
```

Expected: PASS.

- [ ] **Step 7: Commit the workbench checkpoint**

```bash
git add src/stock_quantification/web.py tests/test_web.py
git commit -m "feat: move experiment execution into research workbench"
```

### Task 5: Make Research Results the Canonical Result Browser

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing tests for result browsing ownership**

```python
    @patch.object(DashboardApp, "_symbol_catalog", return_value=[{"symbol": "AAPL", "name": "Apple Inc."}])
    @patch.object(DashboardApp, "_render_local_paper_panel", return_value="<section>模拟盘账户</section>")
    def test_results_page_renders_filter_bar_and_detail_pane(self, _mock_paper_panel, _mock_symbol_catalog) -> None:
        response = self.app.render_home({"view": ["results"]})
        body = response.body.decode("utf-8")
        self.assertIn("Result Group / 结果分组", body)
        self.assertIn("Result Type / 结果类型", body)
        self.assertIn("Research Results / 研究结果", body)
        self.assertIn("Runtime Results / 运行结果", body)
        self.assertNotIn("Strategy Run / 策略运行", body)
```

- [ ] **Step 2: Run the results test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_results_page_renders_filter_bar_and_detail_pane -v
```

Expected: FAIL because result browsing still lives inside the old home page.

- [ ] **Step 3: Add filter parsing and result-center helpers**

```python
    def _render_results_page(self, query: Dict[str, List[str]]) -> str:
        selected_artifact = self._resolve_selected_artifact(query.get("artifact", [None])[0])
        body = "".join(
            [
                self._render_results_filter_bar(query),
                self._render_indexed_result_sections(selected_artifact),
                self._render_selected_artifact(selected_artifact),
            ]
        )
        return self._render_page_shell(
            "results",
            "研究结果",
            "Research Results",
            "筛选、浏览和比较研究与运行产出，不在此页承载实验入口。",
            body,
        )
```

- [ ] **Step 4: Separate research and runtime records in the results page helper**

```python
    def _render_indexed_result_sections(self, selected_artifact: Optional[ArtifactEntry]) -> str:
        research_records, runtime_records = self._split_indexed_records()
        return (
            self._render_result_group_panel("Research Results / 研究结果", research_records, selected_artifact)
            + self._render_result_group_panel("Runtime Results / 运行结果", runtime_records, selected_artifact)
        )
```

- [ ] **Step 5: Run the results tests plus the existing indexed-result tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_web.WebTests.test_results_page_renders_filter_bar_and_detail_pane \
  tests.test_web.WebTests.test_home_page_renders_indexed_research_results \
  tests.test_web.WebTests.test_home_page_separates_research_and_runtime_indexed_results -v
```

Expected: PASS after updating the older test names/assertions to the new page ownership.

- [ ] **Step 6: Commit the results checkpoint**

```bash
git add src/stock_quantification/web.py tests/test_web.py
git commit -m "feat: make research results a dedicated browser page"
```

### Task 6: Keep Local Paper Focused on Account Review

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write a failing test for the paper page**

```python
    def test_paper_page_renders_account_workspace(self) -> None:
        self.app.state.last_run_results = []
        response = self.app.render_home({"view": ["paper"]})
        body = response.body.decode("utf-8")
        self.assertIn("Local Paper / 模拟盘", body)
        self.assertIn("Account Summary / 账户概览", body)
        self.assertIn("Positions / 持仓", body)
        self.assertIn("Trades / 成交", body)
        self.assertNotIn("Factor Backtest / 因子回测", body)
```

- [ ] **Step 2: Run the paper-page test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_paper_page_renders_account_workspace -v
```

Expected: FAIL because there is no dedicated paper page view.

- [ ] **Step 3: Wrap the existing paper account content inside a focused paper page helper**

```python
    def _render_paper_page(self, query: Dict[str, List[str]]) -> str:
        body = self._render_local_paper_panel(query)
        return self._render_page_shell(
            "paper",
            "模拟盘",
            "Local Paper",
            "查看账户净值、持仓、成交和最近一次关联运行，不在此页承载研究操作。",
            body,
        )
```

- [ ] **Step 4: Tune the paper panel headings to read like an account workspace**

```python
        self._summary_tile("Latest NAV / 最新净值", latest_nav, "当前账户最新净值")
        self._summary_tile("Positions / 持仓数", position_count, "当前持仓数量")
        self._summary_tile("Trades / 成交数", trade_count, "筛选条件下成交数量")
```

- [ ] **Step 5: Run the paper-page test and the existing paper summary tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_web.WebTests.test_paper_page_renders_account_workspace \
  tests.test_web.WebTests.test_local_paper_panel_renders_latest_run_summary \
  tests.test_web.WebTests.test_local_paper_panel_falls_back_to_indexed_run_summary -v
```

Expected: PASS.

- [ ] **Step 6: Commit the paper-page checkpoint**

```bash
git add src/stock_quantification/web.py tests/test_web.py
git commit -m "feat: focus local paper page on account review"
```

### Task 7: Rebuild Logs, Operations, and Settings Around Single Responsibilities

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing tests for supporting page headings and ownership**

```python
    @patch.object(DashboardApp, "_load_task_logs", return_value=[{"created_at": "2026-04-06T09:30:00", "category": "runtime", "action": "strategy_run", "status": "SUCCESS", "detail": "ok", "metadata": {"market": "US"}}])
    def test_task_logs_page_reads_as_reporting_page(self, _mock_logs) -> None:
        response = self.app.render_task_logs()
        body = response.body.decode("utf-8")
        self.assertIn("Tasks & Logs / 任务与日志", body)
        self.assertIn("Project Activity / 项目流水", body)

    @patch.object(DashboardApp, "_build_system_status", return_value={"overall_status": "WARN", "artifact_count": 5, "task_log_count": 3, "paper_account_count": 1, "broker_credentials_ready": False, "latest_review": "WARN", "active_job": None, "job_history": [], "audit_events": [], "components": [{"name": "artifact_storage", "status": "UP", "detail": "ok"}]})
    def test_ops_center_reads_as_duty_page(self, _mock_status) -> None:
        response = self.app.render_ops_center()
        body = response.body.decode("utf-8")
        self.assertIn("Operations / 运维中心", body)
        self.assertIn("System Health / 系统状态", body)
        self.assertIn("Run Guard / 运行守护", body)
```

- [ ] **Step 2: Run the supporting-page tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_web.WebTests.test_task_logs_page_reads_as_reporting_page \
  tests.test_web.WebTests.test_ops_center_reads_as_duty_page \
  tests.test_web.WebTests.test_project_config_page_renders -v
```

Expected: FAIL because the pages still use the old shell and old headings.

- [ ] **Step 3: Wrap logs, ops, and config with the shared page shell**

```python
    def render_task_logs(self) -> WebResponse:
        body = self._render_task_logs_page()
        return self._html_page(
            self._render_page_shell(
                "logs",
                "任务与日志",
                "Tasks & Logs",
                "查看项目执行流水，不在此页混入系统健康或研究表单。",
                body,
            ),
            title="Tasks & Logs",
        )
```

- [ ] **Step 4: Tighten ownership copy for operations and settings**

```python
    def render_ops_center(self) -> WebResponse:
        body = self._render_ops_page()
        return self._html_page(
            self._render_page_shell(
                "ops",
                "运维中心",
                "Operations",
                "只看系统健康、后台任务、审计事件和运行守护。",
                body,
            ),
            title="Operations",
        )
```

- [ ] **Step 5: Run the supporting-page tests again**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_web.WebTests.test_task_logs_page_reads_as_reporting_page \
  tests.test_web.WebTests.test_ops_center_reads_as_duty_page \
  tests.test_web.WebTests.test_project_config_page_renders -v
```

Expected: PASS after updating the settings page assertions to the new wording.

- [ ] **Step 6: Commit the supporting-page checkpoint**

```bash
git add src/stock_quantification/web.py tests/test_web.py
git commit -m "feat: align supporting admin pages with single-page ownership"
```

### Task 8: Regression Cleanup, Redirect Audit, and Final Verification

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `tests/test_web.py`

- [ ] **Step 1: Audit redirects so failed experiment submissions return to the owning page**

```python
        return self._redirect("/?view=workbench")
```

- [ ] **Step 2: Remove stale helper paths and dead module references**

```python
    # Delete obsolete helpers once all pages use the new shell:
    # - _render_content
    # - _render_module_nav
```

- [ ] **Step 3: Run the full web test module serially**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: PASS.

- [ ] **Step 4: Run the full project test suite serially**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: PASS. If artifact-write contention appears again, fix the offending test or isolate its temporary artifact root before moving on.

- [ ] **Step 5: Manual smoke-check the dashboard routes**

Run:

```bash
PYTHONPATH=src python3 -m stock_quantification.cli web --host 127.0.0.1 --port 8000
```

Then verify in a browser:

- `http://127.0.0.1:8000/?view=overview`
- `http://127.0.0.1:8000/?view=workbench`
- `http://127.0.0.1:8000/?view=results`
- `http://127.0.0.1:8000/?view=paper`
- `http://127.0.0.1:8000/project/logs`
- `http://127.0.0.1:8000/project/ops`
- `http://127.0.0.1:8000/project/config`

Expected: every page loads with the shared shell, the sidebar shows the correct active page, the top strip contains status only, and no page repeats another page's responsibility.

- [ ] **Step 6: Commit the regression-clean checkpoint**

```bash
git add src/stock_quantification/web.py templates/dashboard.html static/styles.css tests/test_web.py
git commit -m "feat: finish report-first admin dashboard redesign"
```
