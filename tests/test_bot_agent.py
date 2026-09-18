from dataclasses import replace
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from conftest import copied_fixtures
from julius.bot.actions import ALL_ACTIONS, Deps, StoreListing
from julius.bot.agent import BOT_PROMPT_VERSION, MAX_OUTPUT_TOKENS, SYSTEM_PROMPT, build_agent, build_model
from julius.config import Config
from julius.parsers.df import DFReceiptParser
from julius.services import importing


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
    assert len(names) == 14
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


def test_the_prompt_reaches_the_model(cfg, deps):
    model, state = _scripted(ModelResponse(parts=[TextPart("oi")]))

    build_agent(cfg, model=model).run_sync("oi", deps=deps)

    system = [part.content for part in state["messages"][0].parts if getattr(part, "part_kind", "") == "system-prompt"]
    assert system == [SYSTEM_PROMPT]


@pytest.mark.parametrize(
    "required",
    ["exatamente uma", "id", "confirmar", "nunca afirme", "search_prices", "compare_stores", "caro"],
)
def test_system_prompt_states_the_rules_it_has_to_state(required):
    assert required in SYSTEM_PROMPT.lower()


def test_prompt_is_versioned_and_stays_out_of_the_curation_versions():
    from julius.services import suggestions

    assert BOT_PROMPT_VERSION == "1"
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
