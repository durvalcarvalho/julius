import json
from dataclasses import replace

import pytest

from _fakes import RaisingLlmClient, ScriptedLlmClient
from julius.config import Config
from julius.domain.models import ContentSuggestion, MergeSuggestion, PackagingHint, Product, ProductEnrichment
from julius.infra.llm_client import LlmResponse
from julius.repositories import ai_usage
from julius.services import suggestions

MONTH = "2026-09"


@pytest.fixture
def cfg(db_path) -> Config:
    return Config(
        db_path=db_path,
        ai_api_key="secret",
        ai_base_url="https://api.example/v1",
        ai_model="cheap-1",
        ai_budget_usd=1.0,
        ai_input_price_usd_per_1m=1.0,
        ai_output_price_usd_per_1m=1.0,
    )


def _merge_response(payload: dict, input_tokens: int = 1000, output_tokens: int = 500) -> LlmResponse:
    return LlmResponse(json.dumps(payload), input_tokens, output_tokens)


def _enrich_response(payload: dict, input_tokens: int = 1000, output_tokens: int = 500) -> LlmResponse:
    return LlmResponse(json.dumps(payload), input_tokens, output_tokens)


def _lines(cfg: Config) -> list[dict]:
    return [json.loads(line) for line in cfg.ai_log_path.read_text(encoding="utf-8").splitlines()]


def test_not_configured_returns_none_without_call_or_log_line(conn, cfg):
    config = replace(cfg, ai_api_key=None)
    client = ScriptedLlmClient([_merge_response({"pairs": []})])
    assert suggestions.suggest_merges(conn, config, client, [("A", "B")], MONTH) == [None]
    assert client.calls == []
    assert not config.ai_log_path.exists()


def test_budget_exhausted_logs_one_line_and_does_not_call(conn, cfg):
    ai_usage.add_spent(conn, MONTH, cfg.ai_budget_usd)
    client = ScriptedLlmClient([_merge_response({"pairs": []})])
    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)
    assert result == [None]
    assert client.calls == []
    (line,) = _lines(cfg)
    assert line["error"] == "budget_exhausted"
    assert line["attempt"] == 0


def test_suggest_merges_parses_batch_in_order_and_records_cost(conn, cfg):
    payload = {
        "pairs": [
            {"id": 3, "rationale": "r3", "same_product": False, "confidence": 0.2},
            {"id": 1, "rationale": "r1", "same_product": True, "confidence": 0.9},
            {"id": 2, "rationale": "r2", "same_product": True, "confidence": 0.5},
        ]
    }
    client = ScriptedLlmClient([_merge_response(payload, input_tokens=1000, output_tokens=500)])
    pairs = [("A1", "B1"), ("A2", "B2"), ("A3", "B3")]

    result = suggestions.suggest_merges(conn, cfg, client, pairs, MONTH)

    assert result == [
        MergeSuggestion(True, 0.9, "r1"),
        MergeSuggestion(True, 0.5, "r2"),
        MergeSuggestion(False, 0.2, "r3"),
    ]
    assert ai_usage.spent_in_month(conn, MONTH) == pytest.approx(1000 / 1e6 + 500 / 1e6)


def test_invalid_json_then_valid_retries_once_and_charges_both(conn, cfg):
    valid = {"pairs": [{"id": 1, "rationale": "r", "same_product": True, "confidence": 0.5}]}
    client = ScriptedLlmClient([LlmResponse("não sei", 100, 50), _merge_response(valid, 200, 100)])

    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)

    assert result == [MergeSuggestion(True, 0.5, "r")]
    assert len(client.calls) == 2
    lines = _lines(cfg)
    assert [line["attempt"] for line in lines] == [1, 2]
    assert [line["parsed_ok"] for line in lines] == [False, True]
    expected_cost = (100 / 1e6 + 50 / 1e6) + (200 / 1e6 + 100 / 1e6)
    assert ai_usage.spent_in_month(conn, MONTH) == pytest.approx(expected_cost)


def test_two_failures_return_none_for_every_pair_after_two_calls(conn, cfg):
    client = ScriptedLlmClient([LlmResponse("nope", 10, 10), LlmResponse("nope2", 10, 10)])
    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B"), ("C", "D")], MONTH)
    assert result == [None, None]
    assert len(client.calls) == 2


def test_transport_error_is_logged_with_error_text(conn, cfg):
    client = ScriptedLlmClient([LlmResponse("", 0, 0, error="HTTP 429")])
    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)
    assert result == [None]
    lines = _lines(cfg)
    assert lines[-1]["error"] == "HTTP 429"
    assert lines[-1]["cost_usd"] == 0


def test_truncated_response_is_charged(conn, cfg):
    client = ScriptedLlmClient([LlmResponse("", 1200, 1200, error="finish_reason length")])
    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)
    assert result == [None]
    assert ai_usage.spent_in_month(conn, MONTH) > 0


def test_client_raising_never_propagates_and_is_logged_as_client_raised(conn, cfg):
    result = suggestions.suggest_merges(conn, cfg, RaisingLlmClient(), [("A", "B")], MONTH)
    assert result == [None]
    lines = _lines(cfg)
    assert all(line["error"] == "client raised RuntimeError" for line in lines)


def test_item_with_invalid_fields_becomes_none_but_others_survive(conn, cfg):
    payload = {
        "pairs": [
            {"id": 1, "rationale": "ok", "same_product": True, "confidence": 1.5},
            {"id": 2, "rationale": "ok", "same_product": "sim", "confidence": 0.5},
            {"id": 3, "rationale": "ok", "same_product": True, "confidence": 0.5},
        ]
    }
    client = ScriptedLlmClient([_merge_response(payload)])

    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B"), ("C", "D"), ("E", "F")], MONTH)

    assert result[0] is None
    assert result[1] is None
    assert result[2] == MergeSuggestion(True, 0.5, "ok")


def test_log_line_has_exact_keys(conn, cfg):
    payload = {"pairs": [{"id": 1, "rationale": "r", "same_product": True, "confidence": 0.5}]}
    client = ScriptedLlmClient([_merge_response(payload)])
    suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)
    (line,) = _lines(cfg)
    assert set(line) == {
        "ts",
        "call_kind",
        "prompt_version",
        "model",
        "attempt",
        "user_prompt",
        "raw_response",
        "parsed_ok",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "latency_ms",
        "error",
    }


def test_max_tokens_scales_with_pair_count(conn, cfg):
    client = ScriptedLlmClient([_merge_response({"pairs": []})])
    suggestions.suggest_merges(conn, cfg, client, [("A", "B")] * 4, MONTH)
    assert client.calls[0][2] == 420


def test_empty_pairs_returns_empty_without_call(conn, cfg):
    client = ScriptedLlmClient([_merge_response({"pairs": []})])
    assert suggestions.suggest_merges(conn, cfg, client, [], MONTH) == []
    assert client.calls == []


def test_merge_prompt_asks_for_rationale_before_decision():
    prompt = suggestions.SYSTEM_PROMPTS["merge"]
    format_line = next(line for line in prompt.splitlines() if '"same_product"' in line and '"rationale"' in line)
    assert format_line.index('"rationale"') < format_line.index('"same_product"')


def test_spent_this_month_reads_current_month(conn, monkeypatch):
    monkeypatch.setattr(suggestions, "_current_month", lambda: "2026-09")
    ai_usage.add_spent(conn, "2026-09", 0.42)
    assert suggestions.spent_this_month(conn) == pytest.approx(0.42)


def test_is_available_never_raises_on_broken_connection(conn, cfg):
    conn.close()
    assert suggestions.is_available(conn, cfg, MONTH) is False


def test_enrich_prompt_lists_categories_and_id_name_lines(conn, cfg):
    client = ScriptedLlmClient([_enrich_response({"products": []})])
    products = [Product(id=60, canonical_name="LING FGO RESF AURORA kg")]

    suggestions.enrich_products(conn, cfg, client, products, ["carnes", "bebidas"], month=MONTH)

    prompt = client.calls[0][1]
    assert 'categorias: ["carnes", "bebidas"]' in prompt
    assert "60 | LING FGO RESF AURORA kg" in prompt


def test_enrich_parses_kind(conn, cfg):
    payload = {"products": [{"id": 1, "readable_name": "Tomate", "tags": ["hortifruti"], "kind": "Tomate"}]}
    client = ScriptedLlmClient([_enrich_response(payload)])

    result = suggestions.enrich_products(
        conn, cfg, client, [Product(id=1, canonical_name="TOMATE ITALIANO kg")], ["hortifruti"], month=MONTH
    )

    assert result[1].kind == "tomate"


def test_enrich_kind_missing_is_none(conn, cfg):
    payload = {"products": [{"id": 1, "readable_name": "Refri", "tags": ["bebidas"], "content": None}]}
    client = ScriptedLlmClient([_enrich_response(payload)])

    result = suggestions.enrich_products(
        conn, cfg, client, [Product(id=1, canonical_name="REFRI")], ["bebidas"], month=MONTH
    )

    assert result[1] == ProductEnrichment("Refri", ("bebidas",), None, None)


@pytest.mark.parametrize("bad_kind", [None, "", "   ", 123, [], {"a": 1}])
def test_enrich_kind_invalid_types_are_none(conn, cfg, bad_kind):
    payload = {"products": [{"id": 1, "readable_name": "Refri", "tags": ["bebidas"], "kind": bad_kind}]}
    client = ScriptedLlmClient([_enrich_response(payload)])

    result = suggestions.enrich_products(
        conn, cfg, client, [Product(id=1, canonical_name="REFRI")], ["bebidas"], month=MONTH
    )

    assert result[1].kind is None
    assert result[1].readable_name == "Refri"


def test_enrich_prompt_includes_known_kinds(conn, cfg):
    client = ScriptedLlmClient([_enrich_response({"products": []})])
    products = [Product(id=60, canonical_name="TOMATE ITALIANO kg")]

    suggestions.enrich_products(conn, cfg, client, products, ["hortifruti"], ["tomate", "cebola"], month=MONTH)
    assert 'tipos: ["tomate", "cebola"]' in client.calls[0][1]

    suggestions.enrich_products(conn, cfg, client, products, ["hortifruti"], [], month=MONTH)
    assert "tipos: []" in client.calls[1][1]


def test_enrich_prompt_version_is_2(conn, cfg):
    client = ScriptedLlmClient([_enrich_response({"products": []})])
    suggestions.enrich_products(conn, cfg, client, [Product(id=1, canonical_name="A")], [], month=MONTH)
    assert [line["prompt_version"] for line in _lines(cfg)] == ["2"]


def test_enrich_parses_valid_batch_with_null_and_object_content(conn, cfg):
    payload = {
        "products": [
            {"id": 1, "readable_name": "Linguiça", "tags": [" Carnes ", "carnes"], "content": None},
            {"id": 2, "readable_name": "Refri", "tags": ["bebidas"], "content": {"quantity": 1.5, "unit": "l"}},
            {"id": 3, "readable_name": "Outro", "tags": ["mercearia"], "content": None},
        ]
    }
    client = ScriptedLlmClient([_enrich_response(payload)])
    products = [Product(id=1, canonical_name="A"), Product(id=2, canonical_name="B"), Product(id=3, canonical_name="C")]

    result = suggestions.enrich_products(conn, cfg, client, products, ["carnes", "bebidas", "mercearia"], month=MONTH)

    assert result[1] == ProductEnrichment("Linguiça", ("carnes",), None, None)
    assert result[2] == ProductEnrichment("Refri", ("bebidas",), ContentSuggestion(1.5, "L"), None)
    assert len(result) == 3


@pytest.mark.parametrize(
    "bad_item",
    [
        {"id": 999, "readable_name": "X", "tags": ["carnes"], "content": None},
        {"id": 1, "readable_name": "  ", "tags": ["carnes"], "content": None},
        {"id": 1, "readable_name": "X", "tags": [], "content": None},
        {"id": 1, "readable_name": "X", "tags": "carnes", "content": None},
    ],
)
def test_enrich_drops_items_with_unknown_id_or_bad_name_or_bad_tags_but_keeps_others(conn, cfg, bad_item):
    good_item = {"id": 2, "readable_name": "Bom", "tags": ["carnes"], "content": None}
    client = ScriptedLlmClient([_enrich_response({"products": [bad_item, good_item]})])
    products = [Product(id=1, canonical_name="A"), Product(id=2, canonical_name="B")]

    result = suggestions.enrich_products(conn, cfg, client, products, ["carnes"], month=MONTH)

    assert 1 not in result
    assert result[2].readable_name == "Bom"


@pytest.mark.parametrize("content", [{"quantity": 500, "unit": "G"}, {"quantity": -1, "unit": "L"}])
def test_enrich_invalid_content_keeps_item_with_content_none(conn, cfg, content):
    payload = {"products": [{"id": 1, "readable_name": "X", "tags": ["carnes"], "content": content}]}
    client = ScriptedLlmClient([_enrich_response(payload)])

    result = suggestions.enrich_products(conn, cfg, client, [Product(id=1, canonical_name="A")], ["carnes"], month=MONTH)

    assert result[1].content is None
    assert result[1].readable_name == "X"


def test_enrich_splits_into_batches_of_25(conn, cfg):
    products = [Product(id=i, canonical_name=f"P{i}") for i in range(1, 61)]
    responses = [
        _enrich_response(
            {"products": [{"id": i, "readable_name": f"N{i}", "tags": ["carnes"], "content": None} for i in ids]}
        )
        for ids in (range(1, 26), range(26, 51), range(51, 61))
    ]
    client = ScriptedLlmClient(responses)

    result = suggestions.enrich_products(conn, cfg, client, products, ["carnes"], month=MONTH)

    assert len(client.calls) == 3
    assert [call[1].count(" | ") for call in client.calls] == [25, 25, 10]
    assert len(result) == 60


def test_enrich_failed_batch_only_loses_that_batch(conn, cfg):
    products = [Product(id=i, canonical_name=f"P{i}") for i in range(1, 61)]
    ok1 = _enrich_response(
        {"products": [{"id": i, "readable_name": f"N{i}", "tags": ["carnes"], "content": None} for i in range(1, 26)]}
    )
    err = LlmResponse("", 0, 0, error="HTTP 500")
    ok3 = _enrich_response(
        {"products": [{"id": i, "readable_name": f"N{i}", "tags": ["carnes"], "content": None} for i in range(51, 61)]}
    )
    client = ScriptedLlmClient([ok1, err, err, ok3])

    result = suggestions.enrich_products(conn, cfg, client, products, ["carnes"], month=MONTH)

    assert set(result) == set(range(1, 26)) | set(range(51, 61))


def test_enrich_max_tokens_formula(conn, cfg):
    client = ScriptedLlmClient([_enrich_response({"products": []})])
    products = [Product(id=i, canonical_name=f"P{i}") for i in range(1, 7)]
    suggestions.enrich_products(conn, cfg, client, products, [], month=MONTH)
    assert client.calls[0][2] == 1040


def test_enrich_unavailable_returns_empty_dict_without_calls(conn, cfg):
    config = replace(cfg, ai_api_key=None)
    client = ScriptedLlmClient([_enrich_response({"products": []})])

    result = suggestions.enrich_products(conn, config, client, [Product(id=1, canonical_name="A")], [], month=MONTH)

    assert result == {}
    assert client.calls == []


def test_match_products_returns_known_ids_in_order_without_duplicates(conn, cfg):
    client = ScriptedLlmClient([LlmResponse(json.dumps({"ids": [61, 999, 60, 61]}), 10, 5)])
    catalog = [(60, "A", ()), (61, "B", ("carnes",))]

    assert suggestions.match_products(conn, cfg, client, "termo", catalog, MONTH) == [61, 60]


def test_match_products_prompt_has_term_and_catalog_lines_with_tags(conn, cfg):
    client = ScriptedLlmClient([LlmResponse(json.dumps({"ids": []}), 1, 1)])
    catalog = [(60, "LING FGO", ("carnes",)), (61, "SEM TAG", ())]

    suggestions.match_products(conn, cfg, client, "linguica", catalog, MONTH)

    prompt = client.calls[0][1]
    assert "termo: linguica" in prompt
    assert "60 | LING FGO | carnes" in prompt
    assert "61 | SEM TAG | " in prompt


def test_match_products_empty_catalog_or_blank_term_does_not_call(conn, cfg):
    client = ScriptedLlmClient([LlmResponse(json.dumps({"ids": []}), 1, 1)])
    assert suggestions.match_products(conn, cfg, client, "termo", []) == []
    assert suggestions.match_products(conn, cfg, client, "   ", [(1, "A", ())]) == []
    assert client.calls == []


def test_match_products_non_object_payload_returns_empty(conn, cfg):
    client = ScriptedLlmClient([LlmResponse(json.dumps([1, 2, 3]), 1, 1)])
    assert suggestions.match_products(conn, cfg, client, "termo", [(1, "A", ())], MONTH) == []


def _packaging_response(items: list[dict], input_tokens: int = 100, output_tokens: int = 50) -> LlmResponse:
    return LlmResponse(json.dumps({"packaging": items}), input_tokens, output_tokens)


def _products(count: int, start: int = 60) -> list[Product]:
    return [Product(id=start + i, canonical_name=f"P{start + i}") for i in range(count)]


def test_packaging_parses_form_and_candidates(conn, cfg):
    client = ScriptedLlmClient(
        [
            _packaging_response(
                [{"id": 60, "form": "pack", "candidates": [{"quantity": 10, "unit": "UN"}, {"quantity": 20, "unit": "UN"}]}]
            )
        ]
    )
    hints = suggestions.suggest_packaging(conn, cfg, client, _products(1), MONTH)
    assert hints == {60: PackagingHint("pack", (ContentSuggestion(10.0, "UN"), ContentSuggestion(20.0, "UN")))}


@pytest.mark.parametrize("form", [None, "tray", 123])
def test_packaging_unknown_form_falls_back(conn, cfg, form):
    item = {"id": 60, "candidates": []} if form is None else {"id": 60, "form": form, "candidates": []}
    client = ScriptedLlmClient([_packaging_response([item])])
    assert suggestions.suggest_packaging(conn, cfg, client, _products(1), MONTH) == {60: PackagingHint("unknown", ())}


def test_packaging_drops_invalid_candidate_keeps_the_rest(conn, cfg):
    client = ScriptedLlmClient(
        [
            _packaging_response(
                [
                    {
                        "id": 60,
                        "form": "pack",
                        "candidates": [
                            {"quantity": 10, "unit": "UN"},
                            {"quantity": 1, "unit": "OZ"},
                            {"quantity": 0, "unit": "UN"},
                        ],
                    }
                ]
            )
        ]
    )
    hints = suggestions.suggest_packaging(conn, cfg, client, _products(1), MONTH)
    assert hints[60].candidates == (ContentSuggestion(10.0, "UN"),)


def test_packaging_caps_at_three_candidates(conn, cfg):
    candidates = [{"quantity": n, "unit": "UN"} for n in (1, 2, 3, 4, 5)]
    client = ScriptedLlmClient([_packaging_response([{"id": 60, "form": "pack", "candidates": candidates}])])
    hints = suggestions.suggest_packaging(conn, cfg, client, _products(1), MONTH)
    assert [c.quantity for c in hints[60].candidates] == [1.0, 2.0, 3.0]


def test_packaging_empty_candidates_is_valid(conn, cfg):
    client = ScriptedLlmClient([_packaging_response([{"id": 60, "form": "weight", "candidates": []}])])
    assert suggestions.suggest_packaging(conn, cfg, client, _products(1), MONTH) == {60: PackagingHint("weight", ())}


def test_packaging_ignores_unknown_id(conn, cfg):
    client = ScriptedLlmClient(
        [
            _packaging_response(
                [
                    {"id": 999, "form": "unit", "candidates": [{"quantity": 1, "unit": "UN"}]},
                    {"id": 61, "form": "unit", "candidates": []},
                ]
            )
        ]
    )
    hints = suggestions.suggest_packaging(conn, cfg, client, _products(2), MONTH)
    assert set(hints) == {61}


def test_packaging_prompt_lists_id_and_name_only(conn, cfg):
    client = ScriptedLlmClient([_packaging_response([])])
    suggestions.suggest_packaging(conn, cfg, client, [Product(id=60, canonical_name="LING FGO RESF AURORA kg")], MONTH)
    prompt = client.calls[0][1]
    assert "60 | LING FGO RESF AURORA kg" in prompt
    assert "categorias:" not in prompt and "tipos:" not in prompt


def test_packaging_prompt_version_is_1(conn, cfg):
    client = ScriptedLlmClient([_packaging_response([])])
    suggestions.suggest_packaging(conn, cfg, client, _products(1), MONTH)
    (line,) = _lines(cfg)
    assert (line["prompt_version"], line["call_kind"]) == ("1", "packaging")


def test_packaging_max_tokens_formula(conn, cfg):
    client = ScriptedLlmClient([_packaging_response([])])
    suggestions.suggest_packaging(conn, cfg, client, _products(6), MONTH)
    assert client.calls[0][2] == 620


def test_packaging_batches_isolate_failures(conn, cfg):
    client = ScriptedLlmClient(
        [
            LlmResponse("", 10, 0, error="HTTP 500"),
            LlmResponse("", 10, 0, error="HTTP 500"),
            _packaging_response([{"id": 85, "form": "unit", "candidates": []}]),
        ]
    )
    hints = suggestions.suggest_packaging(conn, cfg, client, _products(30), MONTH)
    assert set(hints) == {85}


def test_packaging_unavailable_returns_empty_dict_without_calls(conn, cfg):
    client = ScriptedLlmClient([_packaging_response([{"id": 60, "form": "unit", "candidates": []}])])
    assert suggestions.suggest_packaging(conn, replace(cfg, ai_api_key=None), client, _products(1), MONTH) == {}
    assert client.calls == []
    assert suggestions.suggest_packaging(conn, cfg, client, [], MONTH) == {}
    assert client.calls == []


@pytest.mark.parametrize("payload", ["não é json", json.dumps({"packaging": "x"})])
def test_packaging_never_raises_on_garbage(conn, cfg, payload):
    client = ScriptedLlmClient([LlmResponse(payload, 10, 5)])
    assert suggestions.suggest_packaging(conn, cfg, client, _products(1), MONTH) == {}


def _usage_args(**overrides) -> dict:
    args = {
        "attempt": 1,
        "user_prompt": "produtos: 1 | TOMATE",
        "raw_response": '{"ok": true}',
        "parsed_ok": True,
        "input_tokens": 1000,
        "output_tokens": 500,
        "latency_ms": 42,
        "error": None,
        "month": MONTH,
    }
    return {**args, **overrides}


def test_record_usage_charges_and_logs(conn, cfg):
    config = replace(cfg, ai_input_price_usd_per_1m=0.30, ai_output_price_usd_per_1m=1.20)

    cost = suggestions.record_usage(conn, config, "bot_turn", **_usage_args())

    assert cost == pytest.approx(0.0009)
    assert ai_usage.spent_in_month(conn, MONTH) == pytest.approx(0.0009)
    line = _lines(config)[-1]
    assert line["call_kind"] == "bot_turn"
    assert line["cost_usd"] == pytest.approx(0.0009)
    assert line["input_tokens"] == 1000
    assert line["latency_ms"] == 42


def test_record_usage_with_zero_tokens_logs_without_charging(conn, cfg):
    """The budget_exhausted line: nothing was spent, but the silence has to be visible."""
    cost = suggestions.record_usage(
        conn,
        cfg,
        "bot_turn",
        **_usage_args(input_tokens=0, output_tokens=0, parsed_ok=False, raw_response=None, error="budget_exhausted"),
    )

    assert cost == 0.0
    assert ai_usage.spent_in_month(conn, MONTH) == 0.0
    assert _lines(cfg)[-1]["error"] == "budget_exhausted"


def test_record_usage_without_prices_costs_nothing(conn, cfg):
    """_ask never reaches charging without prices, but a public function must be safe without them."""
    config = replace(cfg, ai_input_price_usd_per_1m=None, ai_output_price_usd_per_1m=None)

    assert suggestions.record_usage(conn, config, "bot_turn", **_usage_args()) == 0.0
    assert ai_usage.spent_in_month(conn, MONTH) == 0.0
    assert _lines(config)[-1]["cost_usd"] == 0.0


def test_record_usage_prompt_version_override(conn, cfg):
    """The bot names its own prompt without entering PROMPT_VERSIONS, which is the curation's."""
    suggestions.record_usage(conn, cfg, "bot_turn", **_usage_args(prompt_version="7"))
    assert _lines(cfg)[-1]["prompt_version"] == "7"

    suggestions.record_usage(conn, cfg, "enrich", **_usage_args())
    assert _lines(cfg)[-1]["prompt_version"] == suggestions.PROMPT_VERSIONS["enrich"]

    suggestions.record_usage(conn, cfg, "bot_turn", **_usage_args())
    assert _lines(cfg)[-1]["prompt_version"] == ""


def test_record_usage_accumulates_in_the_same_month(conn, cfg):
    suggestions.record_usage(conn, cfg, "bot_turn", **_usage_args(input_tokens=1_000_000, output_tokens=0))
    suggestions.record_usage(conn, cfg, "bot_turn", **_usage_args(input_tokens=1_000_000, output_tokens=0))

    assert ai_usage.spent_in_month(conn, MONTH) == pytest.approx(2.0)
    assert len(_lines(cfg)) == 2


def test_record_usage_defaults_the_month_to_now(conn, cfg):
    from datetime import datetime

    suggestions.record_usage(conn, cfg, "bot_turn", **_usage_args(month=None, input_tokens=1_000_000, output_tokens=0))

    assert ai_usage.spent_in_month(conn, datetime.now().strftime("%Y-%m")) == pytest.approx(1.0)


# --- narrate (ticket 163) -----------------------------------------------------------------------

FACTS = "Banana prata · R$ 3,79 (mais barato) · 16/09/2026 (há 2 dias) · Costa Atacadao"


def _persona_response(reply: str) -> LlmResponse:
    return LlmResponse(json.dumps({"reply": reply}), 400, 40)


def test_narrate_returns_grounded_text(conn, cfg):
    client = ScriptedLlmClient([_persona_response("Banana a R$ 3,79 na Costa Atacadao. Foi o melhor preço.")])

    reply = suggestions.narrate(conn, cfg, client, "histórico de preço de um produto", FACTS, MONTH)

    assert reply == "Banana a R$ 3,79 na Costa Atacadao. Foi o melhor preço."
    assert _lines(cfg)[-1]["call_kind"] == "persona"
    assert _lines(cfg)[-1]["prompt_version"] == suggestions.PROMPT_VERSIONS["persona"]


def test_narrate_rejects_a_price_not_in_the_facts(conn, cfg):
    """The model naming a number it was not handed is exactly what this guard exists to catch."""
    client = ScriptedLlmClient([_persona_response("Essa banana já chegou a custar R$ 9,99, um absurdo.")])

    assert suggestions.narrate(conn, cfg, client, "histórico de preço de um produto", FACTS, MONTH) is None


def test_narrate_accepts_a_reply_with_no_price_mentioned(conn, cfg):
    """The write-confirmation case: facts have no money in them, so the guard is a no-op."""
    client = ScriptedLlmClient([_persona_response("Já ajeitei essa categoria, era hora.")])

    reply = suggestions.narrate(conn, cfg, client, "confirmação de uma alteração no catálogo", "produto marcado com a tag hortifruti", MONTH)

    assert reply == "Já ajeitei essa categoria, era hora."


def test_narrate_empty_facts_short_circuits(conn, cfg):
    client = ScriptedLlmClient([_persona_response("não deveria rodar")])

    assert suggestions.narrate(conn, cfg, client, "contexto qualquer", "", MONTH) is None
    assert client.calls == []


def test_narrate_not_configured_returns_none(conn, cfg):
    config = replace(cfg, ai_api_key=None)
    client = ScriptedLlmClient([_persona_response("x")])

    assert suggestions.narrate(conn, config, client, "contexto qualquer", FACTS, MONTH) is None
    assert client.calls == []


def test_narrate_client_raises_returns_none(conn, cfg):
    assert suggestions.narrate(conn, cfg, RaisingLlmClient(), "contexto qualquer", FACTS, MONTH) is None


def test_narrate_malformed_json_shape_returns_none(conn, cfg):
    assert suggestions.narrate(conn, cfg, ScriptedLlmClient([LlmResponse(json.dumps({"reply": 123}), 10, 10)]), "c", FACTS, MONTH) is None
    assert suggestions.narrate(conn, cfg, ScriptedLlmClient([LlmResponse(json.dumps({"nope": "x"}), 10, 10)]), "c", FACTS, MONTH) is None
