"""The same facts the CLI prints, laid out for a phone: minimal HTML, no colour, 4096 characters.

Rendering twice is the feature, not duplication -- the rules (highlight, comparison basis, row
collapsing) arrive already decided in the domain objects; only the layout differs.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

from julius.domain.comparison_basis import comparison_basis
from julius.domain.formatting import (
    br_date,
    content_text,
    coverage_text,
    money,
    plural_groups,
    relative_age,
    store_labels,
    weekday_phrase,
)
from julius.domain.models import KindComparison, PriceCheck, PriceRecord, Product, Store, StoreComparison
from julius.domain.normalization import store_place

if TYPE_CHECKING:  # runtime-free: actions imports pydantic_ai, and rendering text must not.
    from julius.bot.actions import PendingWrite, ShoppingComparison, WriteResult

MAX_MESSAGE_CHARS = 4096

TRUNCATION_NOTE = "\n… +{count} linhas não mostradas — peça um limite menor ou uma tag."

# Same map as cli/receipts.py: the word the sentence needs, not the unit code.
_CONTENT_WORDS = {"L": "litro", "KG": "quilo", "UN": "unidade"}

# Plural, for "quantos quilos você vai comprar?" -- asking quantity (Decisão 4, docs/design/
# quantity-aware-verdict.md) always names more than one, unlike _CONTENT_WORDS' singular.
_CONTENT_WORDS_PLURAL = {"L": "litros", "KG": "quilos", "UN": "unidades"}

# With the article, for a sale/content unit spoken inline ("R$ 3,79 o quilo") -- unit matters to
# how a person reads a price (design v2.7 feedback: never omit it), and gender isn't uniform
# across the three codes, so this can't be built from _CONTENT_WORDS with one fixed article.
_UNIT_PHRASES = {"L": "o litro", "KG": "o quilo", "UN": "a unidade"}

_MARKERS = {"lowest": "▼ ", "highest": "▲ "}
_NO_MARKER = "  "  # two spaces, so unmarked lines stay aligned under the marked ones


def escape(text: str) -> str:
    """Everything read from the database goes through here. An `AÇÚCAR & CIA` left raw makes
    Telegram reject the whole message, and the failure is silent."""
    return html.escape(text, quote=False)


def _store_label(nickname: str, address: str | None) -> str:
    place = store_place(address)
    return f"{escape(nickname)} — {escape(place)}" if place else escape(nickname)


def _record_line(record: PriceRecord, today: date | None) -> str:
    marker = _MARKERS.get(record.highlight or "", _NO_MARKER)
    per_content = (
        f" · {money(record.price_per_content)}/{record.content_unit}" if record.price_per_content is not None else ""
    )
    return (
        f"{marker}{br_date(record.purchased_at)} · {relative_age(record.purchased_at, today=today)}"
        f" · {money(record.unit_price)}{per_content} · {escape(record.canonical_name)}"
        f" · {_store_label(record.store_nickname, record.store_address)}"
    )


def _cheapest_per_content_line(records: Sequence[PriceRecord]) -> str:
    """The rule of cli/receipts.py::_print_cheapest_per_content, copied rather than imported: the
    bot may not reach into cli. States the ordering the lines already carry; not a verdict."""
    basis, participants = comparison_basis(records)
    if basis != "price_per_content" or len(participants) < 2:
        return ""
    ranked = sorted((records[i] for i in participants), key=lambda record: record.price_per_content or 0.0)
    cheapest, dearest = ranked[0], ranked[-1]
    if cheapest.price_per_content == dearest.price_per_content:
        return ""
    word = _CONTENT_WORDS.get(cheapest.content_unit or "", "unidade")
    # "contra" instead of an article: product names have any gender and no rule fits all.
    return (
        f"<i>Mais barato por {word}: {escape(cheapest.canonical_name)} a "
        f"{money(cheapest.price_per_content)}/{cheapest.content_unit} — contra "
        f"{money(dearest.price_per_content)}/{dearest.content_unit} de {escape(dearest.canonical_name)}.</i>"
    )


def render_records(records: Sequence[PriceRecord], *, today: date | None = None) -> str:
    if not records:
        return "Nenhum resultado."
    blocks: list[str] = []
    for unit in dict.fromkeys(record.unit for record in records):
        group = [record for record in records if record.unit == unit]
        lines = "\n".join(_record_line(record, today) for record in group)
        block = f"<b>Preços por {unit}</b>\n<pre>{lines}</pre>"
        cheapest = _cheapest_per_content_line(group)
        blocks.append(f"{block}\n{cheapest}" if cheapest else block)
    return fit("\n\n".join(blocks))


def search_fallback_line(records: Sequence[PriceRecord], *, today: date | None = None) -> str:
    """The Julius-toned answer for when the IA isn't there to say it -- written by hand, no model
    involved, so it's always available. Reuses `highlight` the same way `_record_line` does;
    never recomputes a min/max other than the one difference this function itself states, in
    Python, not left to a model."""
    if not records:
        return "Nenhum resultado."
    if len(records) == 1:
        record = records[0]
        unit_word = _UNIT_PHRASES.get(record.unit, "a unidade")
        return (
            f"Só uma compra registrada: {record.canonical_name} a {money(record.unit_price)} {unit_word} "
            f"em {record.store_nickname}, {relative_age(record.purchased_at, today=today)}."
        )
    cheapest = next((record for record in records if record.highlight == "lowest"), None)
    dearest = next((record for record in records if record.highlight == "highest"), None)
    if cheapest is None or dearest is None:
        return f"{len(records)} compras registradas de {records[0].canonical_name}. Fica de olho nos preços."
    unit_word = _UNIT_PHRASES.get(cheapest.unit, "a unidade")
    diff = money(dearest.unit_price - cheapest.unit_price)
    return (
        f"Já paguei de {money(cheapest.unit_price)} {unit_word}, em {cheapest.store_nickname}, até "
        f"{money(dearest.unit_price)}, em {dearest.store_nickname}, por {records[0].canonical_name} "
        f"— diferença de {diff}. Presta atenção da próxima vez."
    )


def no_match_facts(term: str | None, alternatives: Sequence[PriceRecord]) -> str:
    """Facts for the persona when a search came back empty (brainstorm 2026-09-20: "quanto tá o kg
    de alcatra" answering just "Nenhum resultado." is a dead end). Deliberately never a
    cheapest/dearest diff line like `records_facts` has -- `alternatives` are different products,
    sometimes sold by different units, and diffing their prices would break the same
    never-compare-across-units rule `comparison_basis` exists to enforce elsewhere."""
    what = term or "isso"
    lines = [f"produto pedido, sem preço registrado ainda: {what}"]
    for record in alternatives:
        unit_word = _UNIT_PHRASES.get(record.unit, "a unidade")
        lines.append(f"{record.canonical_name} · {money(record.unit_price)} {unit_word} · {record.store_nickname}")
    return "\n".join(lines)


def no_match_fallback_line(term: str | None, alternatives: Sequence[PriceRecord]) -> str:
    """Same spirit as search_fallback_line: no model, always available.

    The no-alternatives branch dropped the "me diga outro produto que eu confiro?" invitation
    (docs/requirements/bot-persona-fallback-improvements.md §9): a call-to-action here would ask
    the person to type a price/store back, and there is no write action to record that -- an
    invitation this function can't honor would be exactly the kind of claim the bot's honesty
    guard (no_unlicensed_data_claims) exists to catch elsewhere. This only fixes the WORDING of a
    single occurrence; it stays deterministic, so it still repeats verbatim on reuse -- the persona
    prompt's own "busca sem resultado" example (services/suggestions.py) is what's meant to vary
    when the model is available at all."""
    what = term or "isso"
    if not alternatives:
        return f"{what[:1].upper()}{what[1:]} eu ainda não tenho na conta."
    parts = [
        f"{record.canonical_name} a {money(record.unit_price)} {_UNIT_PHRASES.get(record.unit, 'a unidade')}"
        f" em {record.store_nickname}"
        for record in alternatives
    ]
    return f"Ainda não tenho preço de {what}, mas tenho: " + "; ".join(parts) + ". Quer ver mais alguma coisa parecida?"


def _collapse_repeated_prices(records: Sequence[PriceRecord]) -> list[PriceRecord]:
    """Same store, same price, different date -- the real screenshot that started the v2.7.1
    humanization round had this exact repetition (Costa Atacadao twice, one price). Keeps the most
    recent occurrence of each (store, price) pair, in first-seen order; never collapses across
    different stores or prices, even for the same product."""
    kept: dict[tuple[str, float], PriceRecord] = {}
    order: list[tuple[str, float]] = []
    for record in records:
        key = (record.store_nickname, record.unit_price)
        if key not in kept:
            order.append(key)
            kept[key] = record
        elif record.purchased_at > kept[key].purchased_at:
            kept[key] = record
    return [kept[key] for key in order]


def records_facts(records: Sequence[PriceRecord], *, today: date | None = None) -> str:
    """Plain-text facts for the persona (ticket 163's `narrate`) -- no HTML, nothing the model
    was not handed. One line per record (after collapsing repeated store+price pairs), same
    source data as `_record_line`, plus the sale unit (per kilo vs. per unit changes how a price
    reads, so it's never left out), the weekday instead of the calendar date, and, with two or
    more records, the cheapest-to-dearest difference already computed here -- the model is handed
    that number as a fact, never asked to do the subtraction itself."""
    records = _collapse_repeated_prices(records)
    lines = []
    for record in records:
        tag = {"lowest": " (mais barato)", "highest": " (mais caro)"}.get(record.highlight or "", "")
        unit_word = _UNIT_PHRASES.get(record.unit, "a unidade")
        per_content = (
            f" · {money(record.price_per_content)}/{record.content_unit}" if record.price_per_content is not None else ""
        )
        lines.append(
            f"{record.canonical_name} · {money(record.unit_price)} {unit_word}{per_content}{tag} · "
            f"{weekday_phrase(record.purchased_at, today=today)} · "
            f"{record.store_nickname}"
        )
    if len(records) >= 2:
        cheapest = next((record for record in records if record.highlight == "lowest"), None)
        dearest = next((record for record in records if record.highlight == "highest"), None)
        if cheapest is not None and dearest is not None and cheapest.unit_price != dearest.unit_price:
            lines.append(
                f"diferença entre o mais barato e o mais caro: {money(dearest.unit_price - cheapest.unit_price)}"
            )
    return "\n".join(lines)


def comparison_facts(comparison: StoreComparison, *, today: date | None = None) -> str:
    """Same shape as `records_facts`, one line per store entry per group -- same source data as
    `_comparison_block`, no HTML, plus the unit and the per-group cheapest-to-dearest difference,
    already computed here."""
    labels = store_labels(comparison)
    lines = []
    for group in comparison.comparisons:
        cheapest, dearest = group.entries[0].price, group.entries[-1].price
        unit_word = (
            _UNIT_PHRASES.get(group.content_unit or "", "a unidade")
            if group.basis == "price_per_content"
            else _UNIT_PHRASES.get(group.unit, "a unidade")
        )
        for entry in group.entries:
            tag = (
                " (mais barato)"
                if entry.price == cheapest
                else " (mais caro)" if entry.price == dearest else ""
            )
            lines.append(
                f"{group.kind} · {labels[entry.store_cnpj]} · {money(entry.price)} {unit_word}{tag} · "
                f"{weekday_phrase(entry.purchased_at, today=today)}"
            )
        if len(group.entries) >= 2 and cheapest != dearest:
            lines.append(f"{group.kind}: diferença entre o mais barato e o mais caro: {money(dearest - cheapest)}")
    return "\n".join(lines)


def _estimated_savings(shopping: ShoppingComparison) -> float:
    """A savings FLOOR, buying 1 unit/kg/L of each winning kind -- not a prediction of what the
    person will actually buy (see docs/design/quantity-aware-verdict.md, Decisão 5). Nothing new
    to compute: `KindComparison.entries` is already cheapest-first, the same cheapest-to-dearest
    gap `comparison_facts` already prints per group, just summed over the kinds the verdict
    actually won."""
    if shopping.verdict is None:
        return 0.0
    won = set(shopping.verdict.won_kinds)
    return sum(
        group.entries[-1].price - group.entries[0].price
        for group in shopping.comparison.comparisons
        if group.kind in won
    )


def _verdict_lines(shopping: ShoppingComparison) -> list[str]:
    """Shared by shopping_comparison_facts and shopping_verdict_line: the winner/runner-up/
    unmatched lines, computed once from fields the caller already has -- never re-derived."""
    lines: list[str] = []
    verdict = shopping.verdict
    if verdict is not None:
        winners = " e ".join(verdict.winner_stores)
        lines.append(f"veredito: {len(verdict.won_kinds)} de {verdict.total_items} itens mais baratos em {winners}")
        savings = _estimated_savings(shopping)
        if savings > 0:
            lines.append(f"economia mínima estimada, comprando 1 de cada: {money(savings)}")
        if verdict.runner_up_store is not None:
            rest = ", ".join(verdict.runner_up_kinds)
            lines.append(f"o resto ({rest}) sai mais em conta em {verdict.runner_up_store}")
    if shopping.single_store_kinds:
        lines.append(f"só tem preço de um mercado ainda, sem comparação possível: {', '.join(shopping.single_store_kinds)}")
    if shopping.unmatched_terms:
        lines.append(f"sem preço comparável registrado ainda para: {', '.join(shopping.unmatched_terms)}")
    return lines


def shopping_comparison_facts(shopping: ShoppingComparison, *, today: date | None = None) -> str:
    """Plain-text facts for the persona: the same per-kind lines as comparison_facts, plus the
    verdict (winner, runner-up) and unmatched terms -- all computed already, the model only ever
    cites these numbers, never sums or compares them itself."""
    lines = [comparison_facts(shopping.comparison, today=today)] if shopping.comparison.comparisons else []
    lines += _verdict_lines(shopping)
    return "\n".join(line for line in lines if line)


def shopping_verdict_line(shopping: ShoppingComparison, *, today: date | None = None) -> str:
    """Same spirit as compare_fallback_line: no model, always available."""
    del today  # signature symmetry with the other render_X/fallback pairs; unused here
    verdict = shopping.verdict
    if verdict is None:
        if shopping.single_store_kinds:
            return (
                "Só tem preço de um mercado ainda, sem comparação possível: "
                f"{', '.join(shopping.single_store_kinds)}."
            )
        if shopping.unmatched_terms:
            return f"Não achei preço comparável entre mercados pra: {', '.join(shopping.unmatched_terms)}."
        return "Não achei preço comparável entre mercados pra esses itens ainda."
    winners = " e ".join(verdict.winner_stores)
    sentence = f"{len(verdict.won_kinds)} de {verdict.total_items} produtos mais baratos em {winners}, vale ir lá."
    savings = _estimated_savings(shopping)
    if savings > 0:
        sentence += f" Economia mínima estimada, comprando 1 de cada: {money(savings)}."
    if verdict.runner_up_store is not None:
        sentence += f" O resto sai mais em conta em {verdict.runner_up_store}."
    if shopping.single_store_kinds:
        sentence += f" Só tem preço de um mercado ainda: {', '.join(shopping.single_store_kinds)}."
    if shopping.unmatched_terms:
        sentence += f" Não achei preço comparável pra: {', '.join(shopping.unmatched_terms)}."
    return sentence


_PRICE_CHECK_REASON_LINES = {
    "unknown_item": "item não reconhecido no catálogo ainda",
    "no_history": "sem histórico de preço registrado para esse tipo ainda",
    "ambiguous_unit": "tenho preço registrado tanto por peso quanto por unidade -- pergunte qual dos dois",
    "no_comparable_basis": (
        "tenho histórico desse tipo, mas de embalagens diferentes sem conteúdo declarado -- "
        "não dá pra comparar sem isso"
    ),
}

_PRICE_CHECK_REASON_SENTENCES = {
    "unknown_item": "Não conheço esse item ainda.",
    "no_history": "Não tenho preço registrado desse tipo ainda.",
    "ambiguous_unit": "Tenho preço registrado tanto por peso quanto por unidade -- me diga qual dos dois.",
    "no_comparable_basis": (
        "Tenho preço desse tipo, mas de embalagens diferentes sem conteúdo declarado -- "
        "não dá pra comparar sem isso (julius produtos definir-conteudo)."
    ),
}


def price_check_facts(check: PriceCheck, *, today: date | None = None) -> str:
    """Plain-text facts for the persona (Decisão 4, docs/design/shopping-verdict-shape.md): the
    verdict is decided here, in code, from `check.verdict` -- the model only ever restates it,
    same discipline as the shopping-list verdict.

    `reason == "quantity_needed"` (docs/design/quantity-aware-verdict.md, Decisão 2) is NOT one of
    the "no data" reasons below -- `check.verdict` is still undecided, but the reference price/
    store/date are already known and must not be thrown away, or the persona could not write the
    user's own example sentence ("você já conseguiu comprar por R$35, quantos kg vai comprar?")."""
    if check.reason is not None and check.reason != "quantity_needed":
        return _PRICE_CHECK_REASON_LINES[check.reason]
    unit_word = _UNIT_PHRASES.get(check.reference_unit or "", "a unidade")
    lines = [
        f"preço informado: {money(check.informed_price)} {unit_word}",
        f"mais barato já registrado: {money(check.reference_price)} {unit_word} "
        f"({weekday_phrase(check.reference_at, today=today)}, {check.reference_store})",
        f"diferença sobre o mais barato: {check.diff_pct:.0f}%",
    ]
    if check.reason == "quantity_needed":
        word = _CONTENT_WORDS_PLURAL.get(check.reference_unit or "", "unidades")
        lines.append(f"pergunte quantos {word} a pessoa vai comprar antes do veredito final")
    else:
        lines.insert(0, f"veredito: {'sim' if check.verdict else 'não'}")
    return "\n".join(lines)


def price_check_fallback_line(check: PriceCheck, *, today: date | None = None) -> str:
    """Same spirit as compare_fallback_line: no model, always available."""
    if check.reason is not None and check.reason != "quantity_needed":
        return _PRICE_CHECK_REASON_SENTENCES[check.reason]
    unit_word = _UNIT_PHRASES.get(check.reference_unit or "", "a unidade")
    if check.reason == "quantity_needed":
        word = _CONTENT_WORDS_PLURAL.get(check.reference_unit or "", "unidades")
        return (
            f"Você viu {money(check.informed_price)} {unit_word}; o mais barato já registrado foi "
            f"{money(check.reference_price)} {unit_word}, em {check.reference_store}, "
            f"{weekday_phrase(check.reference_at, today=today)}. Quantos {word} você vai comprar?"
        )
    verdict_word = "Sim, vale a pena." if check.verdict else "Não, tá caro."
    return (
        f"{verdict_word} Você viu {money(check.informed_price)} {unit_word}; o mais barato já "
        f"registrado foi {money(check.reference_price)} {unit_word}, em {check.reference_store}, "
        f"{weekday_phrase(check.reference_at, today=today)} -- {check.diff_pct:.0f}% de diferença."
    )


def products_facts(products: Sequence[Product]) -> str:
    """A count, not an enumeration -- narrating a 100-row catalogue in prose is the wall-of-text
    problem the design's Modo B exists to avoid."""
    if not products:
        return ""
    return f"{len(products)} produtos no catálogo"


def stores_facts(stores: Sequence[Store]) -> str:
    if not stores:
        return ""
    return f"{len(stores)} mercados importados"


def _comparison_block(group: KindComparison, labels: dict[str, str], today: date | None) -> str:
    if group.basis == "price_per_content":
        basis = f"por {group.content_unit} (por conteúdo)"
    else:
        basis = f"por {group.unit}"
    cheapest, dearest = group.entries[0].price, group.entries[-1].price
    lines = []
    for entry in group.entries:
        marker = _MARKERS["lowest"] if entry.price == cheapest else _MARKERS["highest"] if entry.price == dearest else _NO_MARKER
        lines.append(
            f"{marker}{escape(labels[entry.store_cnpj])} · {money(entry.price)} · {escape(entry.product_name)}"
            f" · {br_date(entry.purchased_at)} ({relative_age(entry.purchased_at, today=today)})"
        )
    return f"<b>{escape(group.kind)} · {basis}</b>\n<pre>" + "\n".join(lines) + "</pre>"


def render_comparison(comparison: StoreComparison, *, today: date | None = None) -> str:
    if not comparison.comparisons:
        if not comparison.kinds_total:
            return "Nenhum produto tem tipo ainda. Rode: julius produtos revisar"
        return (
            "Nenhum tipo de produto foi comprado em dois mercados ainda — sem base para comparar."
            f"\n<i>Cobertura: {coverage_text(comparison)}.</i>"
        )

    labels = store_labels(comparison)
    parts = [_comparison_block(group, labels, today) for group in comparison.comparisons]

    appearances: dict[str, int] = {}
    wins: dict[str, int] = {}
    for group in comparison.comparisons:
        wins[group.entries[0].store_cnpj] = wins.get(group.entries[0].store_cnpj, 0) + 1
        for entry in group.entries:
            appearances[entry.store_cnpj] = appearances.get(entry.store_cnpj, 0) + 1
    tally = [
        f"{escape(labels[cnpj])}: mais barato em {wins.get(cnpj, 0)} de {total} {plural_groups(total)}"
        for cnpj, total in sorted(appearances.items(), key=lambda item: (-wins.get(item[0], 0) / item[1], labels[item[0]]))
    ]
    parts.append("\n".join(tally))

    count = len(comparison.comparisons)
    base = (
        f"base: {count} {plural_groups(count)} · "
        f"{br_date(comparison.first_purchase)} a {br_date(comparison.last_purchase)}"
    )
    if comparison.kinds_single_store:
        base += f" · {coverage_text(comparison)}"
    parts.append(
        f"{base}\n<i>Período largo: parte da diferença pode ser variação de preço no mês, não o mercado.</i>"
    )
    return fit("\n\n".join(parts))


def compare_fallback_line(comparison: StoreComparison, *, today: date | None = None) -> str:
    """Same spirit as `search_fallback_line`: no model, always available. `today` is accepted for
    signature symmetry with the other render_X/fallback pairs, unused here (no relative age in a
    per-group summary)."""
    if not comparison.comparisons:
        if not comparison.kinds_total:
            return "Nenhum produto tem tipo ainda. Rode: julius produtos revisar"
        return "Nenhum tipo de produto foi comprado em dois mercados ainda — sem base para comparar."
    lines = []
    for group in comparison.comparisons:
        unit_word = (
            _UNIT_PHRASES.get(group.content_unit or "", "a unidade")
            if group.basis == "price_per_content"
            else _UNIT_PHRASES.get(group.unit, "a unidade")
        )
        lines.append(
            f"{group.kind}: {group.entries[0].store_nickname} sai mais em conta, a "
            f"{money(group.entries[0].price)} {unit_word}."
        )
    return " ".join(lines)


def render_products(products: Sequence[Product]) -> str:
    if not products:
        return "Nenhum produto importado ainda."
    lines = []
    for product in products:
        content = (
            content_text(product.content_quantity, product.content_unit)
            if product.content_quantity is not None and product.content_unit
            else "—"
        )
        tags = ", ".join(escape(tag) for tag in product.tags) if product.tags else "—"
        lines.append(
            f"{product.id} · {escape(product.canonical_name)} · {escape(product.kind) if product.kind else '—'}"
            f" · {content} · {tags}"
        )
    return fit("<pre>" + "\n".join(lines) + "</pre>")


def render_stores(stores: Sequence[Store]) -> str:
    if not stores:
        return "Nenhum mercado importado ainda."
    lines = []
    for store in stores:
        place = store_place(store.address)
        suffix = f" · {escape(place)}" if place else ""
        lines.append(f"{escape(store.cnpj)} · {escape(store.nickname)}{suffix}")
    return fit("<pre>" + "\n".join(lines) + "</pre>")


WRITE_REFUSED_LINE = (
    "Essa parte eu não abro pra qualquer um — por aqui você só consulta. Se quiser mexer em nome "
    "de mercado, categoria ou fusão de produto, peça pra quem te chamou te colocar na lista de "
    "confiança."
)
"""docs/design/bot-read-only-tier.md: mesma família de search_fallback_line/compare_fallback_line
-- escrita à mão, sem modelo, sempre disponível. Não varia por dado nenhum (nenhum registro,
nenhuma comparação), por isso é constante e não função como as outras. Nunca deve conter nenhuma
das frases de bot/agent.py::_UNLICENSED_DATA_CLAIMS."""


def render_pending(pending: PendingWrite) -> str:
    """The message the user reads before tapping. The preview was built from the database, never
    from the text the model typed."""
    return f"⚠️ <b>Confirmar?</b>\n{escape(pending.preview)}"


def render_result(result: WriteResult) -> str:
    return f"✅ {escape(result.summary)}\nDesfazer: <code>{escape(result.undo)}</code>"


def render_failure(reason: str) -> str:
    return f"❌ Não executado: {escape(reason)}"


def fit(text: str) -> str:
    """Telegram rejects anything past 4096 characters, so the cut is ours to make. Cutting at a
    line keeps the last row readable, and a `<pre>` left open would swallow the note itself."""
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    lines = text.split("\n")
    kept: list[str] = []
    for line in lines:
        # The note grows as lines are dropped, so its cost is recomputed against the worst case.
        note = TRUNCATION_NOTE.format(count=len(lines) - len(kept) - 1)
        closing = "</pre>" if _pre_is_open("\n".join([*kept, line])) else ""
        cost = len("\n".join([*kept, line])) + len(closing) + len(note)
        if cost > MAX_MESSAGE_CHARS:
            break
        kept.append(line)
    body = "\n".join(kept)
    if _pre_is_open(body):
        body += "</pre>"
    return body + TRUNCATION_NOTE.format(count=len(lines) - len(kept))


def _pre_is_open(text: str) -> bool:
    return text.count("<pre>") > text.count("</pre>")
