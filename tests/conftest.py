from __future__ import annotations

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


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "prices.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(db_path)
    yield connection
    connection.close()
