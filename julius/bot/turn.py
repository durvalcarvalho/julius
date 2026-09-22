"""One message in, one reply out. Everything Telegram-shaped stays in app.py, so this whole file
is exercised by tests without a bot token.

The principle it encodes: the model routes, the code answers. Model prose reaches the user only
when no action was chosen -- every other reply is rendered from what an action actually returned.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ToolCallPart

from julius.bot.actions import Deps, PendingWrite, ProductListing, ShoppingComparison, StoreListing, WriteFailed, execute
from julius.bot.agent import BOT_PROMPT_VERSION, BotAgent
from julius.bot.render import (
    comparison_facts,
    compare_fallback_line,
    escape,
    no_match_facts,
    no_match_fallback_line,
    price_check_facts,
    price_check_fallback_line,
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
    shopping_comparison_facts,
    shopping_verdict_line,
    stores_facts,
)
from julius.config import Config
from julius.domain.models import PriceCheck, PriceRecord, SearchOutcome, StoreComparison
from julius.infra import ai_log
from julius.services import search as search_service
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

# Brainstorm 2026-09-20: "quanto tá o kg de alcatra" with nothing in the catalog used to answer
# "Nenhum resultado." and stop -- the least useful reply a solicitous market clerk could give.
# 3, not more: the same wall-of-text problem NARRATE_MAX_* already guards against, at a much
# smaller scale here since this is a curated "here's what I do have" list, not a raw dump.
ALT_LIMIT = 3

CALL_KIND = "bot_turn"

CANCELLED_NOTICE = "Ação anterior cancelada.\n\n"
AI_UNREACHABLE = "Não consegui falar com a IA agora. Tente de novo em instantes."
COULD_NOT_CONFIRM = "Não consegui confirmar isso com segurança — tenta perguntar de novo, mais direto?"
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


def _tool_note(result) -> str | None:
    """The `note` argument of whichever action call produced `result.output`, if the model gave
    one -- real gap (monkey test, 2026-09-22): "quanto paguei de tomate e qual mercado é mais
    barato pra cebola?" only ever answered tomato; the SYSTEM_PROMPT's own promise ("diga, em
    texto, que a segunda vem na próxima mensagem") is structurally impossible to keep once the
    first part becomes an action call -- choosing an action ends the run with ITS return value as
    the output, and pydantic_ai's output_type is `str` OR one action, never free text alongside a
    tool call in the same turn. `note` is a normal string parameter every read action now accepts
    (bot/actions.py), so the model can say "cebola eu comparo a seguir" as part of the SAME call
    instead of a separate text turn that can't coexist with it -- read back here, from the tool
    call's own arguments, and appended by the caller after whatever `_render_output` produces.
    Scans backwards because a retried call (`ModelRetry`) leaves earlier `ToolCallPart`s behind;
    only the last one is the call that actually produced `result.output`."""
    for message in reversed(result.new_messages()):
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolCallPart):
                note = part.args_as_dict().get("note")
                return note.strip() if isinstance(note, str) and note.strip() else None
    return None


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


def _search_narration_context(records: Sequence[PriceRecord]) -> str:
    """Real bug found by monkey test (2026-09-22): a search for a generic word like "leite" hits
    4 different products (two creme de leite, a leite UHT, a leite condensado) -- narrated with the
    old fixed context "histórico de preço de um produto" (singular), the persona reliably (temp=0,
    reproduced twice) attributed the whole count to just the first product's name ("4 compras
    registradas de Creme de leite Itambé"), even though `records_facts` lists all four correctly.
    The context label is what told it "this is one product's history"; it wasn't. Telling it
    accurately when the search actually spans more than one product removes the false premise."""
    if len({record.product_id for record in records}) <= 1:
        return "histórico de preço de um produto"
    return "histórico de preço de vários produtos diferentes que bateram na mesma busca"


_PRICE_CHECK_NO_DATA_PHRASES = (
    "ainda não tenho",
    "não tenho registrado",
    "não tenho preço",
    "sem preço antigo",
    "não conheço esse item",
    "não tenho como comparar",
)
"""Real bug (monkey test, 2026-09-22), one occurrence, not reproduced in 2 follow-up isolated
retries: the persona said "esse tipo eu ainda não tenho registrado... me traz o valor e o mercado
que eu anoto" for a `PriceCheck` that HAD a resolved verdict and reference price (reason=None) --
the deterministic fallback for the same facts says "Sim, vale a pena... -33% de diferença". The
existing money-value guard in `narrate()` only catches an invented R$ figure; this reply cited
none, so it passed clean. Scoped narrowly, same shape as `agent.py::_UNLICENSED_DATA_CLAIMS`: only
checked when `PriceCheck.reason` says there IS comparable data (`None` or "quantity_needed", both
carry a real `reference_price`), against phrases lifted from `_PRICE_CHECK_REASON_SENTENCES`
itself -- the vocabulary this exact code already uses for the *other* reasons, so a false claim
borrows the same words a true one would. Nasce de UM caso, cresce com o próximo, mesma disciplina
de toda lista deste tipo no projeto."""


def _contradicts_price_check(output: PriceCheck, remark: str) -> bool:
    if output.reason not in (None, "quantity_needed"):
        return False
    lowered = remark.lower()
    return any(phrase in lowered for phrase in _PRICE_CHECK_NO_DATA_PHRASES)


def _first_per_product(records: Sequence[PriceRecord], limit: int) -> list[PriceRecord]:
    """One row per distinct product, first (most relevant) occurrence wins, capped at `limit`.
    Alternatives are different products -- unlike `_collapse_repeated_prices` in render.py, which
    collapses the same product's repeated (store, price) rows, this never merges two rows of the
    same product either; it just keeps the first one seen and drops the rest."""
    seen: set[int] = set()
    kept: list[PriceRecord] = []
    for record in records:
        if record.product_id in seen:
            continue
        seen.add(record.product_id)
        kept.append(record)
        if len(kept) >= limit:
            break
    return kept


def _near_match_alternatives(deps: Deps, term: str | None) -> list[PriceRecord]:
    """Free, no IA: a search miss that's a near-typo of a real product name already in the
    catalog (services.search.closest_names, v1.1) beats guessing a category -- it's the exact
    thing the person asked for, just spelled differently."""
    if not term:
        return []
    near = search_service.closest_names(deps.conn, term)
    records: list[PriceRecord] = []
    for name, _score in near:
        records.extend(search_service.search_prices(deps.conn, term=name, limit=5))
    return _first_per_product(records, ALT_LIMIT)


def _category_alternatives(deps: Deps, term: str | None, tag: str | None) -> list[PriceRecord]:
    """Alternatives from the same tag/category. `tag` is tried first because it may already be
    known for free (SearchOutcome.tag/detected_tag, from a tag the user named or a word that
    fuzzy-matched a tag name) -- the IA classification (suggest_category) only runs when nothing
    deterministic already answered the question, and only a term the deterministic matchers
    could not connect to any tag by text (e.g. "alcatra" vs "carnes") needs it."""
    if tag is None:
        if term is None or deps.client is None:
            return []
        tag = suggestions.suggest_category(
            deps.conn, deps.config, deps.client, term, search_service.known_tags(deps.conn)
        )
    if tag is None:
        return []
    records = search_service.search_prices(deps.conn, tag=tag, limit=20)
    return _first_per_product(records, ALT_LIMIT)


async def _render_no_match(output: SearchOutcome, deps: Deps) -> Reply:
    """The other half of a zero-result SearchOutcome (see _render_output): instead of the bare
    "Nenhum resultado.", try a near-match by name first, then the same category, then narrate
    whatever was found (or wasn't) through the persona -- same seam as every other reply, never a
    special-cased second AI mechanism for wording."""
    alternatives = _near_match_alternatives(deps, output.term)
    if not alternatives:
        alternatives = _category_alternatives(deps, output.term, output.tag or output.detected_tag)
    facts = no_match_facts(output.term, alternatives)
    remark = await _narrate(deps, "busca sem resultado", facts)
    if remark:
        return Reply(escape(remark))
    return Reply(no_match_fallback_line(output.term, alternatives))


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
        if not records:
            # No client is exactly "IA not configured": the reply must be byte-for-byte what it
            # was before this ticket, never the Julius-toned fallback line (that line is for when
            # a configured client tried and failed, not for "there is no client to try").
            if deps.client is None:
                return Reply(base)
            return await _render_no_match(output, deps)
        if deps.client is None:
            return Reply(base)
        if len(records) > NARRATE_MAX_RECORDS:
            return Reply(base)
        context = _search_narration_context(records)
        remark = await _narrate(deps, context, records_facts(records))
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
    if isinstance(output, ShoppingComparison):
        base = shopping_verdict_line(output)
        groups = output.comparison.comparisons
        if (not groups and not output.unmatched_terms) or deps.client is None:
            return Reply(base)
        if len(groups) > NARRATE_MAX_GROUPS:
            return Reply(base)
        remark = await _narrate(deps, "veredito de lista de compras", shopping_comparison_facts(output))
        if remark:
            return Reply(escape(remark))
        return Reply(base)
    if isinstance(output, PriceCheck):
        base = price_check_fallback_line(output)
        if deps.client is None:
            return Reply(base)
        remark = await _narrate(deps, "conferência de preço ao vivo", price_check_facts(output))
        if remark and _contradicts_price_check(output, remark):
            remark = None
        return Reply(escape(remark)) if remark else Reply(base)
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
    except UnexpectedModelBehavior as error:
        # The output-honesty guard (bot/agent.py::no_unlicensed_data_claims) exhausted its
        # retries without getting a clean answer -- the model kept asserting something no action
        # backed. Never the fabricated text itself, and never the generic "network" wording of
        # AI_UNREACHABLE, which would misname the cause (docs/design/agent-output-honesty.md,
        # Decisão 2).
        _charge(
            deps,
            text,
            attempt=1,
            kind=None,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"agent raised {type(error).__name__}",
        )
        return Reply(f"{prefix}{COULD_NOT_CONFIRM}")
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
    logged_output = result.output if isinstance(result.output, str) else _output_kind(result.output)
    suggestions.record_usage(
        deps.conn,
        deps.config,
        CALL_KIND,
        attempt=1,
        user_prompt=text,
        raw_response=logged_output,
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
    note = _tool_note(result)
    text_out = f"{reply.text}\n\n{escape(note)}" if note else reply.text
    if prefix:
        text_out = f"{prefix}{text_out}"
    return Reply(text_out, pending=reply.pending) if (prefix or note) else reply


EXPIRY_EPSILON_SECONDS = 1e-6
"""Real bug (2026-09-20): `now - pending.created_at > PENDING_TTL_SECONDS` compared against a
`created_at` that is `time.monotonic()` -- a float whose magnitude grows with process uptime.
`(a + 300.0) - a` is not always exactly `300.0` in IEEE754: sampling 2M random magnitudes for `a`
found about 1 in 2200 landing close enough to a rounding boundary to overshoot by up to ~1e-11,
which flips the strict `>` and marks a tap "expired" at the exact TTL instant -- the one case
`test_tap_at_exactly_the_ttl_is_still_valid` fixes as required behavior. This bit only in CI/test
runs long-lived enough to reach an unlucky monotonic value (test passed most of the time, which is
what made it look flaky rather than a comparison bug). 1e-6 s is far below anything a real network
round-trip or button tap could land on, so it can't mask a genuinely expired confirmation."""


def _expired(pending: PendingWrite, now: float) -> bool:
    return now - pending.created_at > PENDING_TTL_SECONDS + EXPIRY_EPSILON_SECONDS


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
