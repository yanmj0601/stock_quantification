from evoquant.storage import PostgreSQLStore


def test_v2_tables_are_initialized(tmp_path):
    store = PostgreSQLStore()

    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT table_name AS name
            FROM information_schema.tables
            WHERE table_schema = current_schema()
            ORDER BY table_name
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

