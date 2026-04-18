# Admin Dashboard Redesign Design

## Overview

This redesign replaces the current dark, glassy, all-in-one admin surface with a lighter, report-first research workbench. The primary problem is not missing functionality; it is that too many unrelated tasks are visually compressed into the same page and styled with a presentation language that hides hierarchy instead of clarifying it. The new dashboard should feel like an internal quant research platform: clear, calm, dense where necessary, and immediately scannable.

The redesign keeps the current backend routes, data sources, and page responsibilities where possible, but it changes the visual system, page composition, and navigation model. The goal is to make the existing workflow usable before adding more platform features. The UI should privilege reading, filtering, and comparing over showing everything at once.

This design deliberately avoids a flashy consumer-product aesthetic. The interface should look like a serious internal tool used by researchers and operators every day. It should feel meticulously crafted, with restrained typography, confident spacing, clear panel boundaries, and table-oriented detail views. Every screen should read as a report with actions, not as a collage of cards.

## Design Direction

The visual direction is "reporting workbench" with a small amount of modern product polish. The application moves from a dark, atmospheric, gradient-heavy style to a light, paper-like environment with strong information grouping. Backgrounds should be warm off-white rather than pure white. Text should be dark and quiet. Accent colors should be limited and purposeful: blue-gray for structure, copper or rust for emphasis, and green/red only for state indicators.

Typography should support research reading rather than visual spectacle. Page titles should feel editorial and deliberate. Body text, controls, and dense data views should optimize for readability and scanning. Numeric metrics should have a slightly stronger voice than surrounding text so important values stand out without relying on oversaturated colors.

The component language should move away from stacking every module into isolated glossy cards. The redesign should instead use section panels, summary bars, compact tables, and filter rows. Borders and dividers become more important than shadows. Corner radii should tighten. Shadows should be minimal and only used to separate priority surfaces. The overall result should feel ordered and professional, not decorative.

## Information Architecture

The current home page tries to do too much. The redesign creates a stable application shell with left navigation, a restrained top status strip, and dedicated pages with clearer responsibilities. The left navigation should contain:

- Overview
- Research Results
- Local Paper
- Tasks & Logs
- Operations
- Project Settings

The top status strip should remain lightweight. It should show only the most important current-state information such as latest market, latest run time, system health, and a small set of shortcuts. It should not duplicate large page content.

Each page should use a consistent structure:

1. Page title and one-sentence page purpose
2. Summary row with the most important metrics or conclusions
3. Main working area containing lists, tables, filters, and detail panes

The application should stop treating the overview page as the place where every subsystem must appear in full. Overview becomes a launch surface. The detailed work moves into dedicated pages.

## Page Design

### Overview

Overview should function as a morning briefing screen. It answers four questions first: what ran most recently, whether the latest result is good or bad, whether the system is healthy, and where to go next. It should not contain large configuration forms or expanded detail tables.

The overview page should contain six blocks:

- High-level summary strip
- Latest research outcomes
- Latest runtime outcomes
- Local paper account summary
- Active tasks and notable warnings
- Quick actions and page shortcuts

The page should privilege conclusions over raw detail. A user should be able to scan it in under thirty seconds and decide whether to drill into research, runtime, or operations.

### Research Results

This is the primary workbench page. It should become the canonical place to browse indexed research outputs and runtime outputs. The page should start with a compact filter bar that supports at minimum:

- Result group: research or runtime
- Result type
- Market
- Date or recent window

Below the filter bar, results should render as a list or compact card-table hybrid rather than oversized marketing cards. The detail pane for a selected result should continue to prioritize normalized summary fields, followed by rationale, metrics, and artifact links. Research outputs and runtime outputs should be visually separated so users do not confuse validation studies with local paper runs.

### Local Paper

The local paper page should be treated as an account workspace. It should open with account summary, latest NAV, cumulative return, position count, trade count, and recent run summary. Below that, the layout should split into:

- NAV and latest run context
- Day summary and risk flags
- Positions table
- Trades table

This page should feel like an account report, not a sidebar widget promoted to full width.

### Tasks & Logs

The logs page should be a reporting page, not a card page. It should lead with filters and then present a clear table with time, category, action, status, and detail. Success, blocked, and failed rows should be scannable through restrained status badges rather than loud background treatments.

### Operations

Operations should remain the system health page. It should group health, active jobs, job history, component state, and audit events into clearly separated report sections. The goal is to let operators understand current state quickly, not to create a dashboard full of decorative metrics.

### Project Settings

Project settings should be reorganized as grouped configuration panels:

- Runtime defaults
- Research defaults
- UI preferences

Each group should have a small explanation and cleaner field grouping. The page should stop feeling like a long dump of inputs.

## Interaction Model

The redesign stays read-first. It does not add complex editing workflows in this phase. The biggest change is navigational and structural, not behavioral. Filters on the research results page should be GET-style and transparent in the URL where practical. Lists and detail panes should update predictably. Quick actions on the overview page should link users into the dedicated pages that own the detailed workflow.

Because this is an internal tool, responsiveness still matters, but perfect mobile parity is not the goal. The layout should gracefully collapse on narrower screens, yet the primary target remains desktop and laptop usage.

## Implementation Boundaries

This redesign should preserve the existing server-side page model and routes. It should not introduce a frontend framework migration, a design system dependency, or a new application shell architecture. The implementation should stay inside the current template and CSS approach, with targeted reorganization in the Python HTML assembly layer as needed.

The redesign should not delete existing backend functionality. It should delete and replace the old visual and layout implementation where necessary, but it should preserve working behavior unless the redesign intentionally relocates it to a more appropriate page.

The first implementation pass should cover the full shell and all current top-level pages together so the visual language feels coherent. However, the redesign should still be executed in slices:

1. Global shell and visual system
2. Overview and research results
3. Local paper, logs, operations, and settings
4. Regression cleanup and polish

## Risks and Mitigations

The largest risk is replacing a lot of markup at once and losing important operational affordances. To reduce that risk, the redesign should keep route-level behavior and test coverage intact while changing presentation in layers. Another risk is making the UI cleaner but too sparse for a data-dense workflow. The mitigation is to favor compact report layouts and tables over decorative whitespace-only minimalism.

There is also a maintainability risk because much of the current UI is generated in one large Python module. The redesign should include light structural cleanup where it materially helps the page architecture, but it should avoid a speculative rewrite. We should improve boundaries only where the redesign depends on it.

## Testing Strategy

Existing web tests should be updated to assert the new navigation labels, page headings, and result-center grouping. Route behavior, flash messages, local paper summaries, and indexed result rendering should remain covered. After the redesign, the full unittest suite should still pass. Because the project already has a demonstrated history of artifact write contention, verification should prefer serial test execution for the final pass.

## Out of Scope

This redesign does not add full result comparison workflows, role-based permissions, advanced charting, a new frontend framework, or a production-grade design system package. It also does not attempt to complete the broker-side execution loop. The focus is a coherent, usable, visually strong admin workbench built on the current stack.
