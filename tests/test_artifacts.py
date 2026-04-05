from __future__ import annotations

import tempfile
from unittest import TestCase

from stock_quantification.artifacts import read_json_artifact, write_json_artifact, write_text_artifact


class ArtifactTests(TestCase):
    def test_write_and_read_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_json_artifact(tmpdir, "reports/test.json", {"alpha": 1})
            self.assertTrue(path.endswith("reports/test.json"))
            payload = read_json_artifact(tmpdir, "reports/test.json")
            self.assertEqual(payload["alpha"], 1)

    def test_write_text_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_text_artifact(tmpdir, "reports/test.md", "# hello\n")
            self.assertTrue(path.endswith("reports/test.md"))
