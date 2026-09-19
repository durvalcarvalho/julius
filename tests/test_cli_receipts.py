import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import julius.cli.receipts as receipts_cli
from conftest import copied_fixtures, restore_fixture
from _fakes import ScriptedLlmClient
from julius.cli import app
from julius.domain.models import PriceExtreme
from julius.infra import db
from julius.infra.llm_client import LlmResponse

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "prices.db"))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(sys.modules[__name__], "FIXTURES", copied_fixtures(tmp_path))


def _import(*names: str):
    return runner.invoke(app, ["importar", *(str(restore_fixture(FIXTURES, name)) for name in names)])


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
    assert "1 mercado ainda com a razão social como nome" in result.output and "mercados renomear" in result.output
    runner.invoke(app, ["mercados", "renomear", "27289076001379", "FL 3 Costa"])
    assert _hint_lines(_import("qrcode.html").output) == []


def test_importar_new_products_with_size_suggest_content():
    result = _import("qrcode-5.html")
    assert result.exit_code == 0
    # PACKAGE_SIZE_IN_DESCRIPTION loses the 2-hint cap to PRODUCTS_PENDING_REVIEW here (ticket 110);
    # `julius produtos revisar` is what actually surfaces package size for these 39 pending products.
    assert "39 produtos novos sem categoria" in result.output
    assert "produtos revisar" in result.output


def test_importar_many_files_prints_hints_once():
    result = _import("qrcode.html", "qrcode-3.html", "qrcode-5.html")
    assert result.exit_code == 0
    assert result.output.count("itens novos") == 3
    assert len(_hint_lines(result.output)) == 2
    assert "3 mercados" in result.output


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
    assert "sem categoria" not in result.output  # the pending-review hint, not the audit pointer


def test_importar_without_ai_prints_pending_review_hint():
    result = _import("qrcode-2.html")
    assert result.exit_code == 0
    assert "Dica: 1 produto novo sem categoria" in result.output
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
    assert "produto novo sem categoria" in result.output


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
    assert "39 produtos novos sem categoria" in without_ai.output

    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "b.db"))
    _ai_env(monkeypatch)
    items = [{"id": i, "readable_name": f"N{i}", "tags": ["mercearia"], "content": None} for i in range(1, 40)]
    _stub_client(monkeypatch, ScriptedLlmClient(by_kind={"enrich": _enrich(items)}))

    with_ai = _import("qrcode-5.html")

    assert "definir-conteudo ID QTD UNIDADE" not in with_ai.output  # the hint, not the undo line
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
    assert first["result_count"] == 1  # the three picanha pieces share one price
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


def _extreme(name: str, highlight: str = "lowest", price: float = 1.0, **overrides) -> PriceExtreme:
    values = dict(
        product_name=name,
        store_nickname="Loja",
        unit="KG",
        price=price,
        highlight=highlight,
        basis="unit_price",
        content_unit=None,
        previous_price=price * 2,
        previous_store="Outra",
        previous_at="2026-09-04T10:00:00",
        previous_product_name=name,  # beat itself; pass an override to exercise the other branch
        scope=name,
    )
    values.update(overrides)
    return PriceExtreme(**values)


def _tomato_review(monkeypatch, product_id: int):
    _ai_env(monkeypatch)
    _stub_client(
        monkeypatch,
        ScriptedLlmClient(
            by_kind={
                "enrich": _enrich(
                    [{"id": product_id, "readable_name": "Tomate Italiano União", "tags": ["hortifruti"], "kind": "tomate"}]
                ),
                "merge": _merge([]),
            }
        ),
    )


def test_import_prints_new_low_signal(monkeypatch):
    _import("qrcode-3.html")
    assert runner.invoke(app, ["produtos", "tipo", "4", "tomate"]).exit_code == 0
    _tomato_review(monkeypatch, 19)

    result = _import("qrcode.html")

    assert result.exit_code == 0, result.output
    assert "Nesta compra:" in result.output
    signal = next(line for line in result.output.splitlines() if "↓" in line)
    assert "Tomate Italiano União" in signal
    assert "R$ 11,89/KG" in signal
    assert "menor preço já pago" in signal
    assert "R$ 14,99" in signal and "DONA DE CASA" in signal


def test_import_signal_runs_after_review(monkeypatch):
    """Proves the order: without the review assigning the kind first, the new product would only
    be compared against its own (empty) history and no cross-store signal would exist."""
    _import("qrcode-3.html")
    assert runner.invoke(app, ["produtos", "tipo", "4", "tomate"]).exit_code == 0
    _tomato_review(monkeypatch, 19)

    with_review = _import("qrcode.html").output

    assert "07/09/2026" in next(line for line in with_review.splitlines() if "↓" in line)


def test_import_prints_nothing_without_extremes():
    result = _import("qrcode.html")
    assert result.exit_code == 0
    assert "Nesta compra:" not in result.output


def test_import_limits_signal_to_five_lines(monkeypatch):
    extremes = [_extreme(f"Produto {i}", price=float(i + 1)) for i in range(7)]
    monkeypatch.setattr(receipts_cli.comparison_service, "new_extremes", lambda conn, keys: extremes)

    result = _import("qrcode-2.html")

    assert result.exit_code == 0, result.output
    assert len([line for line in result.output.splitlines() if "↓" in line]) == 5
    assert "+2 mais" in result.output


def test_import_signal_shows_per_content_suffix(monkeypatch):
    extreme = _extreme("Água 1,5L", unit="UN", price=2.46, basis="price_per_content", content_unit="L")
    monkeypatch.setattr(receipts_cli.comparison_service, "new_extremes", lambda conn, keys: [extreme])

    result = _import("qrcode-2.html")

    assert "R$ 2,46/L (por conteúdo)" in result.output


def test_import_signal_names_the_beaten_product(monkeypatch):
    """Over a kind, the record can belong to another product: the real 16/09 receipt announced
    "menor preço já pago" for a frisante that beat a Norton, and said only the price."""
    extreme = _extreme("Vinho Mioranza frisante", previous_product_name="Vinho Norton 750ml BC SV")
    monkeypatch.setattr(receipts_cli.comparison_service, "new_extremes", lambda conn, keys: [extreme])

    result = _import("qrcode-2.html")

    assert "(Vinho Norton 750ml BC SV)" in result.output


def test_import_signal_does_not_repeat_a_product_that_beat_itself(monkeypatch):
    """The common case — bought again, cheaper than last time. `_extreme` defaults both names to
    the same product, so this asserts the default path stays quiet."""
    monkeypatch.setattr(
        receipts_cli.comparison_service, "new_extremes", lambda conn, keys: [_extreme("Cebola")]
    )

    result = _import("qrcode-2.html")

    assert "↓ Cebola" in result.output
    assert "(Cebola)" not in result.output


def test_import_no_signal_when_all_files_fail(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(receipts_cli.comparison_service, "new_extremes", lambda conn, keys: calls.append(keys) or [])
    garbage = tmp_path / "pagina.html"
    garbage.write_text("<html><body>nada aqui</body></html>", encoding="utf-8")

    result = runner.invoke(app, ["importar", str(garbage)])

    assert result.exit_code == 1
    assert calls == []
    assert "Nesta compra:" not in result.output


def test_search_shows_weekday_column():
    _import("qrcode.html")  # 2026-09-12 was a Saturday
    result = runner.invoke(app, ["consultar", "picanha"])
    assert result.exit_code == 0, result.output
    assert "Dia" in result.output
    assert "sab" in result.output


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        ("2026-09-14", "seg"),
        ("2026-09-15", "ter"),
        ("2026-09-16", "qua"),
        ("2026-09-17", "qui"),
        ("2026-09-18", "sex"),
        ("2026-09-19", "sab"),
        ("2026-09-20", "dom"),
    ],
)
def test_search_weekday_for_all_days(date, expected):
    assert receipts_cli._weekday(f"{date}T10:00:00") == expected


def test_search_tolerates_bad_purchased_at():
    _import("qrcode.html")
    conn = db.connect(Path(os.environ["JULIUS_DB"]))
    conn.execute("UPDATE prices SET purchased_at = 'ontem de manhã'")
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["consultar", "picanha"])

    assert result.exit_code == 0, result.output
    assert "PICANHA" in result.output


def _inbox(tmp_path) -> Path:
    path = tmp_path / "entrada"
    path.mkdir(exist_ok=True)
    return path


def _into_inbox(tmp_path, *names: str) -> Path:
    inbox = _inbox(tmp_path)
    for name in names:
        shutil.copy2(Path(__file__).parent / "fixtures" / name, inbox / name)
    return inbox


def test_import_without_args_scans_inbox(tmp_path):
    _into_inbox(tmp_path, "qrcode-2.html", "qrcode-3.html")

    result = runner.invoke(app, ["importar"])

    assert result.exit_code == 0, result.output
    assert result.output.index("qrcode-2.html") < result.output.index("qrcode-3.html")
    assert "1 itens novos" in result.output and "6 itens novos" in result.output


def test_import_without_args_missing_inbox_message():
    result = runner.invoke(app, ["importar"])
    assert result.exit_code == 0, result.output
    assert "make inbox" in result.output
    assert runner.invoke(app, ["produtos", "listar"]).output.startswith("Nenhum produto")


def test_import_without_args_empty_inbox_message(tmp_path):
    _inbox(tmp_path)
    result = runner.invoke(app, ["importar"])
    assert result.exit_code == 0, result.output
    assert "Nada para importar" in result.output


def test_import_without_args_ignores_archive_subdir(tmp_path):
    inbox = _into_inbox(tmp_path, "qrcode-2.html")
    archive = inbox / "importados"
    archive.mkdir()
    shutil.move(str(inbox / "qrcode-2.html"), archive / "2026-09-05_key.html")

    result = runner.invoke(app, ["importar"])

    assert result.exit_code == 0, result.output
    assert "Nada para importar" in result.output


def test_import_archives_on_success(tmp_path):
    inbox = _into_inbox(tmp_path, "qrcode-2.html")

    result = runner.invoke(app, ["importar"])

    assert result.exit_code == 0, result.output
    assert "arquivado como" in result.output
    assert not (inbox / "qrcode-2.html").exists()
    (archived,) = list((inbox / "importados").iterdir())
    assert archived.name.startswith("2026-09-05_") and archived.name.endswith(".html")


def test_import_failure_keeps_file_in_place(tmp_path):
    inbox = _inbox(tmp_path)
    (inbox / "lixo.html").write_text("<html><body>nada aqui</body></html>", encoding="utf-8")

    result = runner.invoke(app, ["importar"])

    assert result.exit_code == 1
    assert (inbox / "lixo.html").exists()
    assert not (inbox / "importados").exists()


def test_import_batch_partial_failure_archives_the_good_ones(tmp_path):
    inbox = _into_inbox(tmp_path, "qrcode-2.html")
    (inbox / "lixo.html").write_text("<html><body>nada aqui</body></html>", encoding="utf-8")

    result = runner.invoke(app, ["importar"])

    assert result.exit_code == 1
    assert (inbox / "lixo.html").exists()
    assert not (inbox / "qrcode-2.html").exists()
    assert len(list((inbox / "importados").iterdir())) == 1


def test_import_archive_failure_does_not_fail_command(tmp_path):
    inbox = _into_inbox(tmp_path, "qrcode-2.html")
    (inbox / "importados").write_text("um arquivo no lugar da pasta", encoding="utf-8")

    result = runner.invoke(app, ["importar"])

    assert result.exit_code == 0, result.output
    assert "não foi possível arquivar" in result.stderr
    assert runner.invoke(app, ["consultar", "picanha"]).exit_code == 0
    assert "1 itens novos" in result.output


def test_import_with_explicit_paths_still_archives(tmp_path):
    loose = tmp_path / "Downloads"
    loose.mkdir()
    shutil.copy2(Path(__file__).parent / "fixtures" / "qrcode-2.html", loose / "qrcode.html")

    result = runner.invoke(app, ["importar", str(loose / "qrcode.html")])

    assert result.exit_code == 0, result.output
    assert "arquivado como" in result.output
    assert not (loose / "qrcode.html").exists()
    assert len(list((tmp_path / "entrada" / "importados").iterdir())) == 1


def _content(product_id: int, quantity: str, unit: str) -> None:
    result = runner.invoke(app, ["produtos", "definir-conteudo", str(product_id), quantity, unit])
    assert result.exit_code == 0, result.output


def _consultar(*words: str) -> str:
    result = runner.invoke(app, ["consultar", *words])
    assert result.exit_code == 0, result.output
    return result.output


def test_consultar_prints_the_cheapest_per_litre():
    _import("qrcode.html")
    _content(1, "2", "L")
    _content(2, "1.5", "L")

    output = _consultar("refri")

    assert "Mais barato por litro:" in output
    assert "R$ 3,33/L" in output and "R$ 3,50/L" in output  # 4,99 / 1,5L beats 6,99 / 2L


def test_consultar_says_unidade_for_un_content():
    """The word comes from content_unit, not from the product. A 2L bottle with content "2 UN" is
    nonsense on purpose: it is the shortest way to exercise the UN branch with the real fixtures."""
    _import("qrcode.html")
    _content(1, "2", "UN")
    _content(2, "3", "UN")
    assert "Mais barato por unidade:" in _consultar("refri")


def test_consultar_no_line_for_a_time_series():
    _import("qrcode.html")
    _content(12, "1", "KG")
    assert "Mais barato por" not in _consultar("picanha")


def test_consultar_no_line_for_kg_group():
    _import("qrcode.html")
    assert "Mais barato por" not in _consultar("tomate")


def test_consultar_no_line_when_only_one_has_content():
    _import("qrcode.html")
    _content(1, "2", "L")
    assert "Mais barato por" not in _consultar("refri")


def test_consultar_no_line_when_prices_per_content_are_equal():
    _import("qrcode.html")
    _content(1, "6.99", "L")
    _content(2, "4.99", "L")
    assert "Mais barato por" not in _consultar("refri")
