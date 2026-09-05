import os
import pytest
import psycopg2
from evoquant.storage import PostgreSQLStore

# 强制将测试环境隔离至独立的 PostgreSQL 测试数据库 evoquant_test，100% 隔离生产库数据
TEST_DB_URL = os.environ.get(
    "EVOQUANT_TEST_DB_URL",
    "postgresql://postgres:password@192.168.124.18:45869/evoquant_test"
)
os.environ["EVOQUANT_DB_URL"] = TEST_DB_URL

# 自动初始化测试库 evoquant_test
try:
    base_dsn = TEST_DB_URL.replace("/evoquant_test", "/postgres")
    conn = psycopg2.connect(base_dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'evoquant_test'")
    if not cur.fetchone():
        cur.execute("CREATE DATABASE evoquant_test")
    cur.close()
    conn.close()
except Exception:
    pass


@pytest.fixture(autouse=True)
def clean_postgres_test_db():
    try:
        store = PostgreSQLStore(TEST_DB_URL)
        with store.connection() as conn:
            conn.execute(
                """
                TRUNCATE TABLE 
                    strategies,
                    audit_events,
                    instruments,
                    market_bars,
                    market_sync_jobs,
                    market_quality_reports,
                    bar_sync_jobs,
                    signal_scans,
                    signal_results,
                    paper_order_drafts,
                    schedule_configs,
                    paper_accounts,
                    paper_orders,
                    paper_fills,
                    paper_positions,
                    risk_state
                CASCADE;
                """
            )
    except Exception:
        pass
    yield
