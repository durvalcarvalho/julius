from __future__ import annotations

import sqlite3


def spent_in_month(conn: sqlite3.Connection, month: str) -> float:
    row = conn.execute("SELECT spent_usd FROM ai_usage WHERE month = ?", (month,)).fetchone()
    return 0.0 if row is None else float(row["spent_usd"])


def add_spent(conn: sqlite3.Connection, month: str, usd: float) -> None:
    conn.execute(
        "INSERT INTO ai_usage (month, spent_usd) VALUES (?, ?) "
        "ON CONFLICT(month) DO UPDATE SET spent_usd = spent_usd + excluded.spent_usd",
        (month, usd),
    )
