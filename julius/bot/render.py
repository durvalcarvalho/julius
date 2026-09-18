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
)
from julius.domain.models import KindComparison, PriceRecord, Product, Store, StoreComparison
from julius.domain.normalization import store_place

if TYPE_CHECKING:  # runtime-free: actions imports pydantic_ai, and rendering text must not.
    from julius.bot.actions import PendingWrite, WriteResult

MAX_MESSAGE_CHARS = 4096

TRUNCATION_NOTE = "\n… +{count} linhas não mostradas — peça um limite menor ou uma tag."

# Same map as cli/receipts.py: the word the sentence needs, not the unit code.
_CONTENT_WORDS = {"L": "litro", "KG": "quilo", "UN": "unidade"}

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
