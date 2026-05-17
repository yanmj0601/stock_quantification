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
