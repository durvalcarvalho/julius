from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def tail(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    """The last `limit` records, newest first. Never raises: a broken log reads as fewer lines."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records[-max(limit, 1) :][::-1]


def append(path: Path, record: Mapping[str, Any]) -> None:
    """One JSON line per call. Never raises: a broken log must never break the caller."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
