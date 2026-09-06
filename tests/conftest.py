"""数据库测试使用显式配置的数据库，并为每个测试创建独立 schema。"""
import os
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn
import pytest

from evoquant.storage import PostgreSQLStore


@pytest.fixture(autouse=True)
def isolated_postgres_schema(monkeypatch):
    test_dsn = os.environ.get("EVOQUANT_TEST_DB_URL")
    schema = "test_" + uuid4().hex
    admin = None

    def connect_isolated(store):
        nonlocal admin
        if not test_dsn:
            pytest.skip("Set EVOQUANT_TEST_DB_URL to run PostgreSQL integration tests")
        if admin is None:
            admin = psycopg2.connect(test_dsn)
            admin.autocommit = True
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        return psycopg2.connect(make_dsn(test_dsn, options=f"-c search_path={schema}"))

    monkeypatch.setattr(PostgreSQLStore, "_connect", connect_isolated)
    try:
        yield
    finally:
        if admin is not None:
            try:
                with admin.cursor() as cursor:
                    cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            finally:
                admin.close()
