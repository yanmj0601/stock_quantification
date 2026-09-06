from evoquant.storage import PostgreSQLStore, PostgresCursorWrapper


def test_default_database_is_nas(monkeypatch):
    monkeypatch.delenv("EVOQUANT_DB_URL", raising=False)
    monkeypatch.setattr(PostgreSQLStore, "initialize", lambda self: None)
    assert PostgreSQLStore().dsn == "postgresql://postgres:password@192.168.124.18:45869/evoquant"


def test_schema_inspection_uses_current_schema():
    class Cursor:
        def execute(self, sql, params=None):
            self.sql = sql
    cursor = Cursor()
    PostgresCursorWrapper(cursor).execute("PRAGMA table_info(bar_sync_jobs)")
    assert "table_schema = current_schema()" in cursor.sql


def test_documented_initialization_sql_matches_runtime_tables():
    """检查 DDL 漂移，包括 PostgreSQL 包装器执行的类型转换。"""
    import ast
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1]

    def tables(script):
        return {
            name: re.sub(r"\s+", " ", body).strip()
            for name, body in re.findall(
                r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\)\s*(?:;|$)",
                script,
                flags=re.S,
            )
        }

    runtime = {}
    for relative in ("storage.py", "services/paper.py", "services/risk.py"):
        module = ast.parse((root / "src/evoquant" / relative).read_text())
        for node in ast.walk(module):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                script = node.value
                if relative == "services/paper.py":
                    script = script.replace("REAL", "DOUBLE PRECISION").replace("INTEGER", "BIGINT")
                runtime.update(tables(script))
    assert len(runtime) == 16
    assert tables((root / "docs/sql/初始化.sql").read_text()) == runtime
