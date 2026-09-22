import json

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from conftest import copied_fixtures
from julius.bot.actions import READ_ACTIONS, Deps, ProductListing, ShoppingComparison, StoreListing, resolve_product, resolve_store
from julius.config import Config
from julius.domain.models import PriceCheck, SearchOutcome
from julius.parsers.df import DFReceiptParser
from julius.repositories.products import resolve_product_id
from julius.repositories.stores import ensure_store
from julius.services import catalog, comparison as comparison_service, importing, search

GAVE_UP = "desisti"


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


@pytest.fixture
def stocked(conn, tmp_path):
    """The three real receipts: three stores, 21 products, two different tomatoes."""
    fixtures = copied_fixtures(tmp_path)
    for name in ("qrcode.html", "qrcode-2.html", "qrcode-3.html"):
        importing.import_receipt(conn, fixtures / name, DFReceiptParser())
    return conn


def _tool_name(action) -> str:
    """PydanticAI exposes an output function as `final_result_<name>`, not by its bare name.
    Deriving it from __name__ means a renamed action cannot drift into the unknown-tool path,
    where the run would still finish -- with the model's prose as the output."""
    return f"final_result_{action.__name__}"


def _agent(action, args):
    """A model that calls `action` once, then gives up in prose. One model call means the action
    ended the run; two means it did not."""
    state = {"calls": 0}

    def model(messages, info):
        state["calls"] += 1
        if state["calls"] == 1:
            return ModelResponse(parts=[ToolCallPart(_tool_name(action), args)])
        return ModelResponse(parts=[TextPart(GAVE_UP)])

    return Agent(FunctionModel(model), deps_type=Deps, output_type=[str, *READ_ACTIONS]), state


def _run(action, args, conn, cfg):
    agent, state = _agent(action, args)
    result = agent.run_sync("pergunta do usuário", deps=Deps(conn=conn, config=cfg))
    return result, state


def _retries(result) -> list[str]:
    return [
        part.content
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if isinstance(part, RetryPromptPart)
    ]


def test_the_output_tool_is_named_after_the_action(stocked, cfg):
    """Pins the naming convention itself: if a future PydanticAI exposed bare names, every test
    here would still pass while exercising the unknown-tool path instead of the action."""
    agent, _ = _agent(READ_ACTIONS[0], {"words": "picanha"})
    names = set()

    def peek(messages, info):
        names.update(tool.name for tool in info.output_tools)
        return ModelResponse(parts=[TextPart(GAVE_UP)])

    Agent(FunctionModel(peek), deps_type=Deps, output_type=[str, *READ_ACTIONS]).run_sync(
        "x", deps=Deps(conn=stocked, config=cfg)
    )

    assert names == {f"final_result_{action.__name__}" for action in READ_ACTIONS}


# --- resolution ------------------------------------------------------------------


def test_resolve_product_by_id(stocked):
    wanted = catalog.list_products(stocked)[0]

    assert resolve_product(stocked, str(wanted.id)).id == wanted.id


def test_resolve_product_unknown_id_retries(stocked):
    with pytest.raises(Exception, match="Não existe produto com id 99999"):
        resolve_product(stocked, "99999")


def test_resolve_product_by_unique_name(stocked):
    assert "PICANHA" in resolve_product(stocked, "picanha").canonical_name.upper()


def test_resolve_product_ambiguous_name_lists_candidates(stocked):
    """Two stores sell a tomato under different codes -- exactly what `produtos fundir` exists for,
    and what the model must not pick between on its own."""
    with pytest.raises(Exception) as error:
        resolve_product(stocked, "tomate")

    message = str(error.value)
    assert "Mais de um produto combina" in message
    assert message.count(" · ") >= 2
    assert "chame de novo com o id" in message


def test_resolve_product_no_match_suggests_or_points_to_listing(stocked):
    with pytest.raises(Exception, match="Parecidos:"):
        resolve_product(stocked, "pikana")

    with pytest.raises(Exception, match="list_products"):
        resolve_product(stocked, "xyzabc")


def test_resolve_store_by_cnpj_and_by_nickname(stocked):
    by_cnpj = resolve_store(stocked, "27.289.076/0013-79")
    by_name = resolve_store(stocked, "costa")

    assert by_cnpj.cnpj == "27289076001379"
    assert by_name.cnpj == by_cnpj.cnpj

    with pytest.raises(Exception, match="Nenhum mercado chamado"):
        resolve_store(stocked, "zzz")

    with pytest.raises(Exception, match="Nenhum mercado com o CNPJ"):
        resolve_store(stocked, "00.000.000/0000-00")


# --- actions, driven by the agent -------------------------------------------------


def test_search_prices_returns_outcome(stocked, cfg):
    result, state = _run(READ_ACTIONS[0], {"words": "picanha"}, stocked, cfg)

    assert isinstance(result.output, SearchOutcome)
    assert result.output.records
    assert state["calls"] == 1, "the action must end the run, not hand control back to the model"


def test_search_prices_detects_a_tag_inside_the_words(stocked, cfg):
    product = resolve_product(stocked, "picanha")
    catalog.tag_product(stocked, product.id, "carnes")

    result, _ = _run(READ_ACTIONS[0], {"words": "picanha carnes"}, stocked, cfg)

    assert result.output.tag == "carnes"


def test_search_prices_without_words_or_tag_retries(stocked, cfg):
    result, state = _run(READ_ACTIONS[0], {"words": ""}, stocked, cfg)

    assert any("Informe um termo de busca ou uma tag." in content for content in _retries(result))
    assert state["calls"] == 2, "the model got a second turn, which is what a retry is for"
    assert result.output == GAVE_UP


def test_search_prices_with_a_limit_below_one_retries(stocked, cfg):
    result, _ = _run(READ_ACTIONS[0], {"words": "picanha", "limit": 0}, stocked, cfg)

    assert any("limit precisa ser pelo menos 1" in content for content in _retries(result))


def _tomato_ids(stocked) -> tuple[int, int]:
    ids = [product.id for product in catalog.list_products(stocked) if "TOMATE" in product.canonical_name.upper()]
    assert len(ids) >= 2, "the fixture is documented to carry two different tomatoes"
    return ids[0], ids[1]


def test_compare_stores_action_requires_items(stocked, cfg):
    result, state = _run(READ_ACTIONS[1], {"items": ()}, stocked, cfg)

    assert any("Informe pelo menos um item" in content for content in _retries(result))
    assert state["calls"] == 2


def test_compare_stores_action_blank_items_are_ignored(stocked, cfg):
    a, b = _tomato_ids(stocked)
    catalog.set_product_kind(stocked, a, "tomate")
    catalog.set_product_kind(stocked, b, "tomate")

    result, _ = _run(READ_ACTIONS[1], {"items": ("  ", "tomate")}, stocked, cfg)

    assert isinstance(result.output, ShoppingComparison)
    assert result.output.comparison.comparisons

    blank_only, state = _run(READ_ACTIONS[1], {"items": ("  ",)}, stocked, cfg)
    assert any("Informe pelo menos um item" in content for content in _retries(blank_only))


def test_compare_stores_action_matches_and_compares(stocked, cfg):
    a, b = _tomato_ids(stocked)
    catalog.set_product_kind(stocked, a, "tomate")
    catalog.set_product_kind(stocked, b, "tomate")

    result, state = _run(READ_ACTIONS[1], {"items": ("tomate",)}, stocked, cfg)

    assert isinstance(result.output, ShoppingComparison)
    assert [c.kind for c in result.output.comparison.comparisons] == ["tomate"]
    assert result.output.verdict is not None
    assert result.output.unmatched_terms == ()
    assert state["calls"] == 1


def test_compare_stores_action_reports_unmatched(stocked, cfg):
    a, b = _tomato_ids(stocked)
    catalog.set_product_kind(stocked, a, "tomate")
    catalog.set_product_kind(stocked, b, "tomate")

    result, _ = _run(READ_ACTIONS[1], {"items": ("tomate", "xyzabc")}, stocked, cfg)

    assert [c.kind for c in result.output.comparison.comparisons] == ["tomate"]
    assert result.output.unmatched_terms == ("xyzabc",)


def test_compare_stores_action_all_unmatched_returns_empty_comparison(stocked, cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(comparison_service, "compare_stores", lambda *a, **k: calls.append((a, k)))

    result, _ = _run(READ_ACTIONS[1], {"items": ("xyzabc",)}, stocked, cfg)

    assert result.output.comparison.comparisons == ()
    assert result.output.verdict is None
    assert result.output.unmatched_terms == ("xyzabc",)
    assert calls == [], "compare_stores must not be called when nothing matched"


def _onion_id(stocked) -> int:
    (onion,) = [p.id for p in catalog.list_products(stocked) if "CEBOLA" in p.canonical_name.upper()]
    return onion


def _add_kind_ambiguous_brand(conn) -> None:
    """Same shape as `test_match_kind_ambiguous_brand_fallback_stays_unresolved`
    (test_services_search.py): two real products, "pepsi" matches both by name, and they disagree
    on kind -- `_match_kind_via_product` refuses, `kind_candidates` has both to offer."""
    ensure_store(conn, "00000000000099", "Synthetic store")
    soda = resolve_product_id(conn, "00000000000099", "s1", "PEPSI REFRIGERANTE PET 2L")
    snack = resolve_product_id(conn, "00000000000099", "s2", "PEPSICO SNACK BATATA 100G")
    catalog.set_product_kind(conn, soda, "refrigerante")
    catalog.set_product_kind(conn, snack, "salgadinho")


def test_check_price_action_ambiguous_brand_asks_instead_of_guessing(stocked, cfg):
    _add_kind_ambiguous_brand(stocked)

    result, state = _run(READ_ACTIONS[4], {"item": "pepsi", "price": 10.0}, stocked, cfg)

    retries = _retries(result)
    assert any("refrigerante" in content and "salgadinho" in content for content in retries)
    assert any("Pergunte à pessoa qual" in content for content in retries)
    assert state["calls"] == 2, "a ModelRetry gives the model a second turn, same as any other one"


def test_compare_stores_action_ambiguous_brand_aborts_the_whole_call(stocked, cfg):
    """RF3/Decisão 3 of docs/design/kind-resolution-in-routing.md: tudo-ou-nada, mesmo precedente
    de resolve_product -- um item ambíguo no meio da lista aborta a chamada inteira, mesmo com
    "tomate" já resolvido antes dele."""
    _add_kind_ambiguous_brand(stocked)
    a, b = _tomato_ids(stocked)
    catalog.set_product_kind(stocked, a, "tomate")
    catalog.set_product_kind(stocked, b, "tomate")

    result, state = _run(READ_ACTIONS[1], {"items": ("tomate", "pepsi")}, stocked, cfg)

    retries = _retries(result)
    assert any("refrigerante" in content and "salgadinho" in content for content in retries)
    assert not isinstance(result.output, ShoppingComparison), "the call must abort, not return a partial result"


def test_check_price_action_pre_existing_kind_tie_still_resolves_silently(stocked, cfg):
    """Limite de escopo da Decisão 3 (docs/design/kind-resolution-in-routing.md): o empate já
    aceito do match direto contra o vocabulário de kind (v2.10, KIND_MATCH_CUTOFF -- "leite" ->
    "creme de leite") não é a ambiguidade nova que pergunta; continua resolvendo em silêncio."""
    ensure_store(stocked, "00000000000098", "Synthetic store")
    condensed = resolve_product_id(stocked, "00000000000098", "c1", "LEITE CONDENSADO 395G")
    cream = resolve_product_id(stocked, "00000000000098", "c2", "CREME DE LEITE 200G")
    catalog.set_product_kind(stocked, condensed, "leite condensado")
    catalog.set_product_kind(stocked, cream, "creme de leite")

    result, state = _run(READ_ACTIONS[4], {"item": "leite", "price": 10.0}, stocked, cfg)

    assert state["calls"] == 1, "must not retry -- the tie resolves silently, same as today"
    assert result.output.kind == "creme de leite"


def test_compare_stores_action_reports_requested_count_and_single_store_kinds(stocked, cfg):
    """RF1/RF2 (docs/requirements/shopping-verdict-shape.md): a term that matches a known kind
    but has price in only one market must not vanish -- it goes to `single_store_kinds`, distinct
    from `unmatched_terms` (a term that matched no kind at all)."""
    a, b = _tomato_ids(stocked)
    catalog.set_product_kind(stocked, a, "tomate")
    catalog.set_product_kind(stocked, b, "tomate")
    onion = _onion_id(stocked)
    catalog.set_product_kind(stocked, onion, "cebola")  # only 1 store in this fixture -> single-store kind

    result, _ = _run(READ_ACTIONS[1], {"items": ("tomate", "cebola", "xyzabc")}, stocked, cfg)

    assert [c.kind for c in result.output.comparison.comparisons] == ["tomate"]
    assert result.output.single_store_kinds == ("cebola",)
    assert result.output.unmatched_terms == ("xyzabc",)
    assert result.output.requested_count == 3


def test_compare_stores_action_logs_the_match(stocked, cfg):
    """The only record of what `compare_stores` actually resolved -- without it, diagnosing a
    silently-dropped item means rerunning `match_kind` by hand against production, exactly what
    this session had to do (docs/design/shopping-verdict-shape.md, Decisão 2)."""
    a, b = _tomato_ids(stocked)
    catalog.set_product_kind(stocked, a, "tomate")
    catalog.set_product_kind(stocked, b, "tomate")

    _run(READ_ACTIONS[1], {"items": ("tomate", "xyzabc")}, stocked, cfg)

    lines = cfg.query_log_path.read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[-1])
    assert record["action"] == "compare_stores"
    assert record["channel"] == "bot"
    assert record["items"] == ["tomate", "xyzabc"]
    assert record["matched_kinds"] == ["tomate"]
    assert record["unmatched_terms"] == ["xyzabc"]


def test_list_products_filters_by_containing(stocked, cfg):
    everything, _ = _run(READ_ACTIONS[2], {}, stocked, cfg)
    tomatoes, _ = _run(READ_ACTIONS[2], {"containing": "tomate"}, stocked, cfg)

    assert isinstance(everything.output, ProductListing)
    assert len(everything.output.products) == 21
    assert tomatoes.output.containing == "tomate"
    assert tomatoes.output.products
    assert all("TOMATE" in product.canonical_name.upper() for product in tomatoes.output.products)


def test_list_products_of_an_empty_catalogue_says_so(conn, cfg):
    result, _ = _run(READ_ACTIONS[2], {}, conn, cfg)

    assert result.output == ProductListing(products=(), containing=None)


def test_list_stores_returns_listing(stocked, cfg):
    result, _ = _run(READ_ACTIONS[3], {}, stocked, cfg)

    assert isinstance(result.output, StoreListing)
    assert len(result.output.stores) == 3


def test_check_price_action_unknown_item_returns_reason(stocked, cfg):
    result, _ = _run(READ_ACTIONS[4], {"item": "xyzabc", "price": 10.0}, stocked, cfg)

    assert result.output.reason == "unknown_item"
    assert result.output.kind is None


@pytest.mark.parametrize("price", [0.0, -5.0])
def test_check_price_action_rejects_a_non_positive_price(stocked, cfg, price):
    """Achado real de monkey test (2026-09-22): sem esta guarda, "a picanha tá -5 reais o quilo,
    boa?" respondia "Sim, vale a pena... -111% de diferença" -- um veredito sem sentido em vez de
    pedir confirmação, a mesma disciplina que set_product_content já aplica pra quantidade."""
    result, state = _run(READ_ACTIONS[4], {"item": "picanha", "price": price}, stocked, cfg)

    assert any("preço precisa ser maior que zero" in content for content in _retries(result))
    assert state["calls"] == 2


def test_check_price_action_rejects_a_non_positive_quantity(stocked, cfg):
    result, state = _run(READ_ACTIONS[4], {"item": "picanha", "price": 10.0, "quantity": 0.0}, stocked, cfg)

    assert any("quantidade precisa ser maior que zero" in content for content in _retries(result))
    assert state["calls"] == 2


def test_check_price_action_passes_quantity_to_the_service(stocked, cfg, monkeypatch):
    """The bridge for the two-turn quantity loop (docs/design/quantity-aware-verdict.md, Decisão
    4): the action itself does no gate logic, it just forwards `quantity` -- monkeypatched here so
    the test doesn't depend on the fixture's real prices landing in the gate's middle band."""
    onion = _onion_id(stocked)
    catalog.set_product_kind(stocked, onion, "cebola")
    calls = []

    def fake_check_price(conn, kind, price, quantity=None, unit=None):
        calls.append((kind, price, quantity, unit))
        return PriceCheck(
            kind=kind, verdict=True, informed_price=price, reference_price=1.0, reference_unit="KG",
            reference_store="Loja", reference_at="2026-09-01T00:00:00", diff_pct=0.0, reason=None,
        )

    monkeypatch.setattr(comparison_service, "check_price", fake_check_price)

    result, _ = _run(READ_ACTIONS[4], {"item": "cebola", "price": 12.0, "quantity": 3.0}, stocked, cfg)

    assert calls == [("cebola", 12.0, 3.0, None)]


def test_check_price_action_passes_unit_to_the_service(stocked, cfg, monkeypatch):
    """The bridge for the ambiguous_unit loop (real bug, 2026-09-22): before this, "por quilo"
    after check_price asked "por peso ou por unidade" had no parameter to answer through, and the
    conversation asked the same question forever."""
    onion = _onion_id(stocked)
    catalog.set_product_kind(stocked, onion, "cebola")
    calls = []

    def fake_check_price(conn, kind, price, quantity=None, unit=None):
        calls.append((kind, price, quantity, unit))
        return PriceCheck(
            kind=kind, verdict=True, informed_price=price, reference_price=1.0, reference_unit="KG",
            reference_store="Loja", reference_at="2026-09-01T00:00:00", diff_pct=0.0, reason=None,
        )

    monkeypatch.setattr(comparison_service, "check_price", fake_check_price)

    result, _ = _run(READ_ACTIONS[4], {"item": "cebola", "price": 8.0, "unit": "KG"}, stocked, cfg)

    assert calls == [("cebola", 8.0, None, "KG")]
    assert result.output.verdict is True


def test_matching_product_ids_is_public_and_drives_the_same_search(stocked):
    ids = search.matching_product_ids(stocked, "picanha")

    assert ids
    assert ids == {record.product_id for record in search.search_prices(stocked, term="picanha")}
    assert not hasattr(search, "_matching_ids")
