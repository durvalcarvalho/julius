from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from julius.domain.models import ContentUnit, Product
from julius.domain.normalization import normalize_text


_RAW_NAME_IDS = """
SELECT DISTINCT pr.id FROM products pr JOIN prices px ON px.product_id = pr.id
 WHERE px.description = pr.canonical_name
"""

_GROUP_MEMBERS = """
SELECT 1 FROM products m JOIN product_group g ON g.product_id = m.id WHERE g.root_id = p.id
"""

_GROUP_HAS_TAG = """
SELECT 1 FROM product_tags pt JOIN product_group g ON g.product_id = pt.product_id WHERE g.root_id = p.id
"""


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
    row = conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone()
    return None if row is None else _group_product(conn, group_root(conn, product_id))


def list_products(conn: sqlite3.Connection) -> list[Product]:
    rows = conn.execute("SELECT id FROM products WHERE merged_into IS NULL ORDER BY canonical_name, id").fetchall()
    # ponytail: three queries per group — 30 ms for the real 105-product catalog; revisit at 10x
    return [_group_product(conn, row["id"]) for row in rows]


def product_names(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [(product.id, product.canonical_name) for product in list_products(conn)]


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
    """Roots, deduplicated: a tag that sits only on the absorbed product must bring its group,
    or `consultar --tag` would stop finding what `produtos listar` shows as tagged."""
    rows = conn.execute(
        """
        SELECT DISTINCT g.root_id FROM product_tags pt
          JOIN tags t ON t.id = pt.tag_id
          JOIN product_group g ON g.product_id = pt.product_id
        WHERE t.name = ? ORDER BY g.root_id
        """,
        (tag_name,),
    )
    return [row["root_id"] for row in rows]


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
    rows = conn.execute(
        f"""
        SELECT p.id FROM products p
        WHERE p.merged_into IS NULL AND NOT EXISTS ({_GROUP_HAS_TAG})
        ORDER BY p.id
        """
    )
    return [row["id"] for row in rows]


def has_raw_name(conn: sqlite3.Connection, product_id: int) -> bool:
    """Whether the name the group shows is still a receipt description. False as soon as ANY member
    has a hand-edited name, because that is the name the group shows (see _group_product) — so the
    AI never overwrites a name a human chose, wherever in the group it lives."""
    row = conn.execute(
        f"""
        SELECT 1 FROM products m JOIN product_group g ON g.product_id = m.id
        WHERE g.root_id = (SELECT root_id FROM product_group WHERE product_id = ?)
          AND m.id NOT IN ({_RAW_NAME_IDS}) LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    return row is None


def incomplete_product_ids(conn: sqlite3.Connection) -> list[int]:
    """Pending = missing kind, tag or package content. Content only counts for something sold by
    the unit: R$/kg is already a price per content, so a KG-only product would stay pending forever
    with nothing to gain."""
    rows = conn.execute(
        f"""
        SELECT p.id FROM products p
        WHERE p.merged_into IS NULL
          AND (NOT EXISTS ({_GROUP_MEMBERS} AND m.kind IS NOT NULL)
            OR NOT EXISTS ({_GROUP_HAS_TAG})
            OR (NOT EXISTS ({_GROUP_MEMBERS} AND m.content_quantity IS NOT NULL)
                AND EXISTS ({_GROUP_MEMBERS} AND EXISTS (
                    SELECT 1 FROM prices WHERE product_id = m.id AND unit = 'UN'))))
        ORDER BY p.id
        """
    )
    return [row["id"] for row in rows]


def sold_by_unit_ids(conn: sqlite3.Connection, product_ids: Sequence[int]) -> set[int]:
    if not product_ids:
        return set()
    placeholders = ",".join("?" * len(product_ids))
    rows = conn.execute(
        f"""
        SELECT DISTINCT g.root_id FROM prices p JOIN product_group g ON g.product_id = p.product_id
        WHERE p.unit = 'UN' AND g.root_id IN ({placeholders})
        """,
        tuple(product_ids),
    )
    return {row["root_id"] for row in rows}


def receipt_descriptions(conn: sqlite3.Connection, product_ids: Sequence[int]) -> dict[int, str]:
    if not product_ids:
        return {}
    placeholders = ",".join("?" * len(product_ids))
    # SQLite takes `description` from the very row that matched the aggregate. That guarantee holds
    # only while max() is the single aggregate of the query (no second aggregate, no ORDER BY
    # tiebreaker) and purchased_at is ISO 8601, which sorts correctly as text.
    rows = conn.execute(
        f"""
        SELECT g.root_id, p.description, max(p.purchased_at) FROM prices p
          JOIN product_group g ON g.product_id = p.product_id
        WHERE g.root_id IN ({placeholders})
        GROUP BY g.root_id
        """,
        tuple(product_ids),
    )
    return {row["root_id"]: row["description"] for row in rows}


def set_merged_into(conn: sqlite3.Connection, product_id: int, target_id: int | None) -> None:
    """Raw writer for the merge relation. The cycle guard is domain rule and lives in
    `services/catalog.py`: a cycle makes the product_group recursion never return."""
    _require_exists(conn, product_id)
    conn.execute("UPDATE products SET merged_into = ? WHERE id = ?", (target_id, product_id))


def group_root(conn: sqlite3.Connection, product_id: int) -> int:
    _require_exists(conn, product_id)
    row = conn.execute("SELECT root_id FROM product_group WHERE product_id = ?", (product_id,)).fetchone()
    return product_id if row is None else row["root_id"]


def group_members(conn: sqlite3.Connection, root_id: int) -> list[int]:
    root = group_root(conn, root_id)
    rows = conn.execute("SELECT product_id FROM product_group WHERE root_id = ? ORDER BY product_id", (root,))
    return [row["product_id"] for row in rows]




def _group_product(conn: sqlite3.Connection, root_id: int) -> Product:
    """The product a group shows. Nothing is copied to the root: the name, content and kind are
    composed on read, which is what makes unmerging restore the previous state by construction."""
    members = conn.execute(
        """
        SELECT m.* FROM products m JOIN product_group g ON g.product_id = m.id
        WHERE g.root_id = ? ORDER BY (m.id <> ?), m.id
        """,
        (root_id, root_id),
    ).fetchall()
    root = members[0]
    name = conn.execute(
        "SELECT canonical_name FROM product_group_name WHERE root_id = ?", (root_id,)
    ).fetchone()["canonical_name"]
    with_content = next((m for m in members if m["content_quantity"] is not None), root)
    tags = conn.execute(
        """
        SELECT DISTINCT t.name FROM tags t
          JOIN product_tags pt ON pt.tag_id = t.id
          JOIN product_group g ON g.product_id = pt.product_id
        WHERE g.root_id = ? ORDER BY t.name
        """,
        (root_id,),
    )
    return Product(
        id=root["id"],
        canonical_name=name,
        content_quantity=with_content["content_quantity"],
        content_unit=with_content["content_unit"],
        tags=tuple(tag["name"] for tag in tags),
        kind=next((m["kind"] for m in members if m["kind"] is not None), None),
        merged_into=root["merged_into"],
    )


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
        merged_into=row["merged_into"],
    )


def _require_exists(conn: sqlite3.Connection, product_id: int) -> None:
    if conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone() is None:
        raise LookupError(f"product {product_id} not found")


def _require_row(cursor: sqlite3.Cursor, product_id: int) -> None:
    if cursor.rowcount == 0:
        raise LookupError(f"product {product_id} not found")
