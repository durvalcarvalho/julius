import asyncio
import json

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from conftest import copied_fixtures
from julius import config as config_module
from julius.bot.actions import Deps
from julius.bot.agent import build_agent
from julius.bot.turn import ChatState, Reply, handle_text
from julius.parsers.df import DFReceiptParser
from julius.repositories import ai_usage
from julius.services import catalog, importing, suggestions

MONTH = None  # record_usage defaults to the current month, which is what the turn uses


@pytest.fixture
def cfg(tmp_path):
    return config_module.load(
        {
            "JULIUS_DB": str(tmp_path / "prices.db"),
            "JULIUS_AI_API_KEY": "k",
            "JULIUS_AI_BASE_URL": "https://x/v1",
            "JULIUS_AI_MODEL": "m",
            "JULIUS_AI_INPUT_PRICE_USD_PER_1M": "0.30",
            "JULIUS_AI_OUTPUT_PRICE_USD_PER_1M": "1.20",
            "JULIUS_AI_BUDGET_USD": "5",
        }
    )


@pytest.fixture
def deps(conn, cfg, tmp_path):
    fixtures = copied_fixtures(tmp_path)
    for name in ("qrcode.html", "qrcode-3.html"):
        importing.import_receipt(conn, fixtures / name, DFReceiptParser())
    return Deps(conn=conn, config=cfg)


def test_deps_client_defaults_to_none(deps):
    """ticket 166: additive field, every existing Deps(...) call keeps working unchanged."""
    assert deps.client is None


def _model(*responses):
    state = {"calls": 0}

    def model(messages, info):
        index = min(state["calls"], len(responses) - 1)
        state["calls"] += 1
        return responses[index]

    return FunctionModel(model), state


def _action(name, args=None):
    return ModelResponse(parts=[ToolCallPart(f"final_result_{name}", args or {})])


def _prose(text):
    return ModelResponse(parts=[TextPart(text)])


def _turn(deps, model, state=None, text="oi"):
    state = state or ChatState()
    agent = build_agent(deps.config, model=model)
    return asyncio.run(handle_text(agent, state, deps, text)), state


def _ai_lines(cfg):
    return [json.loads(line) for line in cfg.ai_log_path.read_text(encoding="utf-8").splitlines()]


def _query_lines(cfg):
    return [json.loads(line) for line in cfg.query_log_path.read_text(encoding="utf-8").splitlines()]


def test_budget_exhausted_answers_without_calling_the_model(deps):
    ai_usage.add_spent(deps.conn, suggestions._current_month(), 5.0)
    deps.conn.commit()
    model, calls = _model(_prose("nunca chamado"))

    reply, _ = _turn(deps, model, text="quanto custa picanha?")

    assert calls["calls"] == 0, "the budget check must come before the model"
    assert "esgotado" in reply.text
    assert "US$ 5.00 de US$ 5.00" in reply.text
    assert _ai_lines(deps.config)[-1]["error"] == "budget_exhausted"


def test_read_reply_is_rendered_from_the_database(deps):
    model, _ = _model(_action("search_prices", {"words": "picanha"}), _prose("PROSA DO MODELO"))

    reply, _ = _turn(deps, model, text="quanto custou a picanha?")

    assert "Preços por KG" in reply.text
    assert "R$ " in reply.text
    assert "PROSA DO MODELO" not in reply.text
    assert reply.pending is None


def test_read_turn_charges_and_logs(deps):
    model, _ = _model(_action("search_prices", {"words": "picanha"}))

    _turn(deps, model, text="picanha")

    assert suggestions.spent_this_month(deps.conn) > 0
    line = _ai_lines(deps.config)[-1]
    assert line["call_kind"] == "bot_turn"
    assert line["prompt_version"] == "1"
    assert line["raw_response"] == "SearchOutcome"
    assert line["input_tokens"] > 0

    query = _query_lines(deps.config)[-1]
    assert query["channel"] == "bot"
    assert query["term_used"] == "picanha"
    assert query["result_count"] > 0
    assert query["ai_fallback"] is False


def test_write_turn_creates_pending_and_writes_nothing(deps):
    product = next(p for p in catalog.list_products(deps.conn) if "PICANHA" in p.canonical_name.upper())
    model, _ = _model(_action("rename_product", {"product": str(product.id), "name": "Picanha bovina"}))

    reply, state = _turn(deps, model, text="renomeia a picanha")

    assert reply.pending is not None
    assert state.pending is reply.pending
    assert reply.text.startswith("⚠️")
    assert catalog.get_product(deps.conn, product.id).canonical_name == product.canonical_name


def test_text_while_pending_cancels_it(deps):
    product = catalog.list_products(deps.conn)[0]
    first_model, _ = _model(_action("rename_product", {"product": str(product.id), "name": "X"}))
    _, state = _turn(deps, first_model, text="renomeia")
    assert state.pending is not None

    second_model, _ = _model(_prose("beleza"))
    reply, _ = _turn(deps, second_model, state=state, text="deixa pra lá")

    assert state.pending is None
    assert reply.text.startswith("Ação anterior cancelada.")
    assert reply.text.endswith("beleza")


def test_plain_text_output_is_escaped_and_returned(deps):
    model, _ = _model(_prose("Oi <você>"))

    reply, _ = _turn(deps, model)

    assert reply.text == "Oi &lt;você&gt;"


def test_agent_exception_is_a_reply_not_a_crash(deps):
    def boom(messages, info):
        raise RuntimeError("a rede caiu")

    reply, state = _turn(deps, FunctionModel(boom), text="oi")

    assert isinstance(reply, Reply)
    assert "Não consegui falar com a IA" in reply.text
    assert _ai_lines(deps.config)[-1]["error"].startswith("agent raised")
    assert state.runs == [], "a turn that never finished is not history"


def test_history_keeps_only_the_last_three_turns_whole(deps):
    state = ChatState()
    for index in range(4):
        model, _ = _model(_prose(f"resposta {index}"))
        _turn(deps, model, state=state, text=f"pergunta {index}")

    assert len(state.runs) == 3
    flattened = state.history
    assert flattened == [message for run in state.runs for message in run]
    assert all("pergunta 0" not in str(message) for message in flattened)


def test_empty_listing_renders_the_empty_message(conn, cfg):
    empty = Deps(conn=conn, config=cfg)
    model, _ = _model(_action("list_products", {}))

    reply, _ = _turn(empty, model, text="que produtos eu tenho?")

    assert reply.text == "Nenhum produto importado ainda."


def test_a_listing_reply_carries_no_pending(deps):
    model, _ = _model(_action("list_stores", {}))

    reply, state = _turn(deps, model, text="quais mercados?")

    assert reply.pending is None and state.pending is None
    assert "Dona de Casa" in reply.text or "DONA DE CASA" in reply.text


# --- Modo A/B narration for the 4 reads (ticket 167) ------------------------------

from _fakes import ScriptedLlmClient  # noqa: E402
from julius.bot import render as render_module  # noqa: E402
from julius.bot.actions import ProductListing, StoreListing  # noqa: E402
from julius.bot.turn import _render_output  # noqa: E402
from julius.domain.models import (  # noqa: E402
    KindComparison,
    PriceRecord,
    Product,
    SearchOutcome,
    Store,
    StoreComparison,
    StorePrice,
)
from julius.infra.llm_client import LlmResponse  # noqa: E402


def _price_record(**overrides) -> PriceRecord:
    base = {
        "product_id": 1,
        "canonical_name": "Banana prata",
        "store_nickname": "Costa Atacadao",
        "unit": "KG",
        "unit_price": 3.79,
        "purchased_at": "2026-09-16T10:00:00",
    }
    return PriceRecord(**{**base, **overrides})


def _kind_group(kind: str, *entries: StorePrice) -> KindComparison:
    return KindComparison(kind=kind, unit="KG", basis="unit_price", content_unit=None, entries=entries)


def _store_entry(nickname: str, cnpj: str, price: float) -> StorePrice:
    return StorePrice(store_nickname=nickname, price=price, purchased_at="2026-09-12", product_name="Tomate", store_cnpj=cnpj)


def _store_comparison(*groups: KindComparison) -> StoreComparison:
    return StoreComparison(comparisons=groups, first_purchase="2026-09-05", last_purchase="2026-09-12", kinds_total=len(groups), kinds_single_store=0)


def _persona_reply(text: str) -> LlmResponse:
    return LlmResponse(json.dumps({"reply": text}), 400, 40)


def _with_client(deps, client):
    from dataclasses import replace

    return replace(deps, client=client)


def test_search_reply_uses_the_persona_when_small_and_a_client_is_configured(deps):
    client = ScriptedLlmClient([_persona_reply("Banana a R$ 3,79 na Costa Atacadao. Bom preço.")])
    output = SearchOutcome(records=(_price_record(),), term="banana", tag=None)

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == "Banana a R$ 3,79 na Costa Atacadao. Bom preço."
    assert "<pre>" not in reply.text
    assert client.calls, "the persona client should have been asked"


def test_search_reply_falls_back_to_a_julius_line_when_the_model_fails(deps):
    """The grounding guard in narrate() is what turn.py relies on here -- a price absent from the
    facts must never reach the user, persona or not."""
    client = ScriptedLlmClient([_persona_reply("Essa banana já custou R$ 999,99, um roubo.")])
    output = SearchOutcome(records=(_price_record(),), term="banana", tag=None)

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == render_module.search_fallback_line(output.records)
    assert "999,99" not in reply.text
    assert "<pre>" not in reply.text


def test_search_reply_above_the_old_cutoff_still_uses_only_the_persona(deps):
    """Desde o design bot-message-chunking.md (v2.8), a narração nunca mais é colada com a tabela
    crua -- ela substitui a resposta inteira, qualquer que seja a contagem dentro do teto de
    sanidade (NARRATE_MAX_RECORDS)."""
    records = tuple(_price_record(product_id=i, purchased_at=f"2026-09-{i:02d}T10:00:00") for i in range(1, 8))
    client = ScriptedLlmClient([_persona_reply("Bastante coisa registrada de banana.")])
    output = SearchOutcome(records=records, term="banana", tag=None)

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == "Bastante coisa registrada de banana."
    assert "<pre>" not in reply.text


def test_search_reply_beyond_the_sanity_ceiling_skips_the_persona(deps):
    """Acima de NARRATE_MAX_RECORDS a chamada de IA nem é tentada -- direto pra tabela crua."""
    from julius.bot.turn import NARRATE_MAX_RECORDS

    records = tuple(
        _price_record(product_id=i, purchased_at=f"2026-01-{(i % 28) + 1:02d}T10:00:00")
        for i in range(1, NARRATE_MAX_RECORDS + 2)
    )
    client = ScriptedLlmClient([_persona_reply("não deveria rodar")])
    output = SearchOutcome(records=records, term="banana", tag=None)

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == render_module.render_records(records)
    assert client.calls == []


def test_search_reply_above_the_fallback_cutoff_with_no_remark_uses_the_table(deps):
    """search_fallback_line supõe um produto só (cita records[0].canonical_name) -- acima do corte
    medido pra essa suposição, uma falha da persona cai na tabela, nunca na frase."""
    from julius.bot.turn import FALLBACK_LINE_MAX_RECORDS

    records = tuple(
        _price_record(product_id=i, purchased_at=f"2026-09-{i:02d}T10:00:00")
        for i in range(1, FALLBACK_LINE_MAX_RECORDS + 2)
    )
    client = ScriptedLlmClient([LlmResponse("", 0, 0, error="timeout")])
    output = SearchOutcome(records=records, term="banana", tag=None)

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == render_module.render_records(records)


def test_search_reply_without_a_client_is_unchanged(deps):
    output = SearchOutcome(records=(_price_record(),), term="banana", tag=None)

    reply = asyncio.run(_render_output(output, ChatState(), deps))

    assert reply.text == render_module.render_records(output.records)


def test_search_reply_with_no_results_never_calls_the_persona(deps):
    client = ScriptedLlmClient([_persona_reply("não deveria rodar")])
    output = SearchOutcome(records=(), term="produtoquenaoexiste", tag=None)

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == "Nenhum resultado."
    assert client.calls == []


def test_compare_reply_uses_the_persona_when_small(deps):
    client = ScriptedLlmClient([_persona_reply("O Assaí ganha na maioria dos grupos.")])
    output = _store_comparison(_kind_group("tomate", _store_entry("Assaí", "1", 11.89), _store_entry("Dona de Casa", "2", 14.99)))

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == "O Assaí ganha na maioria dos grupos."
    assert "<pre>" not in reply.text


def test_compare_reply_above_the_old_cutoff_still_uses_only_the_persona(deps):
    groups = tuple(_kind_group(f"tipo{i}", _store_entry("Assaí", "1", 1.0 + i), _store_entry("Dona de Casa", "2", 2.0 + i)) for i in range(7))
    client = ScriptedLlmClient([_persona_reply("Bastante grupo pra comparar.")])
    output = _store_comparison(*groups)

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == "Bastante grupo pra comparar."
    assert "<pre>" not in reply.text


def test_compare_reply_beyond_the_sanity_ceiling_skips_the_persona(deps):
    from julius.bot.turn import NARRATE_MAX_GROUPS

    groups = tuple(
        _kind_group(f"tipo{i}", _store_entry("Assaí", "1", 1.0 + i), _store_entry("Dona de Casa", "2", 2.0 + i))
        for i in range(NARRATE_MAX_GROUPS + 1)
    )
    client = ScriptedLlmClient([_persona_reply("não deveria rodar")])
    output = _store_comparison(*groups)

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == render_module.render_comparison(output)
    assert client.calls == []


def test_compare_reply_above_the_fallback_cutoff_with_no_remark_uses_the_table(deps):
    from julius.bot.turn import FALLBACK_LINE_MAX_GROUPS

    groups = tuple(
        _kind_group(f"tipo{i}", _store_entry("Assaí", "1", 1.0 + i), _store_entry("Dona de Casa", "2", 2.0 + i))
        for i in range(FALLBACK_LINE_MAX_GROUPS + 1)
    )
    client = ScriptedLlmClient([LlmResponse("", 0, 0, error="timeout")])
    output = _store_comparison(*groups)

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == render_module.render_comparison(output)


def test_compare_reply_with_no_groups_never_calls_the_persona(deps):
    client = ScriptedLlmClient([_persona_reply("não deveria rodar")])
    output = _store_comparison()

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == render_module.render_comparison(output)
    assert client.calls == []


from julius.bot.actions import ShoppingComparison  # noqa: E402
from julius.domain.models import ShoppingVerdict  # noqa: E402


def _shopping(comparison, verdict=None, unmatched=()) -> ShoppingComparison:
    return ShoppingComparison(comparison=comparison, verdict=verdict, unmatched_terms=unmatched)


def test_render_shopping_comparison_no_client_uses_fallback_line(deps):
    comparison = _store_comparison(_kind_group("tomate", _store_entry("Assaí", "1", 11.89), _store_entry("Dona de Casa", "2", 14.99)))
    verdict = ShoppingVerdict(1, ("Assaí",), ("tomate",), None, ())
    output = _shopping(comparison, verdict)

    reply = asyncio.run(_render_output(output, ChatState(), deps))

    assert reply.text == render_module.shopping_verdict_line(output)


def test_render_shopping_comparison_narrates_when_client_available(deps):
    comparison = _store_comparison(_kind_group("tomate", _store_entry("Assaí", "1", 11.89), _store_entry("Dona de Casa", "2", 14.99)))
    verdict = ShoppingVerdict(1, ("Assaí",), ("tomate",), None, ())
    output = _shopping(comparison, verdict)
    client = ScriptedLlmClient([_persona_reply("Vai no Assaí pro tomate.")])

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == "Vai no Assaí pro tomate."
    assert client.calls


def test_render_shopping_comparison_narration_fails_falls_back(deps):
    comparison = _store_comparison(_kind_group("tomate", _store_entry("Assaí", "1", 11.89), _store_entry("Dona de Casa", "2", 14.99)))
    verdict = ShoppingVerdict(1, ("Assaí",), ("tomate",), None, ())
    output = _shopping(comparison, verdict)
    client = ScriptedLlmClient([LlmResponse("", 0, 0, error="timeout")])

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == render_module.shopping_verdict_line(output)


def test_render_shopping_comparison_above_sanity_cap_skips_ai(deps):
    from julius.bot.turn import NARRATE_MAX_GROUPS

    groups = tuple(
        _kind_group(f"tipo{i}", _store_entry("Assaí", "1", 1.0 + i), _store_entry("Dona de Casa", "2", 2.0 + i))
        for i in range(NARRATE_MAX_GROUPS + 1)
    )
    comparison = _store_comparison(*groups)
    output = _shopping(comparison, ShoppingVerdict(len(groups), ("Assaí",), tuple(g.kind for g in groups), None, ()))
    client = ScriptedLlmClient([_persona_reply("não deveria rodar")])

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == render_module.shopping_verdict_line(output)
    assert client.calls == []


def test_render_shopping_comparison_empty_and_no_unmatched_skips_ai(deps):
    output = _shopping(_store_comparison())
    client = ScriptedLlmClient([_persona_reply("não deveria rodar")])

    reply = asyncio.run(_render_output(output, ChatState(), _with_client(deps, client)))

    assert reply.text == render_module.shopping_verdict_line(output)
    assert client.calls == []


def test_product_listing_gets_a_comment_but_keeps_the_table(deps):
    client = ScriptedLlmClient([_persona_reply("Catálogo respeitável, isso sim.")])
    products = (Product(id=1, canonical_name="Ovos"),)

    reply = asyncio.run(_render_output(ProductListing(products=products), ChatState(), _with_client(deps, client)))

    assert reply.text.startswith("Catálogo respeitável, isso sim.")
    assert "1 · Ovos" in reply.text


def test_store_listing_gets_a_comment_but_keeps_the_table(deps):
    client = ScriptedLlmClient([_persona_reply("Mercados suficientes pra pesquisar preço.")])
    stores = (Store(cnpj="11832478000285", legal_name="DONA DE CASA S/A", nickname="Dona de Casa"),)

    reply = asyncio.run(_render_output(StoreListing(stores=stores), ChatState(), _with_client(deps, client)))

    assert reply.text.startswith("Mercados suficientes pra pesquisar preço.")
    assert "Dona de Casa" in reply.text


def test_listing_without_a_client_is_unchanged(deps):
    products = (Product(id=1, canonical_name="Ovos"),)

    reply = asyncio.run(_render_output(ProductListing(products=products), ChatState(), deps))

    assert reply.text == render_module.render_products(products)


# --- the tap (ticket 160) ---------------------------------------------------------

from dataclasses import replace as _replace  # noqa: E402

from julius.bot import turn as turn_module  # noqa: E402
from julius.bot.actions import PendingWrite  # noqa: E402
from julius.bot.turn import PENDING_TTL_SECONDS, handle_tap  # noqa: E402


def _pending_rename(deps, state, name="Picanha bovina"):
    product = next(p for p in catalog.list_products(deps.conn) if "PICANHA" in p.canonical_name.upper())
    model, _ = _model(_action("rename_product", {"product": str(product.id), "name": name}))
    _turn(deps, model, state=state, text="renomeia")
    return product


def _snapshot(deps):
    return [catalog.get_product(deps.conn, p.id) for p in catalog.list_products(deps.conn)]


def test_tap_with_no_pending_is_inert(deps):
    before = _snapshot(deps)
    state = ChatState()

    reply = handle_tap(state, deps, "qualquer", approve=True)

    assert reply.text == "Essa confirmação não está mais ativa."
    assert _snapshot(deps) == before


def test_tap_with_wrong_nonce_keeps_the_pending(deps):
    state = ChatState()
    _pending_rename(deps, state)
    alive = state.pending

    reply = handle_tap(state, deps, "nonce-errado", approve=True)

    assert reply.text == "Essa confirmação não está mais ativa."
    assert state.pending is alive, "an old tap must not knock out a newer pending"


def test_tap_expired_clears_without_executing(deps):
    state = ChatState()
    product = _pending_rename(deps, state)
    before = _snapshot(deps)

    reply = handle_tap(state, deps, state.pending.nonce, approve=True, now=state.pending.created_at + 301)

    assert reply.text == "Confirmação expirada — nada foi executado."
    assert state.pending is None
    assert _snapshot(deps) == before
    assert catalog.get_product(deps.conn, product.id).canonical_name == product.canonical_name


def test_tap_at_exactly_the_ttl_is_still_valid(deps):
    state = ChatState()
    product = _pending_rename(deps, state)

    reply = handle_tap(
        state, deps, state.pending.nonce, approve=True, now=state.pending.created_at + PENDING_TTL_SECONDS
    )

    assert reply.text.startswith("✅")
    assert catalog.get_product(deps.conn, product.id).canonical_name == "Picanha bovina"


def test_tap_deny_clears_without_executing(deps):
    state = ChatState()
    _pending_rename(deps, state)
    before = _snapshot(deps)

    reply = handle_tap(state, deps, state.pending.nonce, approve=False)

    assert reply.text == "❌ Cancelado — nada foi executado."
    assert state.pending is None
    assert _snapshot(deps) == before


def test_tap_approve_executes_and_returns_undo(deps):
    state = ChatState()
    product = _pending_rename(deps, state)

    reply = handle_tap(state, deps, state.pending.nonce, approve=True)

    assert reply.text.startswith("✅")
    assert f"<code>julius produtos renomear {product.id}" in reply.text
    assert catalog.get_product(deps.conn, product.id).canonical_name == "Picanha bovina"
    assert state.pending is None


def test_tap_approve_write_failed_is_reported(deps):
    """A merge that would close a cycle: the service refuses, and the tap says why."""
    a = next(p for p in catalog.list_products(deps.conn) if "PICANHA" in p.canonical_name.upper())
    b = next(p for p in catalog.list_products(deps.conn) if p.id != a.id)
    catalog.merge_products(deps.conn, a.id, b.id)
    state = ChatState(pending=PendingWrite("merge_products", {"source_id": b.id, "target_id": a.id}, "p", "n", 0.0))
    before = _snapshot(deps)

    reply = handle_tap(state, deps, "n", approve=True, now=0.0)

    assert reply.text.startswith("❌ Não executado:")
    assert "já faz parte do grupo" in reply.text
    assert state.pending is None
    assert _snapshot(deps) == before


# --- comment on write confirmations (ticket 168) ----------------------------------


def test_pending_write_gets_a_comment_when_a_client_is_configured(deps):
    client = ScriptedLlmClient([_persona_reply("Já ajeitei essa categoria, era hora.")])
    product = next(p for p in catalog.list_products(deps.conn) if "PICANHA" in p.canonical_name.upper())
    model, _ = _model(_action("rename_product", {"product": str(product.id), "name": "Picanha bovina"}))

    reply, state = _turn(_with_client(deps, client), model, text="renomeia")

    assert reply.text.startswith("Já ajeitei essa categoria, era hora.")
    assert "⚠️" in reply.text and "Confirmar?" in reply.text
    assert reply.pending is not None
    assert client.calls, "the persona client should have been asked"


def test_pending_write_without_a_client_is_unchanged(deps):
    product = next(p for p in catalog.list_products(deps.conn) if "PICANHA" in p.canonical_name.upper())
    model, _ = _model(_action("rename_product", {"product": str(product.id), "name": "Picanha bovina"}))

    reply, _ = _turn(deps, model, text="renomeia")

    assert reply.text.startswith("⚠️")


def test_tap_approve_result_gets_a_comment_but_undo_stays_verbatim(deps):
    client = ScriptedLlmClient([_persona_reply("Bom, mais um preço acertado no radar.")])
    state = ChatState()
    product = _pending_rename(deps, state)
    deps_with_client = _with_client(deps, client)

    reply = handle_tap(state, deps_with_client, state.pending.nonce, approve=True)

    assert reply.text.startswith("Bom, mais um preço acertado no radar.")
    assert f"<code>julius produtos renomear {product.id}" in reply.text
    assert '"Picanha bovina"' not in reply.text.split("<code>")[0]  # comment never leaks into the undo line


def test_tap_write_failed_gets_a_comment_but_reason_stays_verbatim(deps):
    a = next(p for p in catalog.list_products(deps.conn) if "PICANHA" in p.canonical_name.upper())
    b = next(p for p in catalog.list_products(deps.conn) if p.id != a.id)
    catalog.merge_products(deps.conn, a.id, b.id)
    client = ScriptedLlmClient([_persona_reply("Isso não colou, e não é a primeira vez.")])
    deps_with_client = _with_client(deps, client)
    state = ChatState(pending=PendingWrite("merge_products", {"source_id": b.id, "target_id": a.id}, "p", "n", 0.0))

    reply = handle_tap(state, deps_with_client, "n", approve=True, now=0.0)

    assert reply.text.startswith("Isso não colou, e não é a primeira vez.")
    assert "já faz parte do grupo" in reply.text


def test_tap_deny_expired_and_stale_never_call_the_persona(deps):
    """The pending is built with the plain `deps` (no client), so narrate() is never a factor in
    setting it up -- only the tap's own three no-op paths are under test here."""
    client = ScriptedLlmClient([_persona_reply("não deveria rodar")])
    deps_with_client = _with_client(deps, client)

    state = ChatState()
    _pending_rename(deps, state)
    handle_tap(state, deps_with_client, "nonce-errado", approve=True)
    assert client.calls == []

    state = ChatState()
    _pending_rename(deps, state)
    handle_tap(state, deps_with_client, state.pending.nonce, approve=False)
    assert client.calls == []

    state = ChatState()
    _pending_rename(deps, state)
    handle_tap(state, deps_with_client, state.pending.nonce, approve=True, now=state.pending.created_at + 301)
    assert client.calls == []


def test_tap_approve_unexpected_error_clears_pending(deps, monkeypatch):
    state = ChatState()
    _pending_rename(deps, state)
    monkeypatch.setattr(turn_module, "execute", lambda deps, pending: 1 / 0)

    reply = handle_tap(state, deps, state.pending.nonce, approve=True)

    assert reply.text == "❌ Não executado: erro inesperado; nada foi executado"
    assert state.pending is None, "a pending left behind would wedge the chat forever"


def test_text_after_expired_pending_has_no_cancel_notice(deps):
    state = ChatState()
    _pending_rename(deps, state)
    state.pending = _replace(state.pending, created_at=state.pending.created_at - PENDING_TTL_SECONDS - 1)
    model, _ = _model(_prose("beleza"))

    reply, _ = _turn(deps, model, state=state, text="outra coisa")

    assert "Ação anterior cancelada." not in reply.text
    assert reply.text == "beleza"
    assert state.pending is None


def test_text_while_a_live_pending_exists_still_warns(deps):
    """The counterpart of the test above: a pending the user could still see gets a notice."""
    state = ChatState()
    _pending_rename(deps, state)
    model, _ = _model(_prose("beleza"))

    reply, _ = _turn(deps, model, state=state, text="outra coisa")

    assert reply.text.startswith("Ação anterior cancelada.")
