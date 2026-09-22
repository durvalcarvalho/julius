import logging
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from conftest import copied_fixtures
from julius.bot.actions import ALL_ACTIONS, Deps, PendingWrite, StoreListing
from julius.bot.agent import (
    BOT_PROMPT_VERSION,
    MAX_OUTPUT_TOKENS,
    ROUTING_TEMPERATURE,
    SYSTEM_PROMPT,
    build_agent,
    build_model,
)
from julius.bot.render import WRITE_REFUSED_LINE
from julius.config import Config
from julius.parsers.df import DFReceiptParser
from julius.repositories.products import resolve_product_id
from julius.repositories.stores import ensure_store
from julius.services import catalog, importing


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
def deps(conn, cfg, tmp_path) -> Deps:
    fixtures = copied_fixtures(tmp_path)
    importing.import_receipt(conn, fixtures / "qrcode.html", DFReceiptParser())
    return Deps(conn=conn, config=cfg)


def _scripted(*responses):
    """A model that replays the given responses in order, counting how many times it was asked."""
    state = {"calls": 0, "info": None, "messages": None}

    def model(messages, info):
        state["info"] = info
        state["messages"] = messages
        index = min(state["calls"], len(responses) - 1)
        state["calls"] += 1
        return responses[index]

    return FunctionModel(model), state


def test_agent_exposes_exactly_the_actions_as_output_tools(cfg, deps):
    """The menu is closed: nothing registered by @agent.tool, and nothing missing.

    PydanticAI prefixes an output function with `final_result_`, so the names are compared after
    stripping it -- and the prefix itself is asserted, because a library that dropped it would
    make every other bot test call an unknown tool and still finish the run."""
    model, state = _scripted(ModelResponse(parts=[TextPart("oi")]))

    build_agent(cfg, model=model).run_sync("oi", deps=deps)

    names = {tool.name for tool in state["info"].output_tools}
    assert all(name.startswith("final_result_") for name in names)
    assert {name.removeprefix("final_result_") for name in names} == {a.__name__ for a in ALL_ACTIONS}
    assert len(names) == 15
    assert state["info"].function_tools == []


def test_text_output_when_no_action_fits(cfg, deps):
    model, _ = _scripted(ModelResponse(parts=[TextPart("Oi!")]))

    result = build_agent(cfg, model=model).run_sync("bom dia", deps=deps)

    assert result.output == "Oi!"


def test_output_function_ends_the_run_without_a_second_model_call(cfg, deps):
    model, state = _scripted(
        ModelResponse(parts=[ToolCallPart("final_result_list_stores", {})]),
        ModelResponse(parts=[TextPart("não deveria ser chamado")]),
    )

    result = build_agent(cfg, model=model).run_sync("quais mercados?", deps=deps)

    assert isinstance(result.output, StoreListing)
    assert state["calls"] == 1


def test_retry_reaches_the_model_and_a_second_call_happens(cfg, deps):
    model, state = _scripted(
        ModelResponse(parts=[ToolCallPart("final_result_rename_product", {"product": "99999", "name": "X"})]),
        ModelResponse(parts=[TextPart("Não achei esse produto. Qual é o nome dele?")]),
    )

    result = build_agent(cfg, model=model).run_sync("renomeia o 99999", deps=deps)

    retries = [
        part.content
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if isinstance(part, RetryPromptPart)
    ]
    assert state["calls"] == 2
    assert isinstance(result.output, str)
    assert any("Não existe produto com id 99999" in content for content in retries)


def test_ambiguous_kind_exhausts_retries_when_the_model_keeps_guessing(cfg, deps):
    """Same shape as test_output_guard_exhausts_retries_when_the_model_insists, for the NEW
    ModelRetry `_resolve_kind` raises on brand ambiguity (docs/design/kind-resolution-in-routing.md,
    Decisão 3) -- the `retries=2` budget it spends is shared with the output-honesty guard, and a
    model that keeps calling check_price with the same ambiguous item instead of asking the person
    must exhaust it the same way, ending in `UnexpectedModelBehavior` rather than ever returning a
    guessed `kind`."""
    ensure_store(deps.conn, "00000000000099", "Synthetic store")
    soda = resolve_product_id(deps.conn, "00000000000099", "s1", "PEPSI REFRIGERANTE PET 2L")
    snack = resolve_product_id(deps.conn, "00000000000099", "s2", "PEPSICO SNACK BATATA 100G")
    catalog.set_product_kind(deps.conn, soda, "refrigerante")
    catalog.set_product_kind(deps.conn, snack, "salgadinho")
    model, state = _scripted(ModelResponse(parts=[ToolCallPart("final_result_check_price", {"item": "pepsi", "price": 10.0})]))

    with pytest.raises(UnexpectedModelBehavior):
        build_agent(cfg, model=model).run_sync("a pepsi tá 10 reais, tá bom?", deps=deps)

    assert state["calls"] >= 2


def test_build_model_uses_the_configured_endpoint(cfg):
    model = build_model(cfg)

    assert model.model_name == "cheap-1"
    assert str(model.client.base_url).startswith("https://api.example/v1")


@pytest.mark.parametrize("missing", ["ai_api_key", "ai_base_url", "ai_model"])
def test_build_model_requires_ai_config(cfg, missing):
    with pytest.raises(ValueError, match="JULIUS_AI_API_KEY"):
        build_model(replace(cfg, **{missing: None}))


def test_model_settings_carry_request_extras(cfg):
    extras = {"thinking": {"type": "disabled"}}

    with_extras = build_agent(replace(cfg, ai_request_extras=extras), model=_scripted()[0])
    without = build_agent(cfg, model=_scripted()[0])

    assert with_extras.model_settings["extra_body"] == extras
    assert "extra_body" not in without.model_settings
    assert with_extras.model_settings["max_tokens"] == without.model_settings["max_tokens"] == MAX_OUTPUT_TOKENS


def test_model_settings_use_zero_temperature_for_routing(cfg):
    """docs/design/agent-output-honesty.md, Decisão 3: escolher 1 de 15 ações é "multiple
    choice" -- sem isto, o provider usa o próprio default (tipicamente 1.0)."""
    extras = {"thinking": {"type": "disabled"}}

    with_extras = build_agent(replace(cfg, ai_request_extras=extras), model=_scripted()[0])
    without = build_agent(cfg, model=_scripted()[0])

    assert with_extras.model_settings["temperature"] == ROUTING_TEMPERATURE
    assert without.model_settings["temperature"] == ROUTING_TEMPERATURE == 0.0


def test_output_guard_retries_once_when_text_claims_unchecked_data(cfg, deps):
    """docs/design/agent-output-honesty.md, Decisão 1: reproduz o incidente real (o bot afirmou
    "as buscas voltaram vazias... histórico de cupons ainda não foi importado" sem ter chamado
    nenhuma ação) e confirma que a guarda força uma segunda tentativa antes de aceitar a saída."""
    model, state = _scripted(
        ModelResponse(
            parts=[
                TextPart(
                    "Não consegui ver os resultados — as buscas voltaram vazias, sem nenhum "
                    "dado de preço. Isso costuma acontecer quando o histórico de cupons ainda "
                    "não foi importado (ou a importação falhou)."
                )
            ]
        ),
        ModelResponse(parts=[ToolCallPart("final_result_list_stores", {})]),
    )

    result = build_agent(cfg, model=model).run_sync("qual mercado é mais barato pra tomate e cebola?", deps=deps)

    assert state["calls"] == 2
    assert isinstance(result.output, StoreListing)


def test_output_guard_exhausts_retries_when_the_model_insists(cfg, deps):
    model, state = _scripted(
        ModelResponse(parts=[TextPart("As buscas voltaram vazias, sem nenhum resultado no banco de dados.")])
    )

    with pytest.raises(UnexpectedModelBehavior):
        build_agent(cfg, model=model).run_sync("qual mercado é mais barato?", deps=deps)

    # >= 2, não um número exato: a contagem certa é contabilidade interna do pydantic_ai
    # (build_agent's retries=2), não uma decisão deste código -- travar no valor exato quebraria
    # num upgrade de biblioteca sem nenhuma mudança de comportamento real.
    assert state["calls"] >= 2


def test_output_guard_stands_down_after_a_real_action_ran_this_turn(cfg, deps):
    """Achado de revisão: o próprio SYSTEM_PROMPT manda relatar em texto uma recusa de
    resolve_product ("Nenhum produto chamado «X»") -- essa fala é legítima porque uma ação
    REALMENTE rodou, mesmo que a frase final mencione "banco de dados". A guarda não pode barrar
    isso, ou uma resposta correta vira uma queda "não consegui confirmar" à toa."""
    model, state = _scripted(
        ModelResponse(parts=[ToolCallPart("final_result_rename_product", {"product": "99999", "name": "X"})]),
        ModelResponse(parts=[TextPart("Não achei esse produto no banco de dados. Qual é o nome dele?")]),
    )

    result = build_agent(cfg, model=model).run_sync("renomeia o 99999", deps=deps)

    assert state["calls"] == 2  # 1 chamada de ação + 1 resposta em texto -- a guarda não consumiu um 3º
    assert result.output == "Não achei esse produto no banco de dados. Qual é o nome dele?"


def test_output_guard_does_not_touch_action_outputs(cfg, deps):
    """A guarda roda sobre toda saída, de qualquer tipo do BotOutput -- confirma que ela nunca
    barra uma ação de verdade, só texto livre com as frases proibidas."""
    model, state = _scripted(ModelResponse(parts=[ToolCallPart("final_result_list_stores", {})]))

    result = build_agent(cfg, model=model).run_sync("quais mercados?", deps=deps)

    assert isinstance(result.output, StoreListing)
    assert state["calls"] == 1


def test_write_action_is_refused_for_a_read_only_chat(cfg, deps):
    """docs/design/bot-read-only-tier.md: a troca de tipo acontece sobre a resposta que já
    chegou -- uma chamada de modelo só, nunca um retry (diferente da guarda de honestidade)."""
    model, state = _scripted(
        ModelResponse(parts=[ToolCallPart("final_result_rename_product", {"product": "picanha", "name": "Picanha bovina"})])
    )
    read_only = replace(deps, can_write=False, chat_id=999)

    result = build_agent(cfg, model=model).run_sync("renomeia a picanha pra Picanha bovina", deps=read_only)

    assert result.output == WRITE_REFUSED_LINE
    assert state["calls"] == 1


def test_write_action_still_works_for_a_trusted_chat(cfg, deps):
    """`deps` (a fixture) nasce com can_write=True por default -- o caminho "dono" de sempre."""
    model, state = _scripted(
        ModelResponse(parts=[ToolCallPart("final_result_rename_product", {"product": "picanha", "name": "Picanha bovina"})])
    )

    result = build_agent(cfg, model=model).run_sync("renomeia a picanha pra Picanha bovina", deps=deps)

    assert isinstance(result.output, PendingWrite)
    assert state["calls"] == 1


def test_read_action_is_never_touched_by_the_write_guard(cfg, deps):
    model, state = _scripted(ModelResponse(parts=[ToolCallPart("final_result_list_stores", {})]))
    read_only = replace(deps, can_write=False, chat_id=999)

    result = build_agent(cfg, model=model).run_sync("quais mercados?", deps=read_only)

    assert isinstance(result.output, StoreListing)
    assert state["calls"] == 1


def test_blocked_write_attempt_is_logged_with_chat_id_and_action(cfg, deps, caplog):
    model, _ = _scripted(
        ModelResponse(parts=[ToolCallPart("final_result_rename_product", {"product": "picanha", "name": "Picanha bovina"})])
    )
    read_only = replace(deps, can_write=False, chat_id=999)

    with caplog.at_level(logging.INFO, logger="julius.bot"):
        build_agent(cfg, model=model).run_sync("renomeia a picanha pra Picanha bovina", deps=read_only)

    assert any(
        "chat_id=999" in record.getMessage() and "rename_product" in record.getMessage()
        for record in caplog.records
    )


def test_the_prompt_reaches_the_model(cfg, deps):
    """`deps`'s catalogue (one imported receipt, no `kind` set on anything yet) makes the dynamic
    `kind_vocabulary` system prompt come back empty -- still its own part (`dynamic=True` runners
    always contribute one, per `pydantic_ai._system_prompt.resolve_system_prompts`), not folded
    into `SYSTEM_PROMPT` itself."""
    model, state = _scripted(ModelResponse(parts=[TextPart("oi")]))

    build_agent(cfg, model=model).run_sync("oi", deps=deps)

    system = [part.content for part in state["messages"][0].parts if getattr(part, "part_kind", "") == "system-prompt"]
    assert system == [SYSTEM_PROMPT, ""]


def test_kind_vocabulary_lists_registered_kinds(cfg, deps):
    product = catalog.list_products(deps.conn)[0]
    catalog.set_product_kind(deps.conn, product.id, "tomate")
    model, state = _scripted(ModelResponse(parts=[TextPart("oi")]))

    build_agent(cfg, model=model).run_sync("oi", deps=deps)

    system = [part.content for part in state["messages"][0].parts if getattr(part, "part_kind", "") == "system-prompt"]
    assert "tomate" in system[1]
    assert "check_price/compare_stores" in system[1]


def test_kind_vocabulary_stays_current_across_turns_sharing_history(cfg, deps):
    """`dynamic=True` is what makes this work (docs/design/kind-resolution-in-routing.md, Decisão
    1): `bot/turn.py::handle_text` always reuses `message_history`, so a system-prompt function
    evaluated only once (the default, `dynamic=False`) would freeze the vocabulary at whatever the
    catalogue looked like on the chat's first turn -- a `kind` registered afterwards by a separate
    `julius produtos revisar` run would never reach a conversation already in progress."""
    model, state = _scripted(ModelResponse(parts=[TextPart("primeiro")]), ModelResponse(parts=[TextPart("segundo")]))
    agent = build_agent(cfg, model=model)

    first = agent.run_sync("oi", deps=deps)
    product = catalog.list_products(deps.conn)[0]
    catalog.set_product_kind(deps.conn, product.id, "tomate")
    agent.run_sync("de novo", deps=deps, message_history=first.new_messages())

    system = [part.content for part in state["messages"][0].parts if getattr(part, "part_kind", "") == "system-prompt"]
    assert "tomate" in system[1], "the second run must see the kind registered after the first"


@pytest.mark.parametrize(
    "required",
    [
        "exatamente uma",
        "id",
        "confirmar",
        "nunca afirme",
        "search_prices",
        "compare_stores",
        "caro",
        "busca voltou vazia",
        "quantity_needed",
    ],
)
def test_system_prompt_states_the_rules_it_has_to_state(required):
    assert required in SYSTEM_PROMPT.lower()


def test_prompt_is_versioned_and_stays_out_of_the_curation_versions():
    from julius.services import suggestions

    assert BOT_PROMPT_VERSION == "4"
    assert "bot_turn" not in suggestions.PROMPT_VERSIONS


def test_build_agent_touches_no_disk_and_no_network(tmp_path):
    """It takes a Config; it must not read the environment or open the database to build itself."""
    cfg = Config(
        db_path=tmp_path / "never-created.db",
        ai_api_key="k",
        ai_base_url="https://api.example/v1",
        ai_model="m",
        ai_budget_usd=1.0,
        ai_input_price_usd_per_1m=1.0,
        ai_output_price_usd_per_1m=1.0,
    )

    build_agent(cfg)

    assert not (tmp_path / "never-created.db").exists()
    assert list(tmp_path.iterdir()) == []
