"""Compatibility package for local ``src``-layout imports.

The project keeps its implementation under ``src/stock_quantification``.
This wrapper lets local commands such as ``python -m unittest discover``
import the package without requiring an editable install or ``PYTHONPATH``.
"""

from __future__ import annotations

from pathlib import Path


_SRC_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "stock_quantification"
_SRC_INIT = _SRC_PACKAGE / "__init__.py"

__file__ = str(_SRC_INIT)
__path__ = [str(_SRC_PACKAGE)]

exec(compile(_SRC_INIT.read_text(encoding="utf-8"), __file__, "exec"), globals(), globals())
