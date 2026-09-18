import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from conftest import copied_fixtures
from julius.bot import render
from julius.bot.actions import (
    READ_ACTIONS,
    WRITE_ACTIONS,
    Deps,
    PendingWrite,
    WriteFailed,
    WriteResult,
    execute,
    resolve_product,
)
from julius.config import Config
from julius.parsers.df import DFReceiptParser
from julius.services import catalog, importing

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
    fixtures = copied_fixtures(tmp_path)
    for name in ("qrcode.html", "qrcode-2.html", "qrcode-3.html"):
        importing.import_receipt(conn, fixtures / name, DFReceiptParser())
    return conn


@pytest.fixture
def deps(stocked, cfg) -> Deps:
    return Deps(conn=stocked, config=cfg)


KNOWN_ACTIONS = (*READ_ACTIONS, *WRITE_ACTIONS)


def _by_name(name: str):
    return next(action for action in KNOWN_ACTIONS if action.__name__ == name)


def _run(action_name: str, args, deps: Deps):
    action = _by_name(action_name)
    state = {"calls": 0}

    def model(messages, info):
        state["calls"] += 1
        if state["calls"] == 1:
            return ModelResponse(parts=[ToolCallPart(f"final_result_{action.__name__}", args)])
        return ModelResponse(parts=[TextPart(GAVE_UP)])

    agent = Agent(FunctionModel(model), deps_type=Deps, output_type=[str, *KNOWN_ACTIONS])
    return agent.run_sync("pedido do usuário", deps=deps), state


def _retries(result) -> list[str]:
    return [
        part.content
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if isinstance(part, RetryPromptPart)
    ]


def _picanha(deps: Deps):
    return resolve_product(deps.conn, "picanha")


# --- a write action writes nothing ------------------------------------------------


def test_rename_product_returns_pending_and_writes_nothing(deps):
    before = _picanha(deps)

    result, state = _run("rename_product", {"product": "picanha", "name": "Picanha bovina"}, deps)

    pending = result.output
    assert isinstance(pending, PendingWrite)
    assert pending.action == "rename_product"
    assert pending.args == {"product_id": before.id, "name": "Picanha bovina"}
    assert before.canonical_name in pending.preview
    assert state["calls"] == 1
    assert catalog.get_product(deps.conn, before.id).canonical_name == before.canonical_name


def test_every_write_action_leaves_the_database_alone(deps):
    """The whole point of the two passes: the model can choose a write, never cause one."""
    product = _picanha(deps)
    catalog.set_product_kind(deps.conn, product.id, "picanha")
    catalog.set_product_content(deps.conn, product.id, 1, "KG")
    catalog.tag_product(deps.conn, product.id, "carnes")
    snapshot = catalog.get_product(deps.conn, product.id)
    store = catalog.list_stores(deps.conn)[0]

    calls = [
        ("rename_product", {"product": str(product.id), "name": "Outro"}),
        ("rename_store", {"store": store.cnpj, "nickname": "Outro"}),
        ("tag_product", {"product": str(product.id), "tag": "frios"}),
        ("untag_product", {"product": str(product.id), "tag": "carnes"}),
    ]
    for name, args in calls:
        outcome, _ = _run(name, args, deps)
        assert isinstance(outcome.output, PendingWrite), name

    assert catalog.get_product(deps.conn, product.id) == snapshot
    assert catalog.list_stores(deps.conn)[0] == store


# --- execute ----------------------------------------------------------------------


def test_execute_rename_product_applies_and_returns_undo(deps):
    before = _picanha(deps)
    pending, _ = _run("rename_product", {"product": "picanha", "name": "Picanha bovina"}, deps)

    result = execute(deps, pending.output)

    assert isinstance(result, WriteResult)
    assert catalog.get_product(deps.conn, before.id).canonical_name == "Picanha bovina"
    assert result.undo == f'julius produtos renomear {before.id} "{before.canonical_name}"'
    assert before.canonical_name in result.summary


def test_rename_store_pending_and_execute(deps):
    store = next(s for s in catalog.list_stores(deps.conn) if s.cnpj == "27289076001379")

    by_cnpj, _ = _run("rename_store", {"store": "27.289.076/0013-79", "nickname": "Atacadão"}, deps)
    by_nickname, _ = _run("rename_store", {"store": "costa", "nickname": "Atacadão"}, deps)
    assert by_cnpj.output.args == by_nickname.output.args == {"cnpj": store.cnpj, "nickname": "Atacadão"}

    result = execute(deps, by_cnpj.output)

    assert next(s for s in catalog.list_stores(deps.conn) if s.cnpj == store.cnpj).nickname == "Atacadão"
    assert result.undo == f'julius mercados renomear {store.cnpj} "{store.nickname}"'


def test_tag_and_untag_pending_and_execute(deps):
    product = _picanha(deps)

    tagged, _ = _run("tag_product", {"product": str(product.id), "tag": "Carnes"}, deps)
    assert tagged.output.args["tag"] == "carnes", "the tag is lowercased before it is stored"
    tag_result = execute(deps, tagged.output)
    assert "carnes" in catalog.get_product(deps.conn, product.id).tags
    assert tag_result.undo == f"julius produtos tag {product.id} carnes --remover"

    untagged, _ = _run("untag_product", {"product": str(product.id), "tag": "carnes"}, deps)
    untag_result = execute(deps, untagged.output)
    assert "carnes" not in catalog.get_product(deps.conn, product.id).tags
    assert untag_result.undo == f"julius produtos tag {product.id} carnes"


def test_tag_already_present_retries(deps):
    product = _picanha(deps)
    catalog.tag_product(deps.conn, product.id, "carnes")

    result, _ = _run("tag_product", {"product": str(product.id), "tag": "carnes"}, deps)

    assert any(f"O produto {product.id} já tem a tag «carnes»." in c for c in _retries(result))


def test_untag_absent_retries(deps):
    product = _picanha(deps)

    result, _ = _run("untag_product", {"product": str(product.id), "tag": "carnes"}, deps)

    assert any("não tem a tag «carnes»; tem: nenhuma." in c for c in _retries(result))


@pytest.mark.parametrize(
    ("action", "args", "expected"),
    [
        ("rename_product", {"product": "picanha", "name": "   "}, "O nome não pode ficar vazio."),
        ("rename_store", {"store": "costa", "nickname": ""}, "O apelido não pode ficar vazio."),
        ("tag_product", {"product": "picanha", "tag": " "}, "A tag não pode ficar vazio."),
    ],
)
def test_blank_values_retry(deps, action, args, expected):
    result, _ = _run(action, args, deps)

    assert any(expected in content for content in _retries(result))


def test_execute_reads_current_state_for_undo(deps):
    """The user may have renamed it from the CLI while the button sat there. The undo has to
    restore what was actually replaced, not what the preview happened to say."""
    product = _picanha(deps)
    pending, _ = _run("rename_product", {"product": str(product.id), "name": "Do bot"}, deps)
    catalog.rename_product(deps.conn, product.id, "Do meio")

    result = execute(deps, pending.output)

    assert result.undo == f'julius produtos renomear {product.id} "Do meio"'
    assert product.canonical_name not in result.undo


def test_execute_unknown_product_fails_closed(deps):
    pending = PendingWrite("rename_product", {"product_id": 99999, "name": "X"}, "preview", "n", 0.0)

    with pytest.raises(WriteFailed, match="não existe mais"):
        execute(deps, pending)


def test_execute_unknown_action_fails(deps):
    with pytest.raises(WriteFailed, match="ação desconhecida"):
        execute(deps, PendingWrite("explode", {}, "preview", "n", 0.0))


def test_a_double_quote_in_a_name_stays_pastable(deps):
    product = _picanha(deps)
    catalog.rename_product(deps.conn, product.id, 'Picanha "premium"')
    pending, _ = _run("rename_product", {"product": str(product.id), "name": "Picanha"}, deps)

    result = execute(deps, pending.output)

    assert result.undo == f"julius produtos renomear {product.id} \"Picanha 'premium'\""


def test_two_pendings_have_distinct_nonces(deps):
    first, _ = _run("rename_product", {"product": "picanha", "name": "A"}, deps)
    second, _ = _run("rename_product", {"product": "picanha", "name": "B"}, deps)

    assert first.output.nonce != second.output.nonce
    assert first.output.created_at > 0


def test_render_pending_result_failure_escape():
    pending = PendingWrite("rename_product", {}, "Renomear «A & B» para «<C>»", "n", 0.0)

    assert render.render_pending(pending) == "⚠️ <b>Confirmar?</b>\nRenomear «A &amp; B» para «&lt;C&gt;»"
    assert render.render_result(WriteResult("feito & tal", 'julius x "a & b"')) == (
        '✅ feito &amp; tal\nDesfazer: <code>julius x "a &amp; b"</code>'
    )
    assert render.render_failure("deu <ruim> & tal") == "❌ Não executado: deu &lt;ruim&gt; &amp; tal"


def test_read_and_write_actions_are_disjoint():
    assert not set(READ_ACTIONS) & set(WRITE_ACTIONS)
