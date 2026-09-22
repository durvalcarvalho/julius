from __future__ import annotations

import sqlite3


def spent_in_month(conn: sqlite3.Connection, provider: str, month: str) -> float:
    row = conn.execute(
        "SELECT spent_usd FROM decision_usage WHERE provider = ? AND month = ?", (provider, month)
    ).fetchone()
    return 0.0 if row is None else float(row["spent_usd"])


def add_spent(conn: sqlite3.Connection, provider: str, month: str, usd: float) -> None:
    conn.execute(
        "INSERT INTO decision_usage (provider, month, spent_usd) VALUES (?, ?, ?) "
        "ON CONFLICT(provider, month) DO UPDATE SET spent_usd = spent_usd + excluded.spent_usd",
        (provider, month, usd),
    )
