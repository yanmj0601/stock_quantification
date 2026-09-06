import os
import sqlite3
import time
from evoquant.storage import PostgreSQLStore
import psycopg2.extras

# 默认的 PostgreSQL DSN 连接串（支持通过环境变量覆盖）
PG_DSN = os.environ.get(
    "EVOQUANT_DB_URL",
    "postgresql://localhost:5432/evoquant"
)
SQLITE_PATH = "var/evoquant.db"

print(f"Connecting to source SQLite database: {SQLITE_PATH}...")
sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row

# 自动探测并创建 evoquant 数据库（以防用户本地是干净的新 PG 实例）
try:
    import psycopg2
    temp_dsn = PG_DSN.replace("/evoquant", "/postgres")
    temp_conn = psycopg2.connect(temp_dsn)
    temp_conn.autocommit = True
    temp_cur = temp_conn.cursor()
    temp_cur.execute("SELECT 1 FROM pg_database WHERE datname = 'evoquant'")
    if not temp_cur.fetchone():
        print("Database 'evoquant' does not exist. Creating it on local PostgreSQL...")
        temp_cur.execute("CREATE DATABASE evoquant")
    temp_cur.close()
    temp_conn.close()
except Exception as e:
    print(f"PostgreSQL connection / database creation warning: {e}")

print(f"Connecting to target PostgreSQL database: {PG_DSN}...")
try:
    pg_store = PostgreSQLStore(PG_DSN)
except Exception as e:
    print(f"Failed to connect/initialize PostgreSQL. Please ensure the PG server is running. Error: {e}")
    exit(1)

tables = [
    "strategies",
    "audit_events",
    "instruments",
    "market_bars",
    "market_sync_jobs",
    "market_quality_reports",
    "bar_sync_jobs",
    "signal_scans",
    "signal_results",
    "paper_order_drafts",
    "schedule_configs"
]

print("Starting tables data migration...")

for table in tables:
    t0 = time.time()
    # 1. 查询该表有多少条记录
    sqlite_cur = sqlite_conn.cursor()
    count_row = sqlite_cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
    total_rows = count_row[0] if count_row else 0
    if total_rows == 0:
        print(f"Table '{table}' has 0 records. Skipped.")
        continue

    print(f"Migrating table '{table}' ({total_rows} rows)...")

    # 获取列字段名
    cols_cur = sqlite_conn.execute(f"SELECT * FROM {table} LIMIT 1")
    cols = [col[0] for col in cols_cur.description]
    cols_str = ",".join(cols)
    placeholders = ",".join(["%s"] * len(cols))

    # 2. 从 SQLite 批量流式读取数据，并利用 PG 极速批量通道 execute_values 写入
    sqlite_cur.execute(f"SELECT {cols_str} FROM {table}")
    
    # 每次分批提取 5000 条记录
    chunk_size = 5000
    migrated_cnt = 0
    
    with pg_store.connection() as pg_conn:
        pg_cur = pg_conn.raw_conn.cursor()
        # 清空目标表（确保幂等性）
        pg_cur.execute(f"TRUNCATE TABLE {table} CASCADE")
        
        while True:
            rows = sqlite_cur.fetchmany(chunk_size)
            if not rows:
                break
            
            # 将 sqlite3.Row 转换为元组列表
            data = [tuple(row) for row in rows]
            
            # 利用 execute_values 进行高吞吐量写入
            psycopg2.extras.execute_values(
                pg_cur,
                f"INSERT INTO {table} ({cols_str}) VALUES %s",
                data,
                page_size=chunk_size
            )
            migrated_cnt += len(data)
            print(f"  [{migrated_cnt}/{total_rows}] Migrated...")
            
    elapsed = time.time() - t0
    print(f"Successfully migrated table '{table}' in {elapsed:.1f}s!")

print("All tables data migration completed successfully!")
