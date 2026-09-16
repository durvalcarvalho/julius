from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def append(path: Path, record: Mapping[str, Any]) -> None:
    """One JSON line per call. Never raises: a broken log must never break the caller."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
