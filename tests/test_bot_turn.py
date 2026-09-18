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
