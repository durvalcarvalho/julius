from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn, db_path)
    return conn


def available_migrations(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    return sorted((int(path.name.split("_", 1)[0]), path) for path in directory.glob("*.sql"))


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def apply_migrations(
    conn: sqlite3.Connection,
    db_path: Path,
    migrations: list[tuple[int, Path]] | None = None,
) -> None:
    migrations = available_migrations() if migrations is None else migrations
    current = schema_version(conn)
    pending = [(version, path) for version, path in migrations if version > current]
    if not pending:
        return
    if current > 0:
        # Real schema change on a database that already holds data: keep a copy first.
        shutil.copy2(db_path, db_path.with_name(f"{db_path.name}.bak-v{current}"))
    for version, path in pending:
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
