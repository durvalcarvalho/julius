from pathlib import Path

import pytest
from typer.testing import CliRunner

import julius.cli.products as products_cli
from _fakes import ScriptedLlmClient
from julius.cli import app
from julius.infra.llm_client import LlmResponse

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "prices.db"))
    monkeypatch.setenv("COLUMNS", "200")


def _import(*names: str):
    result = runner.invoke(app, ["importar", *(str(FIXTURES / name) for name in names)])
    assert result.exit_code == 0, result.output
    return result


def _run(*args: str, **kwargs):
    return runner.invoke(app, list(args), **kwargs)


def test_mercados_listar_empty_and_after_import():
    assert "Nenhum mercado importado ainda." in _run("mercados", "listar").output
    _import("qrcode.html")
    result = _run("mercados", "listar")
    assert result.exit_code == 0
    assert "27289076001379" in result.output
    assert "FL 3 COSTA MULTICANAL S A" in result.output


def test_mercados_listar_shows_address_column():
    _import("qrcode-3.html")
    result = _run("mercados", "listar")
    assert result.exit_code == 0
    assert "Endereço" in result.output
    assert "GUARA II" in result.output


def test_mercados_renomear_accepts_formatted_cnpj_and_shows_in_listar():
    _import("qrcode.html")
    result = _run("mercados", "renomear", "27.289.076/0013-79", "FL3 Águas Claras")
    assert result.exit_code == 0, result.output
    assert "Mercado 27289076001379 agora é 'FL3 Águas Claras'." in result.output
    assert "FL3 Águas Claras" in _run("mercados", "listar").output


def test_mercados_renomear_unknown_exits_1_with_message():
    result = _run("mercados", "renomear", "00000000000000", "X")
    assert result.exit_code == 1
    assert "00000000000000" in result.stderr


def test_produtos_listar_shows_tags_and_content():
    assert "Nenhum produto importado ainda." in _run("produtos", "listar").output
    _import("qrcode.html")
    assert _run("produtos", "tag", "1", "bebidas").exit_code == 0
    assert _run("produtos", "definir-conteudo", "1", "2", "L").exit_code == 0
    output = _run("produtos", "listar").output
    assert "REFRI PEPSI PET 2L" in output
    assert "bebidas" in output
    assert "2 L" in output


def test_produtos_renomear_and_tag():
    _import("qrcode.html")
    assert "Produto 1 agora é 'Pepsi 2L'." in _run("produtos", "renomear", "1", "Pepsi 2L").output
    assert "marcado com 'bebidas'" in _run("produtos", "tag", "1", " Bebidas ").output
    output = _run("produtos", "listar").output
    assert "Pepsi 2L" in output
    assert "bebidas" in output
    assert _run("produtos", "renomear", "999", "X").exit_code == 1
    assert _run("produtos", "tag", "1", "   ").exit_code == 1


def test_produtos_definir_conteudo_normalizes():
    _import("qrcode.html")
    result = _run("produtos", "definir-conteudo", "1", "500", "g")
    assert result.exit_code == 0, result.output
    assert "0,5 KG" in _run("produtos", "listar").output


def test_produtos_definir_conteudo_bad_unit_exits_1():
    _import("qrcode.html")
    result = _run("produtos", "definir-conteudo", "1", "500", "OZ")
    assert result.exit_code == 1
    assert "OZ" in result.stderr
    assert _run("produtos", "definir-conteudo", "1", "abc", "KG").exit_code == 2


def test_produtos_fundir_asks_confirmation_and_cancels_on_no():
    _import("qrcode.html")
    before = _run("produtos", "listar").output
    result = _run("produtos", "fundir", "1", "2", input="n\n")
    assert result.exit_code == 0, result.output
    assert "Fundir 'REFRI PEPSI PET 2L' em 'REFRI ANT GUARANA PET 1.5L'?" in result.output
    assert "Cancelado." in result.output
    assert _run("produtos", "listar").output == before


def test_produtos_fundir_with_yes_merges():
    _import("qrcode.html")
    result = _run("produtos", "fundir", "1", "2", "--sim")
    assert result.exit_code == 0, result.output
    assert "fundido em" in result.output
    output = _run("produtos", "listar").output
    assert "REFRI PEPSI PET 2L" not in output
    assert "REFRI ANT GUARANA PET 1.5L" in output


def test_produtos_fundir_same_id_exits_1():
    _import("qrcode.html")
    result = _run("produtos", "fundir", "1", "1", "--sim")
    assert result.exit_code == 1
    assert "different" in result.stderr


def test_produtos_comparar_without_ai_shows_env_var_names(monkeypatch):
    for name in ("JULIUS_AI_API_KEY", "JULIUS_AI_BASE_URL", "JULIUS_AI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    _import("qrcode.html")
    before = _run("produtos", "listar").output
    result = _run("produtos", "comparar", "1", "2")
    assert result.exit_code == 0, result.output
    assert "Similaridade de texto" in result.output
    assert "IA indisponível" not in result.output
    assert "Dica:" in result.output and "JULIUS_AI_API_KEY" in result.output
    assert result.output.index("produtos fundir 1 2") < result.output.index("Dica:")
    assert _run("produtos", "listar").output == before


def test_produtos_comparar_unknown_id_exits_1():
    _import("qrcode.html")
    result = _run("produtos", "comparar", "1", "999")
    assert result.exit_code == 1
    assert "999" in result.stderr


def _ai_env(monkeypatch, **extra):
    monkeypatch.setenv("JULIUS_AI_API_KEY", "k")
    monkeypatch.setenv("JULIUS_AI_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("JULIUS_AI_MODEL", "cheap-1")
    monkeypatch.setenv("JULIUS_AI_INPUT_PRICE_USD_PER_1M", "1.0")
    monkeypatch.setenv("JULIUS_AI_OUTPUT_PRICE_USD_PER_1M", "1.0")
    for name, value in extra.items():
        monkeypatch.setenv(name, value)


def _stub_client(monkeypatch, client):
    class Stub:
        @staticmethod
        def from_config(config):
            return client

    monkeypatch.setattr(products_cli, "HttpLlmClient", Stub)


def test_comparar_budget_exhausted_message(monkeypatch):
    _ai_env(monkeypatch, JULIUS_AI_BUDGET_USD="0")
    _stub_client(monkeypatch, ScriptedLlmClient([]))
    _import("qrcode.html")
    result = _run("produtos", "comparar", "1", "2")
    assert result.exit_code == 0, result.output
    assert "orçamento do mês esgotado" in result.output
    assert "US$ 0.00 de US$ 0.00" in result.output


def test_comparar_call_failure_points_to_log(monkeypatch):
    _ai_env(monkeypatch)
    _stub_client(monkeypatch, ScriptedLlmClient([LlmResponse("", 0, 0, error="HTTP 500")]))
    _import("qrcode.html")
    result = _run("produtos", "comparar", "1", "2")
    assert result.exit_code == 0, result.output
    assert "ai_calls.jsonl" in result.output


def test_tag_remover_removes_and_reports():
    _import("qrcode.html")
    _run("produtos", "tag", "1", "bebidas")
    result = _run("produtos", "tag", "1", "bebidas", "--remover")
    assert result.exit_code == 0, result.output
    assert "Tag 'bebidas' removida do produto 1." in result.output
    assert "bebidas" not in _run("produtos", "listar").output


def test_tag_remover_missing_link_exits_1():
    _import("qrcode.html")
    result = _run("produtos", "tag", "1", "bebidas", "--remover")
    assert result.exit_code == 1
    assert "bebidas" in result.stderr


def test_help_shows_subcommands():
    assert "mercados" in _run("--help").output and "produtos" in _run("--help").output
    stores_help = _run("mercados", "--help").output
    assert "listar" in stores_help and "renomear" in stores_help
    products_help = _run("produtos", "--help").output
    for command in ("listar", "renomear", "fundir", "tag", "definir-conteudo"):
        assert command in products_help
