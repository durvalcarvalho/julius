from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from julius.infra import cnpj_client, db

FIXTURES_DIR = Path(__file__).parent / "fixtures"

REAL_AI_OPTION = "--real-ai"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        REAL_AI_OPTION,
        action="store_true",
        default=False,
        help="Roda também os testes marcados `real_ai`, que chamam o modelo de verdade e gastam do orçamento.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skipped with a reason, not deselected: uma suíte que some em silêncio é uma suíte que
    ninguém percebe que parou de rodar."""
    if config.getoption(REAL_AI_OPTION):
        return
    skip = pytest.mark.skip(reason=f"precisa de {REAL_AI_OPTION} (chama o modelo de verdade e gasta do orçamento)")
    for item in items:
        if "real_ai" in item.keywords:
            item.add_marker(skip)


def _wants_real_ai(request: pytest.FixtureRequest) -> bool:
    return request.node.get_closest_marker("real_ai") is not None

ISOLATED_ENV_VARS = (
    "JULIUS_AI_API_KEY",
    "JULIUS_AI_BASE_URL",
    "JULIUS_AI_MODEL",
    "JULIUS_AI_BUDGET_USD",
    "JULIUS_AI_INPUT_PRICE_USD_PER_1M",
    "JULIUS_AI_OUTPUT_PRICE_USD_PER_1M",
    "JULIUS_AI_REQUEST_EXTRAS",
    "JULIUS_BOT_TOKEN",
    "JULIUS_BOT_ALLOWED_CHAT_ID",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Isola os testes de credenciais reais (IA e bot) exportadas no shell do usuário.

    Um teste `real_ai` precisa exatamente do que esta fixture apaga, e é o único que pode pedir."""
    if _wants_real_ai(request):
        return
    for name in ISOLATED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_model_requests(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Nenhum teste fala com um modelo de verdade — irmão de _no_cnpj_lookup. O import é local
    para nada fora de julius/bot/ carregar pydantic_ai no nível do módulo.

    A exceção é `real_ai`, cujo propósito é justamente falar: é o marcador, e só ele, que destrava."""
    if _wants_real_ai(request):
        return
    from pydantic_ai import models

    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture(autouse=True)
def _no_cnpj_lookup(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Nenhum teste consulta o registro de CNPJ de verdade: dar apelido a um mercado não pode
    depender da rede numa rodada de teste. Um teste que queira uma resposta substitui isto."""
    if _wants_real_ai(request):
        return
    monkeypatch.setattr(cnpj_client, "fetch_trade_name", lambda cnpj, **kwargs: None)


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
