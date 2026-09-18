import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import julius.cli.products as products_cli
from conftest import copied_fixtures, restore_fixture
from _fakes import ScriptedLlmClient
from julius.cli import app
from julius.infra.llm_client import LlmResponse

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "prices.db"))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(sys.modules[__name__], "FIXTURES", copied_fixtures(tmp_path))


def _import(*names: str):
    result = runner.invoke(app, ["importar", *(str(restore_fixture(FIXTURES, name)) for name in names)])
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


def test_produtos_tipo_sets_and_prints_confirmation():
    _import("qrcode.html")
    result = _run("produtos", "tipo", "1", "Refrigerante")
    assert result.exit_code == 0, result.output
    assert "REFRI PEPSI PET 2L" in result.output
    assert 'tipo "refrigerante"' in result.output


def test_produtos_tipo_confirms_the_spelling_it_stored():
    """`set_kind` reuses a spelling that already exists, so the echo has to be read back: asking
    for "ovos" where "ovo" is known stores "ovo", and echoing the argument would hide the grouping
    the command just did."""
    _import("qrcode.html")
    assert _run("produtos", "tipo", "1", "ovo").exit_code == 0

    result = _run("produtos", "tipo", "2", "ovos")

    assert result.exit_code == 0, result.output
    assert 'tipo "ovo"' in result.output


def test_produtos_tipo_remover_clears():
    _import("qrcode.html")
    assert _run("produtos", "tipo", "1", "refrigerante").exit_code == 0
    result = _run("produtos", "tipo", "1", "--remover")
    assert result.exit_code == 0, result.output
    assert "tipo removido" in result.output
    assert "refrigerante" not in _run("produtos", "listar").output


def test_produtos_tipo_both_arg_and_remover_fails():
    _import("qrcode.html")
    result = _run("produtos", "tipo", "1", "refrigerante", "--remover")
    assert result.exit_code == 1
    assert "--remover" in result.stderr
    assert "refrigerante" not in _run("produtos", "listar").output


def test_produtos_tipo_neither_arg_nor_remover_fails():
    _import("qrcode.html")
    result = _run("produtos", "tipo", "1")
    assert result.exit_code == 1
    assert "TIPO" in result.stderr


def test_produtos_tipo_unknown_product_exits_1():
    _import("qrcode.html")
    assert _run("produtos", "tipo", "999", "refrigerante").exit_code == 1
    assert _run("produtos", "tipo", "1", "   ").exit_code == 1


def test_produtos_listar_shows_kind_column():
    _import("qrcode.html")
    assert _run("produtos", "tipo", "1", "refrigerante").exit_code == 0
    output = _run("produtos", "listar").output
    assert "Tipo" in output
    assert "refrigerante" in output


def test_produtos_definir_conteudo_remover_clears():
    _import("qrcode.html")
    assert _run("produtos", "definir-conteudo", "1", "2", "L").exit_code == 0
    assert "Por L" in _run("consultar", "pepsi").output
    result = _run("produtos", "definir-conteudo", "1", "--remover")
    assert result.exit_code == 0, result.output
    assert "conteúdo removido" in result.output
    assert "Por L" not in _run("consultar", "pepsi").output


def test_produtos_definir_conteudo_remover_rejects_extra_arguments():
    _import("qrcode.html")
    assert _run("produtos", "definir-conteudo", "1", "2", "L", "--remover").exit_code == 1
    result = _run("produtos", "definir-conteudo", "1", "2")
    assert result.exit_code == 1
    assert "UNIDADE" in result.stderr


def test_produtos_fundir_does_not_ask_for_confirmation():
    _import("qrcode.html")
    result = _run("produtos", "fundir", "1", "2")  # no input= at all: nothing may block on stdin
    assert result.exit_code == 0, result.output
    assert "fundido em" in result.output
    output = _run("produtos", "listar").output
    assert "REFRI PEPSI PET 2L" not in output
    assert "REFRI ANT GUARANA PET 1.5L" in output


def test_produtos_fundir_prints_the_undo_command():
    _import("qrcode.html")
    result = _run("produtos", "fundir", "1", "2")
    assert "julius produtos desfundir 1" in result.output


def test_produtos_fundir_help_does_not_promise_irreversibility():
    result = _run("produtos", "fundir", "--help")
    assert "Irreversível" not in result.output
    assert "desfundir" in result.output


def test_produtos_fundir_same_id_exits_1():
    _import("qrcode.html")
    result = _run("produtos", "fundir", "1", "1")
    assert result.exit_code == 1
    assert "diferentes" in result.stderr


def test_produtos_desfundir_separates_the_products():
    _import("qrcode.html")
    assert _run("produtos", "fundir", "1", "2").exit_code == 0
    result = _run("produtos", "desfundir", "1")
    assert result.exit_code == 0, result.output
    assert "REFRI PEPSI PET 2L" in result.output
    output = _run("produtos", "listar").output
    assert "REFRI PEPSI PET 2L" in output and "REFRI ANT GUARANA PET 1.5L" in output


def test_produtos_desfundir_rejects_unmerged_and_unknown():
    _import("qrcode.html")
    assert _run("produtos", "desfundir", "1").exit_code == 1
    assert "não está fundido" in _run("produtos", "desfundir", "1").stderr
    assert _run("produtos", "desfundir", "9999").exit_code == 1


def test_produtos_fundir_rejects_a_cycle():
    _import("qrcode.html")
    assert _run("produtos", "fundir", "1", "2").exit_code == 0
    result = _run("produtos", "fundir", "2", "1")
    assert result.exit_code == 1
    assert "já faz parte do grupo" in result.stderr


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
    for command in ("listar", "renomear", "fundir", "tag", "tipo", "definir-conteudo"):
        assert command in products_help


def _tomatoes_in_two_stores() -> tuple[int, int]:
    _import("qrcode.html", "qrcode-3.html")
    output = _run("produtos", "listar").output
    ids = [int(match.group(1)) for match in re.finditer(r"│\s*(\d+)\s*│\s*TOMATE ITALIANO", output)]
    assert len(ids) == 2, output
    return ids[0], ids[1]


def test_comparar_message_when_no_kinds():
    _import("qrcode.html")
    result = _run("mercados", "comparar")
    assert result.exit_code == 0, result.output
    assert "Nenhum produto tem tipo ainda" in result.output
    assert "julius produtos revisar" in result.output


def test_comparar_message_when_no_shared_kind():
    _import("qrcode.html")
    assert _run("produtos", "tipo", "1", "refrigerante").exit_code == 0
    result = _run("mercados", "comparar")
    assert result.exit_code == 0, result.output
    assert "sem base para comparar" in result.output


def test_comparar_says_why_there_is_nothing_to_compare():
    """An empty screen that only says "no base" reads as a broken feature. The funnel is the
    answer: comparing needs one kind in two stores, and here there is a single store."""
    _import("qrcode.html")
    assert _run("produtos", "tipo", "1", "refrigerante").exit_code == 0

    result = _run("mercados", "comparar")

    assert "sem base para comparar" in result.output
    assert "o único tipo comprado saiu de um mercado só" in result.output


def test_comparar_footer_says_how_many_kinds_only_one_store_sells():
    """The question this answers came from real use: "why are so few products compared?". The
    tables can only ever show the kinds bought in two stores — the footer says how many are not."""
    first, second = _tomatoes_in_two_stores()
    for product_id in (first, second):
        assert _run("produtos", "tipo", str(product_id), "tomate").exit_code == 0
    assert _run("produtos", "tipo", "1", "refrigerante").exit_code == 0

    result = _run("mercados", "comparar")

    assert "1 dos 2 tipos comprados em um mercado só" in result.output


def test_comparar_disambiguates_two_stores_sharing_a_nickname():
    """Grouping by CNPJ means two branches can reach the same table under one nickname. Two
    identical rows would be worse than the dropped group, so the CNPJ goes on the label.

    Naming now gives each store its neighbourhood, so a collision no longer happens by itself —
    it takes two branches in the same bairro, or, as here, the same name typed twice by hand.
    """
    first, second = _tomatoes_in_two_stores()
    for product_id in (first, second):
        assert _run("produtos", "tipo", str(product_id), "tomate").exit_code == 0
    for cnpj in ("27289076001379", "11832478000285"):
        assert _run("mercados", "renomear", cnpj, "DONA DE CASA S/A").exit_code == 0

    result = _run("mercados", "comparar")

    assert "DONA DE CASA S/A · 27289076001379" in result.output
    assert "DONA DE CASA S/A · 11832478000285" in result.output


def test_comparar_prints_table_and_orders_cheapest_first():
    first, second = _tomatoes_in_two_stores()
    for product_id in (first, second):
        assert _run("produtos", "tipo", str(product_id), "tomate").exit_code == 0

    result = _run("mercados", "comparar")

    assert result.exit_code == 0, result.output
    assert "tomate · por KG" in result.output
    rows = [line for line in result.output.splitlines() if "R$" in line]
    assert "FL 3 COSTA" in rows[0]
    assert "DONA DE CASA" in rows[1]


def test_comparar_names_the_product_of_each_row():
    """The group label is a kind, so a row's price can belong to a product the user would never
    compare — measured on the real database with `vinho`. The name is what makes that visible."""
    first, second = _tomatoes_in_two_stores()
    for product_id in (first, second):
        assert _run("produtos", "tipo", str(product_id), "tomate").exit_code == 0

    result = _run("mercados", "comparar")

    assert "Produto" in result.output
    assert "UNIAO" in result.output  # only one of the two tomatoes carries the supplier


def test_comparar_footer_shows_group_count_and_period():
    first, second = _tomatoes_in_two_stores()
    for product_id in (first, second):
        assert _run("produtos", "tipo", str(product_id), "tomate").exit_code == 0

    result = _run("mercados", "comparar")

    assert "base: 1 grupo · 07/09/2026 a 12/09/2026" in result.output
    assert "Período largo" in result.output


def test_comparar_tally_counts_only_groups_where_store_appears():
    first, second = _tomatoes_in_two_stores()
    for product_id in (first, second):
        assert _run("produtos", "tipo", str(product_id), "tomate").exit_code == 0

    result = _run("mercados", "comparar")

    assert re.search(r"FL 3 COSTA[^\n]*mais barato em 1 de 1 grupo", result.output)
    assert re.search(r"DONA DE CASA[^\n]*mais barato em 0 de 1 grupo", result.output)


def test_comparar_title_shows_per_content_basis():
    _import("qrcode.html", "qrcode-3.html")
    output = _run("produtos", "listar").output
    pepsi = int(re.search(r"│\s*(\d+)\s*│\s*REFRI PEPSI PET 2L", output).group(1))
    trebeschi = int(re.search(r"│\s*(\d+)\s*│\s*TOMATE TREBESCHI 250G DUO", output).group(1))
    for product_id in (pepsi, trebeschi):
        assert _run("produtos", "tipo", str(product_id), "liquido").exit_code == 0
    assert _run("produtos", "definir-conteudo", str(pepsi), "2", "L").exit_code == 0
    assert _run("produtos", "definir-conteudo", str(trebeschi), "250", "ML").exit_code == 0

    result = _run("mercados", "comparar")

    assert result.exit_code == 0, result.output
    assert "liquido · por L (por conteúdo)" in result.output
