from __future__ import annotations

import sqlite3

from julius.domain.models import ContentUnit, Product
from julius.domain.normalization import normalize_text


def find_product_id(conn: sqlite3.Connection, store_cnpj: str, product_code: str) -> int | None:
    row = conn.execute(
        "SELECT product_id FROM product_skus WHERE store_cnpj = ? AND product_code = ?",
        (store_cnpj, product_code),
    ).fetchone()
    return None if row is None else row["product_id"]


def resolve_product_id(conn: sqlite3.Connection, store_cnpj: str, product_code: str, description: str) -> int:
    product_id = find_product_id(conn, store_cnpj, product_code)
    if product_id is not None:
        return product_id
    product_id = conn.execute("INSERT INTO products (canonical_name) VALUES (?)", (description,)).lastrowid
    conn.execute(
        "INSERT INTO product_skus (store_cnpj, product_code, product_id) VALUES (?, ?, ?)",
        (store_cnpj, product_code, product_id),
    )
    return product_id


def get_product(conn: sqlite3.Connection, product_id: int) -> Product | None:
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return None if row is None else _to_product(conn, row)


def list_products(conn: sqlite3.Connection) -> list[Product]:
    rows = conn.execute("SELECT * FROM products ORDER BY canonical_name, id").fetchall()
    # ponytail: one tag query per product; fine for a personal catalog of hundreds
    return [_to_product(conn, row) for row in rows]


def product_names(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [(row["id"], row["canonical_name"]) for row in conn.execute("SELECT id, canonical_name FROM products")]


def rename_product(conn: sqlite3.Connection, product_id: int, name: str) -> None:
    _require_row(conn.execute("UPDATE products SET canonical_name = ? WHERE id = ?", (name, product_id)), product_id)


def set_content(conn: sqlite3.Connection, product_id: int, quantity: float, unit: ContentUnit) -> None:
    cursor = conn.execute(
        "UPDATE products SET content_quantity = ?, content_unit = ? WHERE id = ?",
        (quantity, unit, product_id),
    )
    _require_row(cursor, product_id)


def clear_content(conn: sqlite3.Connection, product_id: int) -> None:
    _require_exists(conn, product_id)
    # Both columns together: half a content is an invalid state.
    conn.execute("UPDATE products SET content_quantity = NULL, content_unit = NULL WHERE id = ?", (product_id,))


def all_kinds(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT kind FROM products WHERE kind IS NOT NULL ORDER BY kind")
    return [row["kind"] for row in rows]


def set_kind(conn: sqlite3.Connection, product_id: int, kind: str | None) -> None:
    """Writes the comparison group. The spelling rule lives here, not in the service layer:
    `curation.apply` writes through the repositories, so a rule in `catalog` would be bypassed."""
    _require_exists(conn, product_id)
    if kind is not None:
        cleaned = kind.strip().lower()
        if not cleaned:
            raise ValueError("kind must not be blank")
        normalized = normalize_text(cleaned)
        kind = next((known for known in all_kinds(conn) if normalize_text(known) == normalized), cleaned)
    conn.execute("UPDATE products SET kind = ? WHERE id = ?", (kind, product_id))


def add_tag(conn: sqlite3.Connection, product_id: int, tag_name: str) -> None:
    _require_exists(conn, product_id)
    conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
    conn.execute(
        "INSERT OR IGNORE INTO product_tags (product_id, tag_id) SELECT ?, id FROM tags WHERE name = ?",
        (product_id, tag_name),
    )


def product_ids_with_tag(conn: sqlite3.Connection, tag_name: str) -> list[int]:
    rows = conn.execute(
        "SELECT pt.product_id FROM product_tags pt JOIN tags t ON t.id = pt.tag_id WHERE t.name = ? ORDER BY pt.product_id",
        (tag_name,),
    )
    return [row["product_id"] for row in rows]


def all_tag_names(conn: sqlite3.Connection) -> list[str]:
    return [row["name"] for row in conn.execute("SELECT name FROM tags ORDER BY name")]


def remove_tag(conn: sqlite3.Connection, product_id: int, tag_name: str) -> None:
    _require_exists(conn, product_id)
    cursor = conn.execute(
        "DELETE FROM product_tags WHERE product_id = ? AND tag_id = (SELECT id FROM tags WHERE name = ?)",
        (product_id, tag_name),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"product {product_id} has no tag {tag_name!r}")


def untagged_product_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT id FROM products WHERE id NOT IN (SELECT product_id FROM product_tags) ORDER BY id")
    return [row["id"] for row in rows]


def has_raw_name(conn: sqlite3.Connection, product_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM prices p JOIN products pr ON pr.id = p.product_id
        WHERE pr.id = ? AND p.description = pr.canonical_name
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    return row is not None


def reassign_skus(conn: sqlite3.Connection, source_id: int, target_id: int) -> None:
    conn.execute("UPDATE product_skus SET product_id = ? WHERE product_id = ?", (target_id, source_id))


def delete_product(conn: sqlite3.Connection, product_id: int) -> None:
    _require_exists(conn, product_id)
    conn.execute("DELETE FROM product_tags WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


def _to_product(conn: sqlite3.Connection, row: sqlite3.Row) -> Product:
    tags = conn.execute(
        "SELECT t.name FROM tags t JOIN product_tags pt ON pt.tag_id = t.id WHERE pt.product_id = ? ORDER BY t.name",
        (row["id"],),
    )
    return Product(
        id=row["id"],
        canonical_name=row["canonical_name"],
        content_quantity=row["content_quantity"],
        content_unit=row["content_unit"],
        tags=tuple(tag["name"] for tag in tags),
        kind=row["kind"],
    )


def _require_exists(conn: sqlite3.Connection, product_id: int) -> None:
    if conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone() is None:
        raise LookupError(f"product {product_id} not found")


def _require_row(cursor: sqlite3.Cursor, product_id: int) -> None:
    if cursor.rowcount == 0:
        raise LookupError(f"product {product_id} not found")
