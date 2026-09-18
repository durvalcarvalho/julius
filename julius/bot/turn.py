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

from julius.bot.actions import Deps, PendingWrite, ProductListing, StoreListing, WriteFailed, execute
from julius.bot.agent import BOT_PROMPT_VERSION, BotAgent
from julius.bot.render import (
    escape,
    render_comparison,
    render_failure,
    render_pending,
    render_products,
    render_records,
    render_result,
    render_stores,
)
from julius.config import Config
from julius.domain.models import SearchOutcome, StoreComparison
from julius.infra import ai_log
from julius.services import suggestions

HISTORY_TURNS = 3
# 300, not 120: the majordomo measured a real tap arriving at 121 s and being dropped.
PENDING_TTL_SECONDS = 300.0

CALL_KIND = "bot_turn"

CANCELLED_NOTICE = "Ação anterior cancelada.\n\n"
AI_UNREACHABLE = "Não consegui falar com a IA agora. Tente de novo em instantes."
STALE_TAP = "Essa confirmação não está mais ativa."
EXPIRED_TAP = "Confirmação expirada — nada foi executado."
DENIED_TAP = "❌ Cancelado — nada foi executado."


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
        # An expired one goes in silence: the user was never told it was still waiting.
        if not _expired(state.pending, time.monotonic()):
            prefix = CANCELLED_NOTICE
        state.pending = None

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


def _expired(pending: PendingWrite, now: float) -> bool:
    return now - pending.created_at > PENDING_TTL_SECONDS


def handle_tap(state: ChatState, deps: Deps, nonce: str, approve: bool, *, now: float | None = None) -> Reply:
    """The second pass of a write. No model here: approved runs execute() in code, and every other
    branch writes nothing.

    `now` is injectable for the same reason `relative_age` takes `today` -- a test of expiry must
    not sleep."""
    pending = state.pending
    if pending is None or pending.nonce != nonce:
        # Deliberately does not clear: an old tap must not knock out a newer pending.
        return Reply(STALE_TAP)
    try:
        if _expired(pending, time.monotonic() if now is None else now):
            return Reply(EXPIRED_TAP)
        if not approve:
            return Reply(DENIED_TAP)
        try:
            return Reply(render_result(execute(deps, pending)))
        except WriteFailed as error:
            return Reply(render_failure(str(error)))
        except Exception:
            # Services write inside `with conn:`, so an exception mid-way already rolled back.
            return Reply(render_failure("erro inesperado; nada foi executado"))
    finally:
        # Written before the branches, not after: a pending left behind wedges the chat forever.
        state.pending = None
