"""无需数据库即可运行的 API 契约检查。"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from evoquant import __version__
from evoquant.api import create_app, _store


class ApiContractTests(unittest.TestCase):
    def test_openapi_uses_package_version(self):
        self.assertEqual(create_app().openapi()["info"]["version"], __version__)

    def test_health_and_schema_do_not_connect_to_database(self):
        with patch("evoquant.api.PostgreSQLStore", side_effect=AssertionError("unexpected DB")):
            client = TestClient(create_app())
            self.assertEqual(client.get("/healthz").json(), {"status": "ok"})
            self.assertEqual(client.get("/openapi.json").status_code, 200)

    def test_store_initialized_only_once(self):
        with patch("evoquant.api.PostgreSQLStore") as factory:
            app = create_app()
            factory.assert_not_called()
            self.assertIs(_store(app), _store(app))
            factory.assert_called_once_with()

    def test_unsupported_schedule_returns_client_error(self):
        with patch("evoquant.api.PostgreSQLStore", side_effect=AssertionError("unexpected DB")):
            response = TestClient(create_app()).patch("/api/schedules/CRYPTO", json={"enabled": True})
        self.assertEqual(response.status_code, 400)
        self.assertIn("not supported", response.json()["detail"])

    def test_invalid_paper_order_returns_client_error(self):
        with patch("evoquant.api.PaperTradingService") as paper, patch("evoquant.api.RiskService", autospec=True):
            paper.return_value.submit_order.side_effect = ValueError("quantity must be non-zero")
            response = TestClient(create_app(store=object())).post("/api/paper/orders", json={
                "account_id": "acct_example", "symbol": "AAPL", "market": "US",
                "quantity": 0, "limit_price": 100
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.json()["detail"])

    def test_unsupported_signal_template_returns_client_error(self):
        with patch("evoquant.api.SignalScanner") as scanner:
            scanner.return_value.run_scan.side_effect = ValueError("unsupported strategy template: missing")
            response = TestClient(create_app(store=object())).post("/api/signals/scans", json={
                "strategy_template": "missing", "parameters": {}, "markets": []
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported strategy template", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
