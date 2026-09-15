from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from julius.repositories import prices


def export_csv(conn: sqlite3.Connection, destination: Path) -> int:
    rows = prices.export_rows(conn)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=prices.EXPORT_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
