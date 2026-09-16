import json
from pathlib import Path

import pytest

from _fakes import ScriptedLlmClient
from julius.config import Config
from julius.domain.models import AppliedAction, ContentSuggestion, Product, ProductProposal
from julius.infra.llm_client import LlmResponse
from julius.parsers.df import DFReceiptParser
from julius.repositories import prices, products, stores
from julius.services import catalog, curation

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CNPJ = "00000000000191"
NO_AI = Config(Path("unused"), None, None, None, 1.0, None, None)


@pytest.fixture
def cfg(db_path) -> Config:
    return Config(
        db_path=db_path,
        ai_api_key="secret",
        ai_base_url="https://api.example/v1",
        ai_model="cheap-1",
        ai_budget_usd=5.0,
        ai_input_price_usd_per_1m=1.0,
        ai_output_price_usd_per_1m=1.0,
    )


def _import(conn, name: str) -> None:
    receipt = DFReceiptParser().parse((FIXTURES_DIR / name).read_text(encoding="utf-8"), source=name)
    with conn:
        stores.ensure_store(conn, receipt.store_cnpj, receipt.store_legal_name, receipt.store_address)
        for item in receipt.items:
            product_id = products.resolve_product_id(conn, receipt.store_cnpj, item.product_code, item.description)
            prices.insert_price(conn, receipt, item, product_id)


def _id_of(conn, name: str) -> int:
    return next(product_id for product_id, n in products.product_names(conn) if n == name)


def _enrich_response(items: list[dict], input_tokens: int = 1000, output_tokens: int = 500) -> LlmResponse:
    return LlmResponse(json.dumps({"products": items}), input_tokens, output_tokens)


def _merge_response(items: list[dict], input_tokens: int = 1000, output_tokens: int = 500) -> LlmResponse:
    return LlmResponse(json.dumps({"pairs": items}), input_tokens, output_tokens)


def test_pending_product_ids_lists_untagged_in_id_order(conn):
    _import(conn, "qrcode-3.html")
    ids = sorted(pid for pid, _ in products.product_names(conn))
    catalog.tag_product(conn, ids[0], "hortifruti")
    assert curation.pending_product_ids(conn) == ids[1:]


def test_propose_single_known_tag_is_auto(conn, cfg):
    _import(conn, "qrcode.html")
    pid = _id_of(conn, "LING FGO RESF AURORA kg")
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich_response([{"id": pid, "readable_name": "Linguiça Aurora", "tags": ["carnes"], "content": None}])}
    )
    (proposal,) = curation.propose(conn, cfg, client, [pid])
    assert proposal.auto_tag == "carnes"


@pytest.mark.parametrize(
    ("tags", "expected_tag_is_known"),
    [(["mercearia", "bebidas"], True), (["ovos"], False)],
)
def test_propose_two_tags_or_unknown_tag_is_not_auto(conn, cfg, tags, expected_tag_is_known):
    _import(conn, "qrcode.html")
    pid = _id_of(conn, "LING FGO RESF AURORA kg")
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich_response([{"id": pid, "readable_name": "X", "tags": tags, "content": None}])}
    )
    (proposal,) = curation.propose(conn, cfg, client, [pid])
    assert proposal.auto_tag is None
    assert proposal.tag_is_known is expected_tag_is_known


def test_propose_keeps_readable_name_none_for_manually_renamed_product(conn, cfg):
    _import(conn, "qrcode.html")
    pid = _id_of(conn, "REFRI PEPSI PET 2L")
    catalog.rename_product(conn, pid, "Nome Manual")
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich_response([{"id": pid, "readable_name": "Outro Nome", "tags": ["bebidas"], "content": None}])}
    )
    (proposal,) = curation.propose(conn, cfg, client, [pid])
    assert proposal.readable_name is None


def test_propose_readable_name_none_when_model_returns_same_name_ignoring_case(conn, cfg):
    _import(conn, "qrcode.html")
    pid = _id_of(conn, "REFRI PEPSI PET 2L")
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich_response([{"id": pid, "readable_name": "refri pepsi pet 2l", "tags": ["bebidas"], "content": None}])}
    )
    (proposal,) = curation.propose(conn, cfg, client, [pid])
    assert proposal.readable_name is None


def test_propose_content_none_when_already_defined(conn, cfg):
    _import(conn, "qrcode-2.html")
    (pid, name), = products.product_names(conn)
    catalog.set_product_content(conn, pid, 2, "L")
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich_response(
                [{"id": pid, "readable_name": name, "tags": ["mercearia"], "content": {"quantity": 5, "unit": "UN"}}]
            )
        }
    )
    (proposal,) = curation.propose(conn, cfg, client, [pid])
    assert proposal.content is None


def test_propose_omits_products_without_enrichment_and_ignores_unknown_ids(conn, cfg):
    _import(conn, "qrcode.html")
    pid = _id_of(conn, "LING FGO RESF AURORA kg")
    client = ScriptedLlmClient(by_kind={"enrich": _enrich_response([])})
    assert curation.propose(conn, cfg, client, [pid, 999999]) == []


def test_apply_renames_tags_and_sets_content_in_one_transaction(conn):
    _import(conn, "qrcode-2.html")
    (pid, name), = products.product_names(conn)
    proposal = ProductProposal(
        product_id=pid,
        current_name=name,
        readable_name="Nome Legível",
        tags=("mercearia",),
        tag_is_known=True,
        content=ContentSuggestion(2.0, "L"),
        kind=None,
    )

    curation.apply(conn, proposal, tag="mercearia", content=True, kind=False)

    product = products.get_product(conn, pid)
    assert product.canonical_name == "Nome Legível"
    assert product.tags == ("mercearia",)
    assert (product.content_quantity, product.content_unit) == (2.0, "L")
    assert products.has_raw_name(conn, pid) is False


def test_apply_with_tag_none_and_content_false_only_renames(conn):
    _import(conn, "qrcode-2.html")
    (pid, name), = products.product_names(conn)
    proposal = ProductProposal(pid, name, "Nome Legível", ("mercearia",), True, ContentSuggestion(2.0, "L"), None)

    curation.apply(conn, proposal, tag=None, content=False, kind=False)

    product = products.get_product(conn, pid)
    assert product.canonical_name == "Nome Legível"
    assert product.tags == ()
    assert product.content_quantity is None


def test_apply_blank_tag_raises_and_changes_nothing(conn):
    _import(conn, "qrcode-2.html")
    (pid, name), = products.product_names(conn)
    proposal = ProductProposal(pid, name, "Nome Legível", ("mercearia",), True, None, None)

    with pytest.raises(ValueError, match="blank"):
        curation.apply(conn, proposal, tag="   ", content=False, kind=False)

    product = products.get_product(conn, pid)
    assert product.canonical_name == name
    assert product.tags == ()


def _import_all_five(conn):
    for name in ("qrcode.html", "qrcode-2.html", "qrcode-3.html", "qrcode-4.html", "qrcode-5.html"):
        _import(conn, name)


def test_duplicate_candidates_on_five_receipts_include_the_three_true_pairs_and_nothing_below_cutoff(conn):
    _import_all_five(conn)
    pairs = curation.duplicate_candidates(conn)

    ids = {(a.id, b.id) for a, b, _ in pairs}
    expected = {
        tuple(sorted((_id_of(conn, "TOMATE ITALIANO UNIAO kg"), _id_of(conn, "TOMATE ITALIANO kg")))),
        tuple(sorted((_id_of(conn, "CEBOLA UNIAO kg"), _id_of(conn, "CEBOLA kg")))),
    }
    sacola_ids = sorted(pid for pid, name in products.product_names(conn) if name == "SACOLA REUTILIZAVEL UND")
    expected.add(tuple(sacola_ids))

    assert expected <= ids
    assert all(score >= 0.75 for _, _, score in pairs)
    assert len(pairs) <= curation.MAX_DUPLICATE_PAIRS
    scores = [score for _, _, score in pairs]
    assert scores == sorted(scores, reverse=True)


def test_duplicate_candidates_scoped_to_ids_only_pairs_them_with_others(conn):
    _import_all_five(conn)
    tomate_uniao_id = _id_of(conn, "TOMATE ITALIANO UNIAO kg")

    pairs = curation.duplicate_candidates(conn, [tomate_uniao_id])

    assert pairs
    assert all(tomate_uniao_id in (a.id, b.id) for a, b, _ in pairs)


def test_judge_duplicates_keeps_only_same_product_true_with_ai_attached(conn, cfg):
    a, b, c, d = Product(1, "A"), Product(2, "B"), Product(3, "C"), Product(4, "D")
    candidates = [(a, b, 0.9), (c, d, 0.8)]
    client = ScriptedLlmClient(
        by_kind={
            "merge": _merge_response(
                [
                    {"id": 1, "rationale": "sim", "same_product": True, "confidence": 0.9},
                    {"id": 2, "rationale": "não", "same_product": False, "confidence": 0.6},
                ]
            )
        }
    )

    result = curation.judge_duplicates(conn, cfg, client, candidates)

    assert len(result) == 1
    assert (result[0].product_a, result[0].product_b) == (a, b)
    assert result[0].ai.same_product is True


def test_judge_duplicates_without_ai_returns_empty(conn):
    candidates = [(Product(1, "A"), Product(2, "B"), 0.9)]
    client = ScriptedLlmClient(
        by_kind={"merge": _merge_response([{"id": 1, "rationale": "x", "same_product": True, "confidence": 0.9}])}
    )
    assert curation.judge_duplicates(conn, NO_AI, client, candidates) == []


def test_judge_duplicates_empty_candidates_does_not_call(conn, cfg):
    client = ScriptedLlmClient(by_kind={"merge": _merge_response([])})
    assert curation.judge_duplicates(conn, cfg, client, []) == []
    assert client.calls == []


def _one_product(conn) -> tuple[int, str]:
    _import(conn, "qrcode-2.html")
    (pid, name), = products.product_names(conn)
    return pid, name


def test_propose_fills_kind_for_product_without_one(conn, cfg):
    pid, name = _one_product(conn)
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich_response([{"id": pid, "readable_name": "Tomate", "tags": ["hortifruti"], "kind": "tomate"}])}
    )

    (proposal,) = curation.propose(conn, cfg, client, [pid])

    assert proposal.kind == "tomate"


def test_propose_keeps_human_kind(conn, cfg):
    pid, name = _one_product(conn)
    catalog.set_product_kind(conn, pid, "tomate")
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich_response(
                [{"id": pid, "readable_name": "Tomate", "tags": ["hortifruti"], "kind": "tomate italiano"}]
            )
        }
    )

    (proposal,) = curation.propose(conn, cfg, client, [pid])

    assert proposal.kind is None


def test_propose_ignores_kind_equal_to_current(conn, cfg):
    pid, _ = _one_product(conn)
    catalog.set_product_kind(conn, pid, "açaí")
    client = ScriptedLlmClient(
        by_kind={"enrich": _enrich_response([{"id": pid, "readable_name": "Açaí", "tags": ["doces"], "kind": "ACAI"}])}
    )

    (proposal,) = curation.propose(conn, cfg, client, [pid])

    assert proposal.kind is None


def test_propose_passes_known_kinds_to_ai(conn, cfg):
    _import(conn, "qrcode.html")
    ids = [pid for pid, _ in products.product_names(conn)][:3]
    catalog.set_product_kind(conn, ids[0], "tomate")
    catalog.set_product_kind(conn, ids[1], "cebola")
    client = ScriptedLlmClient(by_kind={"enrich": _enrich_response([])})

    curation.propose(conn, cfg, client, [ids[2]])

    assert 'tipos: ["cebola", "tomate"]' in client.calls[0][1]


def test_apply_kind_returns_action(conn):
    pid, name = _one_product(conn)
    proposal = ProductProposal(pid, name, None, ("hortifruti",), True, None, "Tomate")

    actions = curation.apply(conn, proposal, tag=None, content=False, kind=True)

    assert actions == [AppliedAction(pid, "kind", None, "tomate")]
    assert products.get_product(conn, pid).kind == "tomate"


def test_apply_kind_action_reports_stored_spelling(conn):
    _import(conn, "qrcode.html")
    ids = [pid for pid, _ in products.product_names(conn)][:2]
    catalog.set_product_kind(conn, ids[0], "açaí")
    proposal = ProductProposal(ids[1], "X", None, ("doces",), True, None, "acai")

    (action,) = curation.apply(conn, proposal, tag=None, content=False, kind=True)

    assert action.after == "açaí"


def test_apply_returns_one_action_per_changed_field(conn):
    pid, name = _one_product(conn)
    proposal = ProductProposal(pid, name, "Picanha", ("carnes",), True, ContentSuggestion(0.5, "KG"), "picanha")

    actions = curation.apply(conn, proposal, tag="carnes", content=True, kind=True)

    assert [action.field for action in actions] == ["name", "tag", "content", "kind"]
    assert actions[0].before == name
    assert actions[1] == AppliedAction(pid, "tag", None, "carnes")
    assert actions[2] == AppliedAction(pid, "content", None, "0.5 KG")
    assert actions[3] == AppliedAction(pid, "kind", None, "picanha")


def test_apply_skips_unchanged_fields(conn):
    pid, name = _one_product(conn)
    proposal = ProductProposal(pid, name, None, ("carnes",), True, ContentSuggestion(0.5, "KG"), "picanha")

    assert curation.apply(conn, proposal, tag=None, content=False, kind=False) == []
    product = products.get_product(conn, pid)
    assert (product.canonical_name, product.tags, product.kind) == (name, (), None)


def test_apply_content_action_formats_value(conn):
    pid, name = _one_product(conn)
    proposal = ProductProposal(pid, name, None, ("carnes",), True, ContentSuggestion(0.5, "KG"), None)

    (action,) = curation.apply(conn, proposal, tag=None, content=True, kind=False)

    assert action == AppliedAction(pid, "content", None, "0.5 KG")


def test_apply_content_action_reports_previous_value(conn):
    pid, name = _one_product(conn)
    catalog.set_product_content(conn, pid, 2, "L")
    proposal = ProductProposal(pid, name, None, ("bebidas",), True, ContentSuggestion(1.5, "L"), None)

    (action,) = curation.apply(conn, proposal, tag=None, content=True, kind=False)

    assert (action.before, action.after) == ("2 L", "1.5 L")


def test_apply_kind_requested_but_proposal_empty(conn):
    pid, name = _one_product(conn)
    proposal = ProductProposal(pid, name, None, ("carnes",), True, None, None)

    assert curation.apply(conn, proposal, tag=None, content=False, kind=True) == []
    assert products.get_product(conn, pid).kind is None
