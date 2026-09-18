"""One message in, one reply out. Everything Telegram-shaped stays in app.py, so this whole file
is exercised by tests without a bot token.

The principle it encodes: the model routes, the code answers. Model prose reaches the user only
when no action was chosen -- every other reply is rendered from what an action actually returned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic_ai.messages import ModelMessage

from julius.bot.actions import Deps, PendingWrite, ProductListing, StoreListing
from julius.bot.agent import BOT_PROMPT_VERSION, BotAgent
from julius.bot.render import (
    escape,
    render_comparison,
    render_pending,
    render_products,
    render_records,
    render_stores,
)
from julius.config import Config
from julius.domain.models import SearchOutcome, StoreComparison
from julius.infra import ai_log
from julius.services import suggestions

HISTORY_TURNS = 3

CALL_KIND = "bot_turn"

CANCELLED_NOTICE = "Ação anterior cancelada.\n\n"
AI_UNREACHABLE = "Não consegui falar com a IA agora. Tente de novo em instantes."


@dataclass
class ChatState:
    """One chat's short memory. Whole turns, never loose messages: cutting inside a turn leaves a
    tool call without its return, and the API refuses the history."""

    runs: list[list[ModelMessage]] = field(default_factory=list)
    pending: PendingWrite | None = None

    @property
    def history(self) -> list[ModelMessage]:
        return [message for run in self.runs for message in run]


@dataclass(frozen=True)
class Reply:
    text: str
    pending: PendingWrite | None = None


def _output_kind(output: object) -> str:
    if isinstance(output, PendingWrite):
        return f"PendingWrite:{output.action}"
    return "text" if isinstance(output, str) else type(output).__name__


def _log_query(config: Config, outcome: SearchOutcome) -> None:
    """Same keys as `julius consultar`, plus the channel -- whoever recalibrates the cutoffs with
    this file has to be able to tell the two apart. `words` is what the model extracted, not what
    the user typed."""
    ai_log.append(
        config.query_log_path,
        {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "words": outcome.term.split() if outcome.term else [],
            "tag_explicit": None,
            "detected_tag": outcome.detected_tag,
            "term_used": outcome.term,
            "tag_used": outcome.tag,
            "result_count": len(outcome.records),
            "ai_fallback": False,
            "channel": "bot",
        },
    )


def _charge(deps: Deps, text: str, *, attempt: int, kind: str | None, latency_ms: int, error: str | None) -> None:
    suggestions.record_usage(
        deps.conn,
        deps.config,
        CALL_KIND,
        attempt=attempt,
        user_prompt=text,
        raw_response=kind,
        parsed_ok=error is None,
        input_tokens=0,
        output_tokens=0,
        latency_ms=latency_ms,
        error=error,
        prompt_version=BOT_PROMPT_VERSION,
    )


def _render_output(output: object, state: ChatState, deps: Deps) -> Reply:
    if isinstance(output, PendingWrite):
        state.pending = output
        return Reply(render_pending(output), pending=output)
    if isinstance(output, SearchOutcome):
        _log_query(deps.config, output)
        return Reply(render_records(output.records))
    if isinstance(output, StoreComparison):
        return Reply(render_comparison(output))
    if isinstance(output, ProductListing):
        return Reply(render_products(output.products))
    if isinstance(output, StoreListing):
        return Reply(render_stores(output.stores))
    # The only path where the model's own words reach the user.
    return Reply(escape(str(output)))


async def handle_text(agent: BotAgent, state: ChatState, deps: Deps, text: str) -> Reply:
    """Never raises: every failure becomes a Reply and a line in ai_calls.jsonl."""
    prefix = ""
    if state.pending is not None:
        state.pending = None
        prefix = CANCELLED_NOTICE

    if not suggestions.is_available(deps.conn, deps.config):
        _charge(deps, text, attempt=0, kind=None, latency_ms=0, error="budget_exhausted")
        spent = suggestions.spent_this_month(deps.conn)
        return Reply(
            f"{prefix}Orçamento de IA do mês esgotado (US$ {spent:.2f} de "
            f"US$ {deps.config.ai_budget_usd:.2f}). O bot volta no mês que vem; a CLI continua "
            "funcionando."
        )

    started = time.monotonic()
    try:
        result = await agent.run(text, deps=deps, message_history=state.history)
    except Exception as error:
        _charge(
            deps,
            text,
            attempt=1,
            kind=None,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"agent raised {type(error).__name__}",
        )
        return Reply(f"{prefix}{AI_UNREACHABLE}")
    latency_ms = int((time.monotonic() - started) * 1000)

    usage = result.usage
    suggestions.record_usage(
        deps.conn,
        deps.config,
        CALL_KIND,
        attempt=1,
        user_prompt=text,
        raw_response=_output_kind(result.output),
        parsed_ok=True,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=latency_ms,
        error=None,
        prompt_version=BOT_PROMPT_VERSION,
    )

    state.runs.append(result.new_messages())
    del state.runs[:-HISTORY_TURNS]

    reply = _render_output(result.output, state, deps)
    return Reply(f"{prefix}{reply.text}", pending=reply.pending) if prefix else reply
