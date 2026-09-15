from pathlib import Path

import pytest
from typer.testing import CliRunner

from julius.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "prices.db"))
    monkeypatch.setenv("COLUMNS", "200")


def _import(*names: str):
    return runner.invoke(app, ["importar", *(str(FIXTURES / name) for name in names)])


def _hint_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("Dica:")]


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


def test_consultar_empty_db_shows_import_hint_not_generic_message():
    result = runner.invoke(app, ["consultar", "banana"])
    assert result.exit_code == 0
    assert "julius importar" in result.output
    assert "Nenhum resultado." not in result.output


def test_consultar_did_you_mean():
    _import("qrcode.html")
    result = runner.invoke(app, ["consultar", "pikana"])
    assert result.exit_code == 0
    (hint,) = _hint_lines(result.output)
    assert "PICANHA BOV FAT kg PROMO" in hint
    assert "Nenhum resultado." not in result.output


def test_consultar_unrelated_term_suggests_tags():
    _import("qrcode-3.html")
    runner.invoke(app, ["produtos", "tag", "1", "hortifruti"])
    result = runner.invoke(app, ["consultar", "carne"])
    assert result.exit_code == 0
    (hint,) = _hint_lines(result.output)
    assert "produtos tag" in hint and "consultar --tag" in hint and "hortifruti" in hint


def test_consultar_unknown_tag_lists_existing():
    _import("qrcode.html")
    runner.invoke(app, ["produtos", "tag", "1", "bebidas"])
    result = runner.invoke(app, ["consultar", "--tag", "carne"])
    assert result.exit_code == 0
    (hint,) = _hint_lines(result.output)
    assert "bebidas" in hint and "produtos tag" in hint


def test_consultar_with_results_prints_no_hint():
    _import("qrcode.html")
    result = runner.invoke(app, ["consultar", "picanha"])
    assert result.exit_code == 0
    assert _hint_lines(result.output) == []


def test_importar_first_time_suggests_store_nicknames():
    result = _import("qrcode.html")
    assert result.exit_code == 0
    assert "1 mercado(s)" in result.output and "mercados renomear" in result.output
    runner.invoke(app, ["mercados", "renomear", "27289076001379", "FL 3 Costa"])
    assert _hint_lines(_import("qrcode.html").output) == []


def test_importar_new_products_with_size_suggest_content():
    result = _import("qrcode-5.html")
    assert result.exit_code == 0
    assert "definir-conteudo" in result.output and "+24" in result.output


def test_importar_many_files_prints_hints_once():
    result = _import("qrcode.html", "qrcode-3.html", "qrcode-5.html")
    assert result.exit_code == 0
    assert result.output.count("itens novos") == 3
    assert len(_hint_lines(result.output)) == 2
    assert "3 mercado(s)" in result.output


def test_importar_missing_file_hint_in_stderr(tmp_path):
    result = runner.invoke(app, ["importar", str(tmp_path / "nada.html")])
    assert result.exit_code == 1
    assert "nada.html: erro" in result.stderr
    (hint,) = _hint_lines(result.stderr)
    assert "*.html" in hint
    assert _hint_lines(result.stdout) == []


def test_importar_pdf_or_garbage_explains_not_a_receipt(tmp_path):
    garbage = tmp_path / "pagina.html"
    garbage.write_text("<html><body>nada aqui</body></html>", encoding="utf-8")
    binary = tmp_path / "nota.pdf"
    binary.write_bytes(b"%PDF-1.4\x80\x81\xff")
    result = runner.invoke(app, ["importar", str(garbage), str(binary)])
    assert result.exit_code == 1
    hints = _hint_lines(result.stderr)
    assert len(hints) == 2 and all("Salvar página" in hint for hint in hints)


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
