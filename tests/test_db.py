import sqlite3

import pytest

from julius.infra import db

EXPECTED_TABLES = {"stores", "products", "product_skus", "tags", "product_tags", "prices", "ai_usage"}

INSERT_PRICE = """
INSERT INTO prices (access_key, item_index, purchased_at, store_cnpj, product_id,
                    product_code, description, quantity, unit, unit_price, total_price)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_connect_creates_full_schema_at_latest_version(conn):
    assert _tables(conn) == EXPECTED_TABLES
    assert db.schema_version(conn) == 1


def test_connect_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "deep" / "er" / "prices.db"
    db.connect(path).close()
    assert path.exists()


def test_connect_is_idempotent_and_never_backs_up_an_up_to_date_db(db_path):
    db.connect(db_path).close()
    db.connect(db_path).close()
    assert list(db_path.parent.glob("*.bak-*")) == []


def test_rows_are_accessible_by_column_name(conn):
    conn.execute("INSERT INTO stores VALUES ('1', 'Legal Name', 'Nick')")
    assert conn.execute("SELECT * FROM stores").fetchone()["nickname"] == "Nick"


def test_foreign_keys_are_enforced(conn):
    conn.execute("INSERT INTO products (id, canonical_name) VALUES (1, 'X')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(INSERT_PRICE, ("k", 1, "2026-09-12T13:09:16", "00000000000000", 1, "c", "d", 1, "UN", 1, 1))


def test_unit_check_constraint_rejects_raw_codes_that_bypassed_normalization(conn):
    conn.execute("INSERT INTO stores VALUES ('1', 'S', 'S')")
    conn.execute("INSERT INTO products (id, canonical_name) VALUES (1, 'X')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(INSERT_PRICE, ("k", 1, "2026-09-12T13:09:16", "1", 1, "c", "d", 1, "GF", 1, 1))


def test_duplicate_receipt_line_is_rejected_by_primary_key(conn):
    conn.execute("INSERT INTO stores VALUES ('1', 'S', 'S')")
    conn.execute("INSERT INTO products (id, canonical_name) VALUES (1, 'X')")
    row = ("k", 1, "2026-09-12T13:09:16", "1", 1, "c", "d", 1, "UN", 1, 1)
    conn.execute(INSERT_PRICE, row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(INSERT_PRICE, row)


def test_pending_migration_backs_up_existing_db_then_applies_it(db_path, tmp_path):
    conn = db.connect(db_path)
    conn.execute("INSERT INTO stores VALUES ('1', 'Legal', 'Nick')")
    conn.commit()
    extra = tmp_path / "0002_add_notes.sql"
    extra.write_text("CREATE TABLE notes (id INTEGER PRIMARY KEY);", encoding="utf-8")

    db.apply_migrations(conn, db_path, db.available_migrations() + [(2, extra)])

    assert db.schema_version(conn) == 2
    assert "notes" in _tables(conn)
    assert conn.execute("SELECT count(*) FROM stores").fetchone()[0] == 1

    backup = sqlite3.connect(db_path.with_name("prices.db.bak-v1"))
    assert db.schema_version(backup) == 1
    assert "notes" not in _tables(backup)


def test_available_migrations_are_sorted_numerically_not_lexically(tmp_path):
    for name in ["0010_ten.sql", "0002_two.sql", "0001_one.sql"]:
        (tmp_path / name).write_text("", encoding="utf-8")
    assert [version for version, _ in db.available_migrations(tmp_path)] == [1, 2, 10]


def test_shipped_migrations_start_at_one_and_are_contiguous():
    versions = [version for version, _ in db.available_migrations()]
    assert versions == list(range(1, len(versions) + 1))
