"""测试一个显式提供的 PostgreSQL DSN，且不输出凭据。"""
import os

import psycopg2


dsn = os.environ.get("EVOQUANT_DB_URL")
if not dsn:
    raise SystemExit("Set EVOQUANT_DB_URL before running this script")

with psycopg2.connect(dsn, connect_timeout=3) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user")
        database, user = cursor.fetchone()
print(f"Connected to database {database} as {user}")
