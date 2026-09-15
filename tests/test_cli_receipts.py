from pathlib import Path

import pytest
from typer.testing import CliRunner

from julius.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "prices.db"))


def _import(*names: str):
    return runner.invoke(app, ["importar", *(str(FIXTURES / name) for name in names)])


def test_importar_prints_per_file_summary():
    result = _import("qrcode.html")
    assert result.exit_code == 0, result.output
    assert "qrcode.html: 20 itens novos, 0 já existiam" in result.output


def test_importar_twice_reports_existing():
    _import("qrcode.html")
    result = _import("qrcode.html")
    assert result.exit_code == 0
    assert "0 itens novos, 20 já existiam" in result.output


def test_importar_continues_after_bad_file_and_exits_1(tmp_path):
    missing = tmp_path / "inexistente.html"
    result = runner.invoke(app, ["importar", str(missing), str(FIXTURES / "qrcode-2.html")])
    assert result.exit_code == 1
    assert "inexistente.html: erro" in result.stderr
    assert "qrcode-2.html: 1 itens novos, 0 já existiam" in result.output


def test_consultar_requires_term_or_tag():
    result = runner.invoke(app, ["consultar"])
    assert result.exit_code == 2
    assert "termo" in result.output.lower() or "termo" in result.stderr.lower()


def test_consultar_shows_table_per_unit():
    _import("qrcode.html")
    result = runner.invoke(app, ["consultar", "picanha"])
    assert result.exit_code == 0, result.output
    assert "PICANHA" in result.output
    assert "Preços por KG" in result.output
    assert "Preços por UN" not in result.output


def test_consultar_no_results_message():
    _import("qrcode.html")
    result = runner.invoke(app, ["consultar", "xyzabc"])
    assert result.exit_code == 0
    assert "Nenhum resultado." in result.output


def test_consultar_on_empty_db_explains_how_to_start():
    result = runner.invoke(app, ["consultar", "banana"])
    assert result.exit_code == 0
    assert "Nenhum recibo importado ainda" in result.output
    assert "julius importar" in result.output
    assert "Nenhum resultado." not in result.output


def test_exportar_writes_file_and_reports_count(tmp_path):
    _import("qrcode.html")
    output = tmp_path / "out" / "precos.csv"
    result = runner.invoke(app, ["exportar", "--saida", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "20 linhas" in result.output


def test_help_lists_the_three_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("importar", "consultar", "exportar"):
        assert command in result.output
