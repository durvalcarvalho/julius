from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone

import typer
from rich.table import Table
from rich.text import Text

from julius.cli._common import console, content_text
from julius.config import Config
from julius.domain.models import AppliedAction, ContentSuggestion, PackagingForm, PackagingHint, Product, ProductProposal
from julius.domain.normalization import normalize_content
from julius.infra import ai_log
from julius.infra.llm_client import LlmClient
from julius.services import catalog, curation, suggestions

_FIELD_LABELS = (("name", "nome(s)"), ("tag", "categoria(s)"), ("content", "conteúdo(s)"), ("kind", "tipo(s)"))

# The AI's own words never reach the screen: `form` is data, this is the vocabulary the user reads.
_FORM_LABELS: dict[PackagingForm, str] = {
    "unit": "unidade",
    "pack": "pacote",
    "volume": "volume",
    "weight": "peso",
    "unknown": "",
}


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _undo_command(action: AppliedAction) -> str:
    """The CLI owns the command syntax; AppliedAction stays pure data (see ticket 121)."""
    product_id = action.product_id
    if action.field == "name":
        return f'julius produtos renomear {product_id} "{action.before}"'
    if action.field == "tag":
        return f"julius produtos tag {product_id} {action.after} --remover"
    if action.field == "content":
        if action.before is None:
            return f"julius produtos definir-conteudo {product_id} --remover"
        return f"julius produtos definir-conteudo {product_id} {action.before}"
    if action.before is None:
        return f"julius produtos tipo {product_id} --remover"
    return f'julius produtos tipo {product_id} "{action.before}"'


def _log_actions(settings: Config, actions: Sequence[AppliedAction]) -> None:
    for action in actions:
        ai_log.append(
            settings.action_log_path,
            {
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "product_id": action.product_id,
                "field": action.field,
                "before": action.before,
                "after": action.after,
                "undo": _undo_command(action),
            },
        )


def _category_cell(proposal: ProductProposal) -> Text:
    """The applied category in normal weight, the discarded candidates dim beside it."""
    discarded = [tag for tag in proposal.tags if tag != proposal.tag]
    if proposal.tag is None:
        return Text(" · ".join(discarded), style="dim")
    return Text.assemble(proposal.tag, (" · " + " · ".join(discarded) if discarded else "", "dim"))


def _or_current(proposed: str, current: str) -> str | Text:
    """An empty cell means one thing only: neither the AI nor the catalog has the value."""
    return proposed if proposed else Text(current, style="dim")


def _current_content(product: Product | None) -> str:
    if product is None or product.content_quantity is None:
        return ""
    return content_text(product.content_quantity, product.content_unit)  # type: ignore[arg-type]


def _table(proposals: Sequence[ProductProposal], products_by_id: dict[int, Product]) -> Table:
    table = Table("ID", "Cupom", "Nome", "Categoria", "Tipo", "Conteúdo")
    for proposal in proposals:
        product = products_by_id.get(proposal.product_id)
        proposed_content = content_text(proposal.content.quantity, proposal.content.unit) if proposal.content else ""
        table.add_row(
            str(proposal.product_id),
            proposal.receipt_description,
            proposal.readable_name or proposal.current_name,
            _category_cell(proposal),
            _or_current(proposal.kind or "", product.kind if product and product.kind else ""),
            _or_current(proposed_content, _current_content(product)),
        )
    return table


def _needs_content(proposal: ProductProposal, products_by_id: dict[int, Product]) -> bool:
    product = products_by_id.get(proposal.product_id)
    return proposal.content is None and proposal.sold_by_unit and product is not None and product.content_quantity is None


def _ask_content(proposal: ProductProposal, hint: PackagingHint | None) -> ContentSuggestion | None:
    """Retail intuition only fills the options; a keystroke is what writes anything. Candidates of a
    product the model called "weight" are dropped: that is exactly where it produced 500 KG of bacon."""
    candidates: tuple[ContentSuggestion, ...] = ()
    if hint is not None and hint.form not in ("weight", "unknown"):
        candidates = hint.candidates
    label = _FORM_LABELS[hint.form] if hint is not None else ""
    options = [f"[{i}] {content_text(c.quantity, c.unit)}" + (f" · {label}" if label else "")
               for i, c in enumerate(candidates, start=1)]
    options.append(f"[{len(candidates) + 1}] digitar")
    options.append("[Enter] pular")
    name = proposal.readable_name or proposal.current_name
    answer = typer.prompt(
        f"{proposal.product_id} · {name} — conteúdo  {'  '.join(options)}", default="", show_default=False
    ).strip()
    if not answer.isdigit():
        return None
    index = int(answer)
    if 1 <= index <= len(candidates):
        return candidates[index - 1]
    if index != len(candidates) + 1:
        return None
    return _typed_content()


def _typed_content() -> ContentSuggestion | None:
    typed = typer.prompt("    quantidade e unidade (ex.: 500 G)", default="", show_default=False).strip().split()
    if len(typed) != 2:
        console.print("  Valor ignorado: escreva quantidade e unidade, como 500 G.")
        return None
    try:
        quantity, unit = normalize_content(float(typed[0].replace(",", ".")), typed[1])
    except ValueError as error:
        console.print(f"  Valor ignorado: {error}")
        return None
    return ContentSuggestion(quantity, unit)


def _ask_pending_content(
    conn, settings: Config, client: LlmClient, pending: Sequence[ProductProposal]
) -> list[ProductProposal]:
    """Asks about every product whose content the AI refused to state, and returns what is still
    missing afterwards."""
    hints: dict[int, PackagingHint] = {}
    if suggestions.is_available(conn, settings):
        catalog_products = [
            Product(id=p.product_id, canonical_name=p.readable_name or p.current_name) for p in pending
        ]
        with console.status(f"Consultando IA sobre a embalagem de {len(pending)} produto(s)…"):
            hints = suggestions.suggest_packaging(conn, settings, client, catalog_products)
    still_missing: list[ProductProposal] = []
    for proposal in pending:
        chosen = _ask_content(proposal, hints.get(proposal.product_id))
        if chosen is None:
            still_missing.append(proposal)
            continue
        answered = replace(proposal, readable_name=None, content=chosen)
        _log_actions(settings, curation.apply(conn, answered, tag=None, content=True, kind=False))
    return still_missing


def review_products(
    conn,
    settings: Config,
    client: LlmClient,
    product_ids: Sequence[int],
    *,
    assume_yes: bool,
    interactive: bool,
) -> bool:
    with console.status(f"Consultando IA para {len(product_ids)} produto(s)…"):
        proposals = curation.propose(conn, settings, client, product_ids)
    if not proposals:
        if not suggestions.is_available(conn, settings):
            console.print("IA indisponível: orçamento do mês esgotado.")
        else:
            console.print(f"IA não respondeu (veja {settings.ai_log_path}).")
        return False

    products_by_id = {product.id: product for product in catalog.list_products(conn)}
    console.print(_table(proposals, products_by_id))

    # Content and kind are applied without asking: both are reversible by a command that already
    # exists (ticket 118) and a wrong value shows up in `produtos listar`/`consultar`. Asking is
    # what left 32 of 79 UN products without content.
    applied: list[AppliedAction] = []
    for proposal in proposals:
        applied += curation.apply(conn, proposal, tag=proposal.tag, content=True, kind=True)
    _log_actions(settings, applied)
    counts = Counter(action.field for action in applied)
    summary = ", ".join(f"{counts[field]} {label}" for field, label in _FIELD_LABELS if counts[field])
    if summary:
        console.print(f"Aplicado: {summary}.")
        console.print("Desfazer ou auditar: julius produtos revisar --ultimas-acoes")

    pending = [p for p in proposals if _needs_content(p, products_by_id)]
    if pending and interactive and not assume_yes:
        pending = _ask_pending_content(conn, settings, client, pending)

    candidates = curation.duplicate_candidates(conn, product_ids)
    duplicates = curation.judge_duplicates(conn, settings, client, candidates)
    if duplicates:
        console.print("Possíveis duplicatas (IA):")
        for candidate in duplicates:
            a, b = candidate.product_a, candidate.product_b
            console.print(
                f"  julius produtos fundir {b.id} {a.id}    "
                f"# {a.canonical_name} ≈ {b.canonical_name} — mesmo produto "
                f"({candidate.ai.confidence:.2f}): {candidate.ai.rationale}"
            )

    if pending:
        console.print(f"Pendentes: {len(pending)} produto(s) sem conteúdo.")

    return True
