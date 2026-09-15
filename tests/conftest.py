from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from julius.infra import db

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "prices.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(db_path)
    yield connection
    connection.close()
