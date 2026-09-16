import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import julius.cli.products as products_cli
from conftest import copied_fixtures, restore_fixture
from _fakes import RaisingLlmClient, ScriptedLlmClient
from julius.cli import _review, app
from julius.domain.models import AppliedAction
from julius.infra.llm_client import LlmResponse

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "prices.db"))
    monkeypatch.setenv("COLUMNS", "220")
    monkeypatch.setattr(sys.modules[__name__], "FIXTURES", copied_fixtures(tmp_path))


def _run(*args: str, **kwargs):
    return runner.invoke(app, list(args), **kwargs)


def _import(*names: str):
    result = _run("importar", *(str(restore_fixture(FIXTURES, name)) for name in names))
    assert result.exit_code == 0, result.output
    return result


def _ai_env(monkeypatch, **extra):
    monkeypatch.setenv("JULIUS_AI_API_KEY", "k")
    monkeypatch.setenv("JULIUS_AI_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("JULIUS_AI_MODEL", "cheap-1")
    monkeypatch.setenv("JULIUS_AI_INPUT_PRICE_USD_PER_1M", "1.0")
    monkeypatch.setenv("JULIUS_AI_OUTPUT_PRICE_USD_PER_1M", "1.0")
    monkeypatch.setenv("JULIUS_AI_BUDGET_USD", "5.0")
    for name, value in extra.items():
        monkeypatch.setenv(name, value)


def _enrich(items: list[dict], input_tokens: int = 1000, output_tokens: int = 500) -> LlmResponse:
    return LlmResponse(json.dumps({"products": items}), input_tokens, output_tokens)


def _merge(items: list[dict], input_tokens: int = 1000, output_tokens: int = 500) -> LlmResponse:
    return LlmResponse(json.dumps({"pairs": items}), input_tokens, output_tokens)


def _actions(tmp_path) -> list[dict]:
    path = tmp_path / "actions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _stub_client(monkeypatch, client):
    class Stub:
        @staticmethod
        def from_config(config):
            return client

    monkeypatch.setattr(products_cli, "HttpLlmClient", Stub)


def test_revisar_applies_readable_names_and_single_known_tags_without_prompt(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Linguiça de frango Aurora", "tags": ["carnes"], "content": None}])}
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    assert "Aplicado: 1 nome(s), 1 categoria(s)." in result.output
    output = _run("produtos", "listar").output
    assert "Linguiça de frango Aurora" in output
    assert "carnes" in output


def test_revisar_prints_table_with_cupom_and_new_name_columns(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Linguiça de frango Aurora", "tags": ["carnes"], "content": None}])}
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert "Cupom" in result.output and "Nome" in result.output
    assert "LING FGO RESF AURORA kg" in result.output
    assert "Linguiça de frango Aurora" in result.output


def test_revisar_prompts_for_ambiguous_tag_and_applies_choice(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia", "bebidas"], "content": None}])}
    )
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)

    result = _run("produtos", "revisar", input="1\n")

    assert result.exit_code == 0, result.output
    assert "mercearia" in _run("produtos", "listar").output


def test_revisar_other_option_creates_new_tag(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia", "bebidas"], "content": None}])}
    )
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)

    result = _run("produtos", "revisar", input="3\novos\n")

    assert result.exit_code == 0, result.output
    output = _run("produtos", "listar").output
    assert "ovos" in output


def test_revisar_enter_skips_and_reports_pending(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia", "bebidas"], "content": None}])}
    )
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)

    result = _run("produtos", "revisar", input="\n")

    assert result.exit_code == 0, result.output
    assert "Pendentes: 1 produto(s) sem categoria." in result.output


def test_revisar_applies_content_without_asking(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [{"id": 8, "readable_name": "Ovo Grande", "tags": ["hortifruti"], "content": {"quantity": 30, "unit": "UN"}}]
            )
        }
    )
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    assert "definir conteúdo" not in result.output
    assert "30 UN" in _run("produtos", "listar").output


def test_revisar_applies_kind_automatically(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [{"id": 11, "readable_name": "Linguiça", "tags": ["carnes"], "content": None, "kind": "Linguiça"}]
            )
        }
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    assert "linguiça" in _run("produtos", "listar").output


def test_revisar_logs_one_line_per_action(monkeypatch, tmp_path):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [
                    {
                        "id": 8,
                        "readable_name": "Ovo Grande",
                        "tags": ["hortifruti"],
                        "content": {"quantity": 30, "unit": "UN"},
                        "kind": "ovo",
                    }
                ]
            )
        }
    )
    _stub_client(monkeypatch, client)

    assert _run("produtos", "revisar").exit_code == 0

    records = _actions(tmp_path)
    assert [record["field"] for record in records] == ["name", "tag", "content", "kind"]
    assert all(record["product_id"] == 8 for record in records)
    assert all(record["at"] and record["undo"] for record in records)


def test_revisar_undo_command_for_kind_without_previous(monkeypatch, tmp_path):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Linguiça", "tags": ["carnes"], "kind": "linguiça"}])}
    )
    _stub_client(monkeypatch, client)

    assert _run("produtos", "revisar").exit_code == 0

    (kind_action,) = [record for record in _actions(tmp_path) if record["field"] == "kind"]
    assert kind_action["undo"] == "julius produtos tipo 11 --remover"
    assert kind_action["before"] is None


def test_undo_command_per_field():
    # content/kind with a previous value can only come from curation.apply directly (propose never
    # re-proposes what a product already has), so the mapping is unit-tested here.
    assert _review._undo_command(AppliedAction(7, "name", "LING FGO", "Linguiça")) == (
        'julius produtos renomear 7 "LING FGO"'
    )
    assert _review._undo_command(AppliedAction(7, "tag", None, "carnes")) == "julius produtos tag 7 carnes --remover"
    assert _review._undo_command(AppliedAction(7, "content", None, "30 UN")) == (
        "julius produtos definir-conteudo 7 --remover"
    )
    assert _review._undo_command(AppliedAction(7, "content", "2 L", "1.5 L")) == (
        "julius produtos definir-conteudo 7 2 L"
    )
    assert _review._undo_command(AppliedAction(7, "kind", None, "uva")) == "julius produtos tipo 7 --remover"
    assert _review._undo_command(AppliedAction(7, "kind", "uva", "uva verde")) == 'julius produtos tipo 7 "uva"'


def test_revisar_summary_counts_by_field(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [
                    {
                        "id": 8,
                        "readable_name": "Ovo Grande",
                        "tags": ["hortifruti"],
                        "content": {"quantity": 30, "unit": "UN"},
                        "kind": "ovo",
                    }
                ]
            )
        }
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert "Aplicado: 1 nome(s), 1 categoria(s), 1 conteúdo(s), 1 tipo(s)." in result.output
    assert "julius produtos definir-conteudo 8 30 UN" not in result.output


def test_revisar_summary_omits_zero_counts(monkeypatch):
    _import("qrcode.html")
    assert _run("produtos", "tag", "11", "carnes").exit_code == 0
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia", "bebidas"]}])}
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert "Aplicado: 1 nome(s)." in result.output
    assert "conteúdo" not in result.output and "tipo(s)" not in result.output


def test_revisar_survives_unwritable_log(monkeypatch, tmp_path):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    (tmp_path / "actions.jsonl").mkdir()  # a directory where the log file should go
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Linguiça", "tags": ["carnes"], "kind": "linguiça"}])}
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    assert "linguiça" in _run("produtos", "listar").output


def test_revisar_non_interactive_without_sim_applies_only_auto_and_prints_content_commands(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [
                    {"id": 11, "readable_name": "Linguiça de frango Aurora", "tags": ["carnes"], "content": None},
                    {"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia", "bebidas"], "content": None},
                    {"id": 5, "readable_name": "Ovo Grande", "tags": ["hortifruti"], "content": {"quantity": 30, "unit": "UN"}},
                ]
            )
        }
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    assert "Pendentes: 1 produto(s) sem categoria." in result.output
    output = _run("produtos", "listar").output
    assert "carnes" in output and "hortifruti" in output
    assert "30 UN" in output


def test_revisar_sim_applies_first_tag_even_if_unknown(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [
                    {"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia", "bebidas"], "content": None},
                    {"id": 5, "readable_name": "Ovo Grande", "tags": ["hortifruti"], "content": {"quantity": 30, "unit": "UN"}},
                ]
            )
        }
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar", "--sim")

    assert result.exit_code == 0, result.output
    output = _run("produtos", "listar").output
    assert "mercearia" in output
    assert "30 UN" in output


def test_revisar_prints_fundir_command_for_confirmed_duplicate_and_does_not_merge(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich([{"id": 1, "readable_name": "Refrigerante Pepsi 2L", "tags": ["bebidas"], "content": None}]),
            "merge": _merge([{"id": 1, "rationale": "mesmo corte", "same_product": True, "confidence": 0.8}]),
        }
    )
    _stub_client(monkeypatch, client)
    before = len(_run("produtos", "listar").output.splitlines())

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    assert "Possíveis duplicatas (IA):" in result.output
    assert "julius produtos fundir 13 12" in result.output
    output = _run("produtos", "listar").output
    assert "PICANHA BOV FAT kg PROMO" in output
    assert "FRALDINHA BOV PROMO kg" in output
    assert len(output.splitlines()) == before


def test_revisar_without_ai_shows_not_configured_hint():
    _import("qrcode.html")
    result = _run("produtos", "revisar")
    assert result.exit_code == 0, result.output
    assert "Dica:" in result.output and "JULIUS_AI_API_KEY" in result.output


def test_revisar_with_nothing_pending(monkeypatch):
    _ai_env(monkeypatch)
    _stub_client(monkeypatch, ScriptedLlmClient([]))
    result = _run("produtos", "revisar")
    assert result.exit_code == 0, result.output
    assert "Nenhum produto pendente de revisão." in result.output


def test_revisar_budget_exhausted_prints_reason_and_changes_nothing(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch, JULIUS_AI_BUDGET_USD="0")
    _stub_client(monkeypatch, ScriptedLlmClient([]))
    before = _run("produtos", "listar").output

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    assert "orçamento do mês esgotado" in result.output
    assert _run("produtos", "listar").output == before


def test_revisar_ai_error_prints_log_path_and_changes_nothing(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    err = LlmResponse("", 0, 0, error="HTTP 500")
    _stub_client(monkeypatch, ScriptedLlmClient(by_kind={"enrich": [err, err]}))
    before = _run("produtos", "listar").output

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    assert "IA não respondeu" in result.output
    assert "ai_calls.jsonl" in result.output
    assert _run("produtos", "listar").output == before


def test_revisar_skips_rename_for_manually_renamed_product(monkeypatch):
    _import("qrcode.html")
    assert _run("produtos", "renomear", "11", "Nome Manual").exit_code == 0
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Outro Nome da IA", "tags": ["carnes"], "content": None}])}
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    output = _run("produtos", "listar").output
    assert "Nome Manual" in output
    assert "Outro Nome da IA" not in output
    assert "carnes" in output


def test_cli_ultimas_acoes_prints_table(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [
                    {
                        "id": 8,
                        "readable_name": "Ovo Grande",
                        "tags": ["hortifruti"],
                        "content": {"quantity": 30, "unit": "UN"},
                        "kind": "ovo",
                    }
                ]
            )
        }
    )
    _stub_client(monkeypatch, client)
    assert _run("produtos", "revisar").exit_code == 0

    result = _run("produtos", "revisar", "--ultimas-acoes")

    assert result.exit_code == 0, result.output
    assert "Desfazer" in result.output
    assert "julius produtos tipo 8 --remover" in result.output
    assert "conteudo" in result.output


def test_cli_ultimas_acoes_empty_log_message():
    result = _run("produtos", "revisar", "--ultimas-acoes")
    assert result.exit_code == 0, result.output
    assert "Nenhuma ação automática registrada" in result.output


def test_cli_ultimas_acoes_does_not_call_ai(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    _stub_client(monkeypatch, RaisingLlmClient())

    result = _run("produtos", "revisar", "--ultimas-acoes")

    assert result.exit_code == 0, result.output
    assert "Nenhuma ação automática registrada" in result.output


def test_cli_ultimas_acoes_tolerates_partial_record(tmp_path):
    (tmp_path / "actions.jsonl").write_text(json.dumps({"product_id": 7, "field": "kind"}) + "\n", encoding="utf-8")

    result = _run("produtos", "revisar", "--ultimas-acoes")

    assert result.exit_code == 0, result.output
    assert "kind" in result.output


def test_review_summary_points_to_flag(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Linguiça", "tags": ["carnes"]}])}
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert "julius produtos revisar --ultimas-acoes" in result.output
