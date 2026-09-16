import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import julius.cli.products as products_cli
from _fakes import ScriptedLlmClient
from julius.cli import _review, app
from julius.infra.llm_client import LlmResponse

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "prices.db"))
    monkeypatch.setenv("COLUMNS", "220")


def _run(*args: str, **kwargs):
    return runner.invoke(app, list(args), **kwargs)


def _import(*names: str):
    result = _run("importar", *(str(FIXTURES / name) for name in names))
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


@pytest.mark.parametrize(("answer", "expects_content"), [("s", True), ("n", False)])
def test_revisar_content_confirmed_or_declined(monkeypatch, answer, expects_content):
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

    result = _run("produtos", "revisar", input=f"{answer}\n")

    assert result.exit_code == 0, result.output
    output = _run("produtos", "listar").output
    assert ("30 UN" in output) is expects_content


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
    assert "julius produtos definir-conteudo 5 30 UN" in result.output
    assert "Pendentes: 1 produto(s) sem categoria." in result.output
    output = _run("produtos", "listar").output
    assert "carnes" in output and "hortifruti" in output
    assert "30 UN" not in output


def test_revisar_sim_applies_first_tag_even_if_unknown_and_never_writes_content(monkeypatch):
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
    assert "julius produtos definir-conteudo 5 30 UN" in result.output
    output = _run("produtos", "listar").output
    assert "mercearia" in output
    assert "30 UN" not in output


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
