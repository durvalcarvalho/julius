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
    comparison_facts,
    compare_fallback_line,
    escape,
    products_facts,
    records_facts,
    render_comparison,
    render_failure,
    render_pending,
    render_products,
    render_records,
    render_result,
    render_stores,
    search_fallback_line,
    stores_facts,
)
from julius.config import Config
from julius.domain.models import SearchOutcome, StoreComparison
from julius.infra import ai_log
from julius.services import suggestions

HISTORY_TURNS = 3
# 300, not 120: the majordomo measured a real tap arriving at 121 s and being dropped.
PENDING_TTL_SECONDS = 300.0

# Medido contra o banco real em 18/09/2026 (105 produtos, 132 preços, 5 mercados): 6 cobre 69 das
# 72 buscas possíveis (96%), e o único `mercados comparar` real do catálogo tem exatamente 6 grupos.
# Desde o design `bot-message-chunking.md` (v2.8), a narração é sempre tentada -- não é mais um
# corte Modo A/Modo B. O que este número decide agora é só o fallback SEM remark (IA não
# configurada, orçamento estourado, ou a chamada falhou): `search_fallback_line` supõe implicitamente
# um produto só (cita `records[0].canonical_name`), então só é seguro reaproveitá-lo dentro do corte
# onde isso foi medido; acima dele o fallback volta a ser a tabela crua, nunca a frase.
FALLBACK_LINE_MAX_RECORDS = 6
FALLBACK_LINE_MAX_GROUPS = 6

# Teto de sanidade: acima disto a chamada de IA nem é tentada, direto pra tabela crua -- protege
# contra um `consultar` de catálogo grande virar um prompt de centenas de linhas por acidente (o
# `max_tokens=260` já truncou uma vez com só 6 grupos, ticket 172). Não é número medido contra o
# catálogo real (nenhum caso real chega perto ainda) -- placeholder generoso, a recalibrar quando
# o catálogo crescer o suficiente para importar. Ver "O que fica para medir" em
# docs/design/bot-message-chunking.md.
NARRATE_MAX_RECORDS = 40
NARRATE_MAX_GROUPS = 20

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


async def _narrate(deps: Deps, context: str, facts: str) -> str | None:
    """The one seam between the turn and the persona (ticket 163's `narrate`). No client, or no
    facts, means no call at all -- the exact same "answer without it" behaviour as IA not being
    configured.

    Called directly, not through `asyncio.to_thread`: `deps.conn` is a `sqlite3.Connection`, which
    refuses to be touched from a thread other than the one that opened it (`check_same_thread`,
    on by default) -- a worker thread would raise, `narrate`'s own `except Exception` would
    swallow it, and every call would silently look like "the model said nothing". `async def` is
    kept only so every call site can `await` it uniformly; it never actually yields, same as
    `handle_tap` (ticket 168) calling `narrate` with no threading at all. This bot already
    processes updates sequentially by design (see `docs/design/telegram-bot.md`), so blocking
    briefly here costs nothing this project doesn't already accept elsewhere."""
    if deps.client is None or not facts:
        return None
    return suggestions.narrate(deps.conn, deps.config, deps.client, context, facts)


async def _render_output(output: object, state: ChatState, deps: Deps) -> Reply:
    if isinstance(output, PendingWrite):
        state.pending = output
        base = render_pending(output)
        remark = await _narrate(deps, "confirmação de uma alteração no catálogo", output.preview)
        return Reply(f"{escape(remark)}\n\n{base}" if remark else base, pending=output)
    if isinstance(output, SearchOutcome):
        _log_query(deps.config, output)
        records = output.records
        base = render_records(records)
        # No client is exactly "IA not configured": the reply must be byte-for-byte what it was
        # before this ticket, never the Julius-toned fallback line (that line is for when a
        # configured client tried and failed, not for "there is no client to try").
        if not records or deps.client is None:
            return Reply(base)
        if len(records) > NARRATE_MAX_RECORDS:
            return Reply(base)
        remark = await _narrate(deps, "histórico de preço de um produto", records_facts(records))
        if remark:
            return Reply(escape(remark))
        if len(records) <= FALLBACK_LINE_MAX_RECORDS:
            return Reply(search_fallback_line(records))
        return Reply(base)
    if isinstance(output, StoreComparison):
        base = render_comparison(output)
        groups = output.comparisons
        if not groups or deps.client is None:
            return Reply(base)
        if len(groups) > NARRATE_MAX_GROUPS:
            return Reply(base)
        remark = await _narrate(deps, "comparação de preço entre mercados", comparison_facts(output))
        if remark:
            return Reply(escape(remark))
        if len(groups) <= FALLBACK_LINE_MAX_GROUPS:
            return Reply(compare_fallback_line(output))
        return Reply(base)
    if isinstance(output, ProductListing):
        base = render_products(output.products)
        remark = await _narrate(deps, "catálogo de produtos", products_facts(output.products))
        return Reply(f"{escape(remark)}\n\n{base}" if remark else base)
    if isinstance(output, StoreListing):
        base = render_stores(output.stores)
        remark = await _narrate(deps, "catálogo de mercados", stores_facts(output.stores))
        return Reply(f"{escape(remark)}\n\n{base}" if remark else base)
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

    reply = await _render_output(result.output, state, deps)
    return Reply(f"{prefix}{reply.text}", pending=reply.pending) if prefix else reply


def _expired(pending: PendingWrite, now: float) -> bool:
    return now - pending.created_at > PENDING_TTL_SECONDS


def _tap_comment(deps: Deps, facts: str) -> str | None:
    """Same guard as `_narrate`, synchronous because `handle_tap` is not a coroutine (there is no
    event loop here to `await` into -- `app.py::on_tap` calls it directly). Called *after*
    `execute`/`WriteFailed` resolve, never before: narrating a result that might still fail would
    contradict the "never affirm a write already happened" rule the persona prompt carries."""
    if deps.client is None or not facts:
        return None
    return suggestions.narrate(deps.conn, deps.config, deps.client, "confirmação de uma alteração no catálogo", facts)


def handle_tap(state: ChatState, deps: Deps, nonce: str, approve: bool, *, now: float | None = None) -> Reply:
    """The second pass of a write: approved runs execute() in code, every other branch writes
    nothing. The model is never asked to decide anything here -- at most it comments, after the
    fact, on a result the code already produced.

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
            result = execute(deps, pending)
        except WriteFailed as error:
            reason = str(error)
            comment = _tap_comment(deps, reason)
            base = render_failure(reason)
            return Reply(f"{escape(comment)}\n\n{base}" if comment else base)
        except Exception:
            # Services write inside `with conn:`, so an exception mid-way already rolled back.
            return Reply(render_failure("erro inesperado; nada foi executado"))
        comment = _tap_comment(deps, result.summary)
        base = render_result(result)
        return Reply(f"{escape(comment)}\n\n{base}" if comment else base)
    finally:
        # Written before the branches, not after: a pending left behind wedges the chat forever.
        state.pending = None
