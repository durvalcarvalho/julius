from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from julius.domain.models import PriceRecord, Receipt, ReceiptItem

EXPORT_COLUMNS = (
    "purchased_at",
    "store_cnpj",
    "store_nickname",
    "store_address",
    "product_id",
    "canonical_name",
    "product_code",
    "description",
    "quantity",
    "unit",
    "unit_price",
    "total_price",
    "access_key",
    "item_index",
)

_EXPORT_SQL = """
SELECT p.purchased_at, p.store_cnpj, s.nickname AS store_nickname, s.address AS store_address,
       p.product_id, pr.canonical_name, p.product_code, p.description, p.quantity, p.unit,
       p.unit_price, p.total_price, p.access_key, p.item_index
FROM prices p
JOIN stores s ON s.cnpj = p.store_cnpj
JOIN products pr ON pr.id = p.product_id
ORDER BY p.purchased_at, p.access_key, p.item_index
"""


def insert_price(conn: sqlite3.Connection, receipt: Receipt, item: ReceiptItem, product_id: int) -> bool:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO prices (access_key, item_index, purchased_at, store_cnpj, product_id,
                                      product_code, description, quantity, unit, unit_price, total_price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            receipt.access_key,
            item.index,
            receipt.issued_at,
            receipt.store_cnpj,
            product_id,
            item.product_code,
            item.description,
            item.quantity,
            item.unit,
            item.unit_price,
            item.total_price,
        ),
    )
    return cursor.rowcount == 1


def prices_for_products(conn: sqlite3.Connection, product_ids: Sequence[int]) -> list[PriceRecord]:
    if not product_ids:
        return []
    placeholders = ",".join("?" * len(product_ids))
    rows = conn.execute(
        f"""
        SELECT p.product_id, pr.canonical_name, s.nickname, s.address, p.unit, p.unit_price, p.purchased_at,
               pr.content_quantity, pr.content_unit
        FROM prices p
        JOIN stores s ON s.cnpj = p.store_cnpj
        JOIN products pr ON pr.id = p.product_id
        WHERE p.product_id IN ({placeholders})
        ORDER BY p.purchased_at DESC, p.unit_price
        """,
        tuple(product_ids),
    )
    return [
        PriceRecord(
            product_id=row["product_id"],
            canonical_name=row["canonical_name"],
            store_nickname=row["nickname"],
            unit=row["unit"],
            unit_price=row["unit_price"],
            purchased_at=row["purchased_at"],
            price_per_content=None if row["content_quantity"] is None else row["unit_price"] / row["content_quantity"],
            content_unit=row["content_unit"],
            store_address=row["address"],
        )
        for row in rows
    ]


def export_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    return [dict(zip(EXPORT_COLUMNS, row)) for row in conn.execute(_EXPORT_SQL)]


def reassign_product(conn: sqlite3.Connection, source_id: int, target_id: int) -> None:
    conn.execute("UPDATE prices SET product_id = ? WHERE product_id = ?", (target_id, source_id))


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM prices").fetchone()[0]
