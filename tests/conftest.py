from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from julius.infra import db

FIXTURES_DIR = Path(__file__).parent / "fixtures"

AI_ENV_VARS = (
    "JULIUS_AI_API_KEY",
    "JULIUS_AI_BASE_URL",
    "JULIUS_AI_MODEL",
    "JULIUS_AI_BUDGET_USD",
    "JULIUS_AI_INPUT_PRICE_USD_PER_1M",
    "JULIUS_AI_OUTPUT_PRICE_USD_PER_1M",
    "JULIUS_AI_REQUEST_EXTRAS",
)


@pytest.fixture(autouse=True)
def _clean_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isola os testes de credenciais reais de IA exportadas no shell do usuário."""
    for name in AI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def copied_fixtures(tmp_path: Path) -> Path:
    """`julius importar` archives the file it reads, so a CLI test must never hand it the
    repository's own fixtures — it would move them out of the working tree."""
    target = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_DIR, target)
    return target


def restore_fixture(target_dir: Path, name: str) -> Path:
    """Puts a fresh copy back: importing archives the file, so a second import of the same
    receipt needs the file to exist again (the idempotency guarantee is about the database)."""
    path = target_dir / name
    shutil.copy2(FIXTURES_DIR / name, path)
    return path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "prices.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(db_path)
    yield connection
    connection.close()
