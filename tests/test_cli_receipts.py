import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

import julius.cli.receipts as receipts_cli
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
    return runner.invoke(app, ["importar", *(str(FIXTURES / name) for name in names)])


def _hint_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("Dica:")]


def _product_id(name_fragment: str) -> int:
    output = runner.invoke(app, ["produtos", "listar"]).output
    match = re.search(r"│\s*(\d+)\s*│[^│]*" + re.escape(name_fragment), output)
    assert match, f"{name_fragment!r} not found in:\n{output}"
    return int(match.group(1))


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

    monkeypatch.setattr(receipts_cli, "HttpLlmClient", Stub)


def _enrich(items: list[dict], input_tokens: int = 1000, output_tokens: int = 500) -> LlmResponse:
    return LlmResponse(json.dumps({"products": items}), input_tokens, output_tokens)


def _merge(items: list[dict], input_tokens: int = 1000, output_tokens: int = 500) -> LlmResponse:
    return LlmResponse(json.dumps({"pairs": items}), input_tokens, output_tokens)


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
    # NO_MATCH_TRY_TAGS lists the first 5 known tags (migration 0002 seed), not just used ones.
    assert "produtos tag" in hint and "consultar --tag" in hint and "bebidas" in hint


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


def test_consultar_shows_store_address_under_nickname():
    _import("qrcode-3.html")
    result = runner.invoke(app, ["consultar", "tomate"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    nickname_line = next(i for i, line in enumerate(lines) if "DONA DE CASA S/A" in line)
    assert "GUARA II" in lines[nickname_line + 1]


def test_consultar_ai_fallback_finds_products_and_prints_hint(monkeypatch):
    _import("qrcode.html")
    picanha_id = _product_id("PICANHA")
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient([LlmResponse(json.dumps({"ids": [picanha_id]}), 10, 5)])
    _stub_client(monkeypatch, fake)

    result = runner.invoke(app, ["consultar", "carnes"])

    assert result.exit_code == 0, result.output
    assert "Preços por KG" in result.output
    assert "PICANHA" in result.output
    assert any("Encontrado pela IA" in hint for hint in _hint_lines(result.output))
    assert len(fake.calls) == 1


def test_consultar_does_not_call_ai_when_there_are_results(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient([])
    _stub_client(monkeypatch, fake)

    result = runner.invoke(app, ["consultar", "picanha"])

    assert result.exit_code == 0
    assert fake.calls == []


def test_consultar_ai_fallback_with_no_ids_keeps_regular_hints(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient([LlmResponse(json.dumps({"ids": []}), 10, 5)])
    _stub_client(monkeypatch, fake)

    result = runner.invoke(app, ["consultar", "carnes"])

    assert result.exit_code == 0
    (hint,) = _hint_lines(result.output)
    assert "produtos tag" in hint


def test_consultar_with_tag_never_calls_ai(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient([LlmResponse(json.dumps({"ids": []}), 10, 5)])
    _stub_client(monkeypatch, fake)

    result = runner.invoke(app, ["consultar", "carnes", "--tag", "x"])

    assert result.exit_code == 0
    assert fake.calls == []


def test_consultar_without_ai_configured_is_unchanged():
    _import("qrcode.html")
    result = runner.invoke(app, ["consultar", "carnes"])
    assert result.exit_code == 0
    (hint,) = _hint_lines(result.output)
    assert "produtos tag" in hint


def test_importar_first_time_suggests_store_nicknames():
    result = _import("qrcode.html")
    assert result.exit_code == 0
    assert "1 mercado(s)" in result.output and "mercados renomear" in result.output
    runner.invoke(app, ["mercados", "renomear", "27289076001379", "FL 3 Costa"])
    assert _hint_lines(_import("qrcode.html").output) == []


def test_importar_new_products_with_size_suggest_content():
    result = _import("qrcode-5.html")
    assert result.exit_code == 0
    # PACKAGE_SIZE_IN_DESCRIPTION loses the 2-hint cap to PRODUCTS_PENDING_REVIEW here (ticket 110);
    # `julius produtos revisar` is what actually surfaces package size for these 39 pending products.
    assert "39 produto(s) novo(s) sem categoria" in result.output
    assert "produtos revisar" in result.output


def test_importar_many_files_prints_hints_once():
    result = _import("qrcode.html", "qrcode-3.html", "qrcode-5.html")
    assert result.exit_code == 0
    assert result.output.count("itens novos") == 3
    assert len(_hint_lines(result.output)) == 2
    assert "3 mercado(s)" in result.output


def test_importar_reviews_new_products_when_ai_is_configured(monkeypatch):
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 1, "readable_name": "Nome Legível", "tags": ["mercearia"], "content": None}])}
    )
    _stub_client(monkeypatch, fake)

    result = _import("qrcode-2.html")

    assert result.exit_code == 0, result.output
    assert "Aplicado:" in result.output
    listar = runner.invoke(app, ["produtos", "listar"]).output
    assert "Nome Legível" in listar and "mercearia" in listar
    assert "produtos revisar" not in result.output


def test_importar_without_ai_prints_pending_review_hint():
    result = _import("qrcode-2.html")
    assert result.exit_code == 0
    assert "Dica: 1 produto(s) novo(s) sem categoria" in result.output
    assert "julius produtos revisar" in result.output


def test_importar_reimport_does_not_call_ai(monkeypatch):
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 1, "readable_name": "X", "tags": ["mercearia"], "content": None}])}
    )
    _stub_client(monkeypatch, fake)
    _import("qrcode-2.html")
    fake.calls.clear()

    _import("qrcode-2.html")

    assert fake.calls == []


def test_importar_sim_applies_ambiguous_tag_without_prompt(monkeypatch):
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 1, "readable_name": "X", "tags": ["mercearia", "bebidas"], "content": None}])}
    )
    _stub_client(monkeypatch, fake)

    result = runner.invoke(app, ["importar", str(FIXTURES / "qrcode-2.html"), "--sim"])

    assert result.exit_code == 0, result.output
    assert "mercearia" in runner.invoke(app, ["produtos", "listar"]).output


def test_importar_multiple_files_reviews_once_at_the_end(monkeypatch):
    _ai_env(monkeypatch)
    items = [{"id": i, "readable_name": f"N{i}", "tags": ["mercearia"], "content": None} for i in range(1, 21)]
    fake = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(items),
            "merge": _merge([{"id": 1, "rationale": "mesma variedade", "same_product": True, "confidence": 0.9}]),
        }
    )
    _stub_client(monkeypatch, fake)

    result = runner.invoke(app, ["importar", str(FIXTURES / "qrcode.html"), str(FIXTURES / "qrcode-3.html")])

    assert result.exit_code == 0, result.output
    assert len(fake.calls) <= 2
    assert result.output.count("Aplicado:") == 1


def test_importar_ai_failure_keeps_import_and_exit_0(monkeypatch):
    _ai_env(monkeypatch)
    error = LlmResponse("", 0, 0, error="HTTP 500")
    _stub_client(monkeypatch, ScriptedLlmClient(by_kind={"enrich": [error, error]}))

    result = _import("qrcode-2.html")

    assert result.exit_code == 0, result.output
    assert "1 itens novos" in result.output
    assert "IA não respondeu" in result.output
    assert "produto(s) novo(s) sem categoria" in result.output


def test_importar_bad_file_still_exits_1_after_review(monkeypatch, tmp_path):
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 1, "readable_name": "X", "tags": ["mercearia"], "content": None}])}
    )
    _stub_client(monkeypatch, fake)
    missing = tmp_path / "nao-existe.html"

    result = runner.invoke(app, ["importar", str(missing), str(FIXTURES / "qrcode-2.html")])

    assert result.exit_code == 1
    assert "Aplicado:" in result.output
    assert len(fake.calls) >= 1


def test_importar_package_size_hint_only_without_review(monkeypatch, tmp_path):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "a.db"))
    without_ai = _import("qrcode-5.html")
    assert "39 produto(s) novo(s) sem categoria" in without_ai.output

    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "b.db"))
    _ai_env(monkeypatch)
    items = [{"id": i, "readable_name": f"N{i}", "tags": ["mercearia"], "content": None} for i in range(1, 40)]
    _stub_client(monkeypatch, ScriptedLlmClient(by_kind={"enrich": _enrich(items)}))

    with_ai = _import("qrcode-5.html")

    assert "definir-conteudo" not in with_ai.output
    assert "sem categoria" not in with_ai.output


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


def test_consultar_accepts_multiple_words_without_quotes():
    _import("qrcode.html")
    result = runner.invoke(app, ["consultar", "picanha", "bov"])
    assert result.exit_code == 0, result.output
    assert "PICANHA" in result.output


def test_consultar_detects_tag_in_free_text_without_tag_flag():
    _import("qrcode.html")
    picanha_id = _product_id("PICANHA")
    runner.invoke(app, ["produtos", "tag", str(picanha_id), "carnes"])
    result = runner.invoke(app, ["consultar", "carnes"])
    assert result.exit_code == 0, result.output
    assert "PICANHA" in result.output


def test_sem_tag_forces_plain_term_search():
    _import("qrcode.html")
    picanha_id = _product_id("PICANHA")
    runner.invoke(app, ["produtos", "tag", str(picanha_id), "carnes"])

    with_detection = runner.invoke(app, ["consultar", "carnes"])
    without_detection = runner.invoke(app, ["consultar", "carnes", "--sem-tag"])

    assert "PICANHA" in with_detection.output
    assert "PICANHA" not in without_detection.output


def test_explicit_tag_still_intersects_with_term():
    _import("qrcode.html")
    picanha_id = _product_id("PICANHA")
    runner.invoke(app, ["produtos", "tag", str(picanha_id), "carnes"])
    result = runner.invoke(app, ["consultar", "picanha", "--tag", "carnes"])
    assert result.exit_code == 0, result.output
    assert "PICANHA" in result.output


def test_consultar_ai_fallback_fires_even_when_word_auto_detects_as_tag(monkeypatch):
    _import("qrcode.html")
    picanha_id = _product_id("PICANHA")
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient([LlmResponse(json.dumps({"ids": [picanha_id]}), 10, 5)])
    _stub_client(monkeypatch, fake)

    result = runner.invoke(app, ["consultar", "hortifruti"])  # auto-detects the tag; retry as term is also empty

    assert result.exit_code == 0, result.output
    assert "PICANHA" in result.output
    assert len(fake.calls) == 1


def test_consultar_help_lists_sem_tag_flag():
    result = runner.invoke(app, ["consultar", "--help"])
    assert result.exit_code == 0
    assert "--sem-tag" in result.output


def test_consultar_logs_one_line_per_call(tmp_path):
    _import("qrcode.html")
    runner.invoke(app, ["consultar", "picanha"])
    runner.invoke(app, ["consultar", "banana"])
    lines = (tmp_path / "query_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["words"] == ["picanha"]
    assert first["result_count"] == 3
    assert first["tag_used"] is None
    assert first["ai_fallback"] is False


def test_consultar_logs_zero_results_without_raising(tmp_path):
    runner.invoke(app, ["consultar", "banana"])
    lines = (tmp_path / "query_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["result_count"] == 0


def test_consultar_logs_ai_fallback_flag(tmp_path, monkeypatch):
    _import("qrcode.html")
    picanha_id = _product_id("PICANHA")
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient([LlmResponse(json.dumps({"ids": [picanha_id]}), 10, 5)])
    _stub_client(monkeypatch, fake)

    runner.invoke(app, ["consultar", "carnes"])

    lines = (tmp_path / "query_log.jsonl").read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    assert last["ai_fallback"] is True
    assert last["detected_tag"] == "carnes"
