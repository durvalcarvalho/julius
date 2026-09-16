from __future__ import annotations

import sqlite3

from julius.domain.models import Store


def ensure_store(conn: sqlite3.Connection, cnpj: str, legal_name: str, address: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO stores (cnpj, legal_name, nickname, address) VALUES (?, ?, ?, ?)
        ON CONFLICT(cnpj) DO UPDATE SET address = COALESCE(excluded.address, stores.address)
        """,
        (cnpj, legal_name, legal_name, address),
    )


def get_store(conn: sqlite3.Connection, cnpj: str) -> Store | None:
    row = conn.execute("SELECT cnpj, legal_name, nickname, address FROM stores WHERE cnpj = ?", (cnpj,)).fetchone()
    return _to_store(row) if row else None


def list_stores(conn: sqlite3.Connection) -> list[Store]:
    rows = conn.execute("SELECT cnpj, legal_name, nickname, address FROM stores ORDER BY nickname, cnpj")
    return [_to_store(row) for row in rows]


def rename_store(conn: sqlite3.Connection, cnpj: str, nickname: str) -> None:
    cursor = conn.execute("UPDATE stores SET nickname = ? WHERE cnpj = ?", (nickname, cnpj))
    if cursor.rowcount == 0:
        raise LookupError(f"store {cnpj} not found")


def _to_store(row: sqlite3.Row) -> Store:
    return Store(cnpj=row["cnpj"], legal_name=row["legal_name"], nickname=row["nickname"], address=row["address"])
