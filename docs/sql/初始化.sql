-- PostgreSQL initialization, synchronized with storage.py, paper.py and risk.py.
-- Run against an existing empty application database; no credentials or seed records.
BEGIN;

CREATE TABLE IF NOT EXISTS strategies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    template_id TEXT NOT NULL,
    parameters TEXT NOT NULL,
    status TEXT NOT NULL,
    version BIGINT NOT NULL,
    metrics TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    exchange TEXT NOT NULL,
    currency TEXT NOT NULL,
    sector TEXT NOT NULL,
    index_membership TEXT NOT NULL,
    tradable BIGINT NOT NULL,
    lot_size BIGINT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, market)
);

CREATE TABLE IF NOT EXISTS market_bars (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    session TEXT NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    adjusted BIGINT NOT NULL,
    suspended BIGINT NOT NULL,
    limit_up BIGINT NOT NULL,
    limit_down BIGINT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, market, session)
);

CREATE TABLE IF NOT EXISTS market_sync_jobs (
    id TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_symbols BIGINT NOT NULL,
    success_symbols BIGINT NOT NULL,
    failed_symbols BIGINT NOT NULL,
    coverage DOUBLE PRECISION NOT NULL,
    failures TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_quality_reports (
    id TEXT PRIMARY KEY,
    sync_job_id TEXT NOT NULL,
    market TEXT NOT NULL,
    missing_bars BIGINT NOT NULL,
    duplicate_bars BIGINT NOT NULL,
    price_anomalies BIGINT NOT NULL,
    suspended_count BIGINT NOT NULL,
    limit_up_count BIGINT NOT NULL,
    limit_down_count BIGINT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bar_sync_jobs (
    id TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    batch_size BIGINT NOT NULL,
    total_symbols BIGINT NOT NULL,
    completed_symbols BIGINT NOT NULL,
    success_symbols BIGINT NOT NULL,
    failed_symbols BIGINT NOT NULL,
    progress DOUBLE PRECISION NOT NULL,
    failures TEXT NOT NULL,
    target_symbols TEXT NOT NULL DEFAULT '[]',
    scheduled_for TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signal_scans (
    id TEXT PRIMARY KEY,
    strategy_template TEXT NOT NULL,
    parameters TEXT NOT NULL,
    market_scope TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    coverage TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signal_results (
    scan_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    signal TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    target_weight DOUBLE PRECISION NOT NULL,
    reason TEXT NOT NULL,
    risk_flags TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    rank BIGINT NOT NULL,
    PRIMARY KEY (scan_id, symbol, market)
);

CREATE TABLE IF NOT EXISTS paper_order_drafts (
    id TEXT PRIMARY KEY,
    scan_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    side TEXT NOT NULL,
    target_weight DOUBLE PRECISION NOT NULL,
    current_weight DOUBLE PRECISION NOT NULL,
    estimated_quantity DOUBLE PRECISION NOT NULL,
    reference_price DOUBLE PRECISION NOT NULL,
    reason TEXT NOT NULL,
    risk_flags TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_configs (
    id TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    enabled BIGINT NOT NULL,
    timezone TEXT NOT NULL,
    run_time TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cash DOUBLE PRECISION NOT NULL,
    nav DOUBLE PRECISION NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_orders (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    quantity DOUBLE PRECISION NOT NULL,
    limit_price DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_fills (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    quantity DOUBLE PRECISION NOT NULL,
    fill_price DOUBLE PRECISION NOT NULL,
    fee DOUBLE PRECISION NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    quantity DOUBLE PRECISION NOT NULL,
    average_cost DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (account_id, symbol, market)
);

CREATE TABLE IF NOT EXISTS risk_state (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    live_enabled INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

-- Additive migrations also applied by PostgreSQLStore.initialize().
ALTER TABLE bar_sync_jobs ADD COLUMN IF NOT EXISTS scheduled_for VARCHAR NOT NULL DEFAULT '';
ALTER TABLE bar_sync_jobs ADD COLUMN IF NOT EXISTS target_symbols VARCHAR NOT NULL DEFAULT '[]';

COMMIT;
