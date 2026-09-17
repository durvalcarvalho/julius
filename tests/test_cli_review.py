import json
import os
import sys
import time
from typing import get_args, get_type_hints
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
    # Importing also gives the store a nickname, which writes its own line to actions.jsonl.
    # That belongs to test_cli_store_naming.py; here the log has to start empty so these tests
    # keep measuring what the *product* review logged.
    _action_log().unlink(missing_ok=True)
    return result


def _action_log() -> Path:
    return Path(os.environ["JULIUS_DB"]).parent / "actions.jsonl"


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


def test_revisar_applies_first_known_tag_without_asking(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia", "bebidas"], "content": None}])}
    )
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)

    result = _run("produtos", "revisar", input="\n")

    assert result.exit_code == 0, result.output
    assert "— categoria" not in result.output
    assert "mercearia" in _run("produtos", "listar").output


def test_revisar_does_not_apply_unknown_category(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 8, "readable_name": "Chá Relaxa", "tags": ["ovos"], "content": None}])}
    )
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)

    result = _run("produtos", "revisar", input="\n")

    assert result.exit_code == 0, result.output
    assert "categoria  [" not in result.output
    assert "ovos" not in _run("produtos", "listar").output


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
    # Naive local, not UTC: `--ultimas-acoes` shows this hour, and an offset here used to be
    # displayed as if it were local time.
    assert all("+" not in record["at"] and not record["at"].endswith("Z") for record in records)


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

    assert "Aplicado: 1 nome(s), 1 categoria(s)." in result.output
    assert "conteúdo(s)" not in result.output and "tipo(s)" not in result.output


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


def test_revisar_non_interactive_applies_known_categories_and_content(monkeypatch):
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
    assert "Pendentes: 1 produto(s) sem conteúdo." in result.output  # the tea, sold by UN, got none
    output = _run("produtos", "listar").output
    assert "carnes" in output and "hortifruti" in output and "mercearia" in output
    assert "30 UN" in output


def test_revisar_sim_does_not_apply_unknown_tag(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [
                    {"id": 8, "readable_name": "Chá Relaxa", "tags": ["ovos"], "content": None},
                    {"id": 5, "readable_name": "Ovo Grande", "tags": ["hortifruti"], "content": {"quantity": 30, "unit": "UN"}},
                ]
            )
        }
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar", "--sim")

    assert result.exit_code == 0, result.output
    output = _run("produtos", "listar").output
    assert "ovos" not in output
    assert "hortifruti" in output
    assert "30 UN" in output


def _duplicate_client(monkeypatch, *, same: bool = True, enrich_items: list[dict] | None = None):
    """The review with one confirmed duplicate pair (ids 12 and 13 of qrcode.html)."""
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(enrich_items or [{"id": 1, "readable_name": "Refrigerante Pepsi 2L", "tags": ["bebidas"], "content": None}]),
            "merge": _merge([{"id": 1, "rationale": "mesmo corte", "same_product": same, "confidence": 0.8}]),
        }
    )
    _stub_client(monkeypatch, client)
    return client


def test_revisar_merges_confirmed_duplicate_keeping_the_lowest_id(monkeypatch):
    _duplicate_client(monkeypatch)

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output
    assert "Fundidos automaticamente (confira):" in result.output
    assert "12 ← 13" in result.output and "mesmo corte" in result.output
    assert "desfazer: julius produtos desfundir 13" in result.output
    output = _run("produtos", "listar").output
    assert "PICANHA BOV FAT kg PROMO" in output
    assert "FRALDINHA BOV PROMO kg" not in output  # absorbed, hidden from the listing


def test_revisar_does_not_merge_unconfirmed_pair(monkeypatch):
    _duplicate_client(monkeypatch, same=False)

    result = _run("produtos", "revisar")

    assert "Fundidos automaticamente" not in result.output
    assert "FRALDINHA BOV PROMO kg" in _run("produtos", "listar").output


def test_revisar_merge_announces_inherited_content(monkeypatch):
    _import("qrcode.html")
    assert _run("produtos", "definir-conteudo", "13", "500", "G").exit_code == 0
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich([{"id": 1, "readable_name": "Refrigerante Pepsi 2L", "tags": ["bebidas"], "content": None}]),
            "merge": _merge([{"id": 1, "rationale": "mesmo corte", "same_product": True, "confidence": 0.8}]),
        }
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert "o grupo herdou o conteúdo 0.5 KG do produto 13" in result.output
    assert "0,5 KG" in _run("produtos", "listar").output


def test_revisar_merge_logs_the_action_with_its_undo(monkeypatch, tmp_path):
    _duplicate_client(monkeypatch)
    _run("produtos", "revisar")

    (action,) = [line for line in _actions(tmp_path) if line["field"] == "merge"]
    assert (action["product_id"], action["after"]) == (12, "13")
    assert action["undo"] == "julius produtos desfundir 13"


def test_revisar_with_sim_still_merges(monkeypatch):
    _duplicate_client(monkeypatch)
    assert "Fundidos automaticamente" in _run("produtos", "revisar", "--sim").output


def test_revisar_prints_nothing_about_duplicates_when_there_are_none(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich([{"id": 11, "readable_name": "Linguiça", "tags": ["carnes"], "content": None}]),
            "merge": _merge([]),
        }
    )
    _stub_client(monkeypatch, client)

    output = _run("produtos", "revisar").output
    assert "Fundidos" not in output and "duplicata" not in output.lower()


def test_revisar_survives_a_merge_that_fails(monkeypatch):
    """A pair whose products are already in the same group: the cycle guard refuses and the
    review keeps going."""
    _import("qrcode.html")
    assert _run("produtos", "fundir", "13", "12").exit_code == 0
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich([{"id": 1, "readable_name": "Refrigerante Pepsi 2L", "tags": ["bebidas"], "content": None}]),
            "merge": _merge([{"id": 1, "rationale": "mesmo corte", "same_product": True, "confidence": 0.8}]),
        }
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert result.exit_code == 0, result.output


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


def test_table_shows_receipt_description_not_renamed_name(monkeypatch):
    _import("qrcode.html")
    assert _run("produtos", "renomear", "11", "Linguiça Aurora").exit_code == 0
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Outro Nome", "tags": ["carnes"], "content": None}])}
    )
    _stub_client(monkeypatch, client)

    output = _run("produtos", "revisar").output

    assert "LING FGO RESF AURORA kg" in output  # Cupom
    assert "Linguiça Aurora" in output  # Nome (renamed by hand, the AI never overwrites it)


def test_table_shows_current_content_dim_when_nothing_to_propose(monkeypatch):
    _import("qrcode.html")
    assert _run("produtos", "definir-conteudo", "12", "500", "G").exit_code == 0
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [
                    {"id": 12, "readable_name": "Picanha", "tags": ["carnes"], "content": None},
                    {"id": 13, "readable_name": "Fraldinha", "tags": ["carnes"], "content": None},
                ]
            )
        }
    )
    _stub_client(monkeypatch, client)

    output = _run("produtos", "revisar").output

    picanha, fraldinha = (line for line in output.splitlines() if "Picanha" in line or "Fraldinha" in line)
    assert "0,5 KG" in picanha
    assert "0,5 KG" not in fraldinha


def test_table_shows_current_kind_when_nothing_to_propose(monkeypatch):
    _import("qrcode.html")
    assert _run("produtos", "tipo", "12", "picanha").exit_code == 0
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 12, "readable_name": "Picanha", "tags": ["carnes"], "content": None}])}
    )
    _stub_client(monkeypatch, client)

    assert "picanha" in _run("produtos", "revisar").output


def test_table_shows_category_and_discarded_candidates(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia", "bebidas"], "content": None}])}
    )
    _stub_client(monkeypatch, client)

    output = _run("produtos", "revisar").output

    assert "mercearia" in output and "bebidas" in output
    assert "?" not in output


def test_revisar_asks_nothing_for_a_kg_product(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Linguiça", "tags": ["carnes", "frios"], "content": None}])}
    )
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)

    result = _run("produtos", "revisar")  # no input= at all: nothing may block on stdin

    assert result.exit_code == 0, result.output
    assert "— categoria" not in result.output and "— conteúdo" not in result.output


def test_revisar_no_pending_line_when_nothing_pending(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich(
                [{"id": 11, "readable_name": "Linguiça", "tags": ["carnes"], "content": None, "kind": "linguiça"}]
            )
        }
    )
    _stub_client(monkeypatch, client)

    assert "Pendentes:" not in _run("produtos", "revisar").output  # sold by KG: content is not owed


def _packaging(items: list[dict], input_tokens: int = 100, output_tokens: int = 50) -> LlmResponse:
    return LlmResponse(json.dumps({"packaging": items}), input_tokens, output_tokens)


TEA = [{"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia"], "content": None}]


def _tea_review(monkeypatch, packaging: LlmResponse | None = None, *, args: tuple[str, ...] = (), input: str = ""):
    """The tea is sold by UN and the AI refuses its content: the one case that reaches the question."""
    _import("qrcode.html")
    _ai_env(monkeypatch)
    by_kind = {"enrich": _enrich(TEA)}
    if packaging is not None:
        by_kind["packaging"] = packaging
    client = ScriptedLlmClient(by_kind=by_kind)
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)
    return client, _run("produtos", "revisar", *args, input=input)


def _packaging_calls(client) -> list[tuple[str, str, int]]:
    return [call for call in client.calls if '"packaging"' in call[0]]


def test_content_question_offers_candidates(monkeypatch):
    hint = _packaging([{"id": 8, "form": "pack", "candidates": [{"quantity": 10, "unit": "UN"}, {"quantity": 20, "unit": "UN"}]}])
    _, result = _tea_review(monkeypatch, hint, input="1\n")

    assert result.exit_code == 0, result.output
    assert "[1] 10 UN · pacote" in result.output and "[2] 20 UN · pacote" in result.output
    assert "10 UN" in _run("produtos", "listar").output


def test_content_question_typed_value(monkeypatch):
    hint = _packaging([{"id": 8, "form": "pack", "candidates": [{"quantity": 10, "unit": "UN"}]}])
    _, result = _tea_review(monkeypatch, hint, input="2\n500 G\n")

    assert result.exit_code == 0, result.output
    assert "0,5 KG" in _run("produtos", "listar").output


def test_content_question_enter_skips_and_stays_pending(monkeypatch):
    hint = _packaging([{"id": 8, "form": "pack", "candidates": [{"quantity": 10, "unit": "UN"}]}])
    _, result = _tea_review(monkeypatch, hint, input="\n")

    assert "Pendentes: 1 produto(s) sem conteúdo." in result.output
    assert "10 UN" not in _run("produtos", "listar").output


@pytest.mark.parametrize("answer", ["xyz\n", "2\n500 OZ\n", "9\n"])
def test_content_question_invalid_input_is_treated_as_skip(monkeypatch, answer):
    hint = _packaging([{"id": 8, "form": "pack", "candidates": [{"quantity": 10, "unit": "UN"}]}])
    _, result = _tea_review(monkeypatch, hint, input=answer)

    assert result.exit_code == 0, result.output
    assert "Pendentes: 1 produto(s) sem conteúdo." in result.output


def test_content_question_suppresses_candidates_for_weight_form(monkeypatch):
    hint = _packaging([{"id": 8, "form": "weight", "candidates": [{"quantity": 500, "unit": "KG"}]}])
    _, result = _tea_review(monkeypatch, hint, input="\n")

    assert "500 KG" not in result.output
    assert "[1] digitar" in result.output


def test_content_question_without_packaging_call_still_asks(monkeypatch):
    _, result = _tea_review(monkeypatch, LlmResponse("", 10, 0, error="HTTP 500"), input="\n")

    assert result.exit_code == 0, result.output
    assert "— conteúdo" in result.output and "[1] digitar" in result.output


def test_content_question_skipped_for_kg_product(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Linguiça", "tags": ["carnes"], "content": None}])}
    )
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)

    result = _run("produtos", "revisar")

    assert "— conteúdo" not in result.output
    assert _packaging_calls(client) == []


def test_content_question_not_asked_without_tty(monkeypatch):
    hint = _packaging([{"id": 8, "form": "pack", "candidates": [{"quantity": 10, "unit": "UN"}]}])
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(by_kind={"enrich": _enrich(TEA), "packaging": hint})
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")

    assert "— conteúdo" not in result.output
    assert _packaging_calls(client) == []
    assert "Pendentes: 1 produto(s) sem conteúdo." in result.output


def test_sim_asks_nothing_and_leaves_pending(monkeypatch):
    hint = _packaging([{"id": 8, "form": "pack", "candidates": [{"quantity": 10, "unit": "UN"}]}])
    client, result = _tea_review(monkeypatch, hint, args=("--sim",))

    assert result.exit_code == 0, result.output
    assert "— conteúdo" not in result.output
    assert _packaging_calls(client) == []
    assert "Pendentes: 1 produto(s) sem conteúdo." in result.output


def test_content_answer_is_logged_with_undo(monkeypatch, tmp_path):
    hint = _packaging([{"id": 8, "form": "pack", "candidates": [{"quantity": 10, "unit": "UN"}]}])
    _tea_review(monkeypatch, hint, input="1\n")

    (action,) = [line for line in _actions(tmp_path) if line["field"] == "content"]
    assert action["after"] == "10 UN"
    assert action["undo"] == "julius produtos definir-conteudo 8 --remover"


def test_ai_refusal_is_the_only_trigger(monkeypatch):
    """A product whose enrich DID return content is never asked, packaging candidates or not."""
    _import("qrcode.html")
    _ai_env(monkeypatch)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich([{"id": 8, "readable_name": "Chá Relaxa", "tags": ["mercearia"], "content": {"quantity": 10, "unit": "UN"}}]),
            "packaging": _packaging([{"id": 8, "form": "pack", "candidates": [{"quantity": 99, "unit": "UN"}]}]),
        }
    )
    _stub_client(monkeypatch, client)
    monkeypatch.setattr(_review, "_is_interactive", lambda: True)

    result = _run("produtos", "revisar")

    assert "— conteúdo" not in result.output
    assert _packaging_calls(client) == []
    assert "10 UN" in _run("produtos", "listar").output


def test_undo_command_for_merge_field():
    action = AppliedAction(33, "merge", None, "80")
    assert _review._undo_command(action) == "julius produtos desfundir 80"


def test_every_applied_action_field_has_a_label_and_an_undo_command():
    """Forgetting one would print an empty label or a wrong command instead of failing."""
    names = get_args(get_type_hints(AppliedAction)["field"])
    labelled = {field for field, _ in _review._FIELD_LABELS}
    for name in names:
        assert name in labelled, name
        assert _review._undo_command(AppliedAction(1, name, "antes", "depois")).startswith("julius produtos")


def test_when_reads_both_the_old_utc_lines_and_the_new_local_ones(monkeypatch):
    """actions.jsonl holds UTC lines written before the writers switched to naive local. TZ is
    pinned because `.astimezone()` uses the machine's zone, and the assertion would otherwise only
    hold in UTC-3."""
    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    time.tzset()

    assert products_cli._when("2026-09-17T22:31:47+00:00") == "17/09/2026 19:31"
    assert products_cli._when("2026-09-17T19:31:47") == "17/09/2026 19:31"


@pytest.mark.parametrize("raw", ["", "lixo", "2026-13-40T00:00:00"])
def test_when_of_a_broken_record_is_empty(raw):
    assert products_cli._when(raw) == ""
