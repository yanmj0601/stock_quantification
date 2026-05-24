from evoquant.storage import SQLiteStore


def test_v2_tables_are_initialized(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")

    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

    table_names = {row["name"] for row in rows}
    assert {
        "instruments",
        "market_bars",
        "market_sync_jobs",
        "market_quality_reports",
        "signal_scans",
        "signal_results",
        "paper_order_drafts",
        "schedule_configs",
    }.issubset(table_names)


def test_storage_migrates_existing_bar_sync_jobs_table(tmp_path):
    db_path = tmp_path / "state.db"
    store = SQLiteStore(db_path)
    with store.connection() as conn:
        conn.execute("DROP TABLE bar_sync_jobs")
        conn.execute(
            """
            CREATE TABLE bar_sync_jobs (
                id TEXT PRIMARY KEY,
                market TEXT NOT NULL
            )
            """
        )

    SQLiteStore(db_path)

    with SQLiteStore(db_path).connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(bar_sync_jobs)").fetchall()
        }
    assert "scheduled_for" in columns
    assert "target_symbols" in columns
