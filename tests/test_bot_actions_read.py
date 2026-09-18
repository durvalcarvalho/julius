import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from conftest import copied_fixtures
from julius.bot.actions import READ_ACTIONS, Deps, ProductListing, StoreListing, resolve_product, resolve_store
from julius.config import Config
from julius.domain.models import SearchOutcome, StoreComparison
from julius.parsers.df import DFReceiptParser
from julius.services import catalog, importing, search

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


def test_compare_stores_returns_comparison(stocked, cfg):
    result, state = _run(READ_ACTIONS[1], {}, stocked, cfg)

    assert isinstance(result.output, StoreComparison)
    assert state["calls"] == 1


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


def test_matching_product_ids_is_public_and_drives_the_same_search(stocked):
    ids = search.matching_product_ids(stocked, "picanha")

    assert ids
    assert ids == {record.product_id for record in search.search_prices(stocked, term="picanha")}
    assert not hasattr(search, "_matching_ids")
