from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json_artifact(base_dir: str | Path, relative_path: str, payload: Any) -> str:
    root = ensure_directory(Path(base_dir))
    target = root / relative_path
    ensure_directory(target.parent)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_target = Path(handle.name)
    temp_target.replace(target)
    return str(target)


def write_text_artifact(base_dir: str | Path, relative_path: str, payload: str) -> str:
    root = ensure_directory(Path(base_dir))
    target = root / relative_path
    ensure_directory(target.parent)
    target.write_text(payload, encoding="utf-8")
    return str(target)


def read_json_artifact(
    base_dir: str | Path,
    relative_path: str,
    max_age_hours: Optional[int] = None,
) -> Any:
    target = Path(base_dir) / relative_path
    if not target.exists():
        return None
    if max_age_hours is not None:
        modified_at = datetime.fromtimestamp(target.stat().st_mtime)
        if datetime.now() - modified_at > timedelta(hours=max_age_hours):
            return None
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_bytes_artifact(base_dir: str | Path, relative_path: str, payload: bytes) -> str:
    root = ensure_directory(Path(base_dir))
    target = root / relative_path
    ensure_directory(target.parent)
    with target.open("wb") as handle:
        handle.write(payload)
    return str(target)


def read_bytes_artifact(
    base_dir: str | Path,
    relative_path: str,
    max_age_hours: Optional[int] = None,
) -> Optional[bytes]:
    target = Path(base_dir) / relative_path
    if not target.exists():
        return None
    if max_age_hours is not None:
        modified_at = datetime.fromtimestamp(target.stat().st_mtime)
        if datetime.now() - modified_at > timedelta(hours=max_age_hours):
            return None
    return target.read_bytes()
