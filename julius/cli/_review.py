from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone

import typer
from rich.table import Table

from julius.cli._common import console
from julius.config import Config
from julius.domain.models import AppliedAction, ProductProposal
from julius.infra import ai_log
from julius.infra.llm_client import LlmClient
from julius.services import curation, suggestions

_FIELD_LABELS = (("name", "nome(s)"), ("tag", "categoria(s)"), ("content", "conteúdo(s)"), ("kind", "tipo(s)"))


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


def _table(proposals: Sequence[ProductProposal]) -> Table:
    table = Table("ID", "Cupom", "Nome", "Categoria", "Tipo", "Conteúdo")
    for proposal in proposals:
        name = proposal.readable_name or proposal.current_name
        category = proposal.auto_tag or ("? " + ", ".join(proposal.tags) if proposal.tags else "")
        content = f"{proposal.content.quantity:g} {proposal.content.unit}" if proposal.content else ""
        table.add_row(str(proposal.product_id), proposal.current_name, name, category, proposal.kind or "", content)
    return table


def _ask_tag(proposal: ProductProposal) -> str | None:
    options = "  ".join(
        [f"[{i}] {tag}" for i, tag in enumerate(proposal.tags, start=1)]
        + [f"[{len(proposal.tags) + 1}] outra", "[Enter] pular"]
    )
    name = proposal.readable_name or proposal.current_name
    answer = typer.prompt(f"{proposal.product_id} · {name} — categoria  {options}", default="", show_default=False)
    answer = answer.strip()
    if not answer.isdigit():
        return None
    index = int(answer)
    if 1 <= index <= len(proposal.tags):
        return proposal.tags[index - 1]
    if index == len(proposal.tags) + 1:
        new_tag = typer.prompt("    nova categoria").strip()
        return new_tag or None
    return None


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

    console.print(_table(proposals))

    # Content and kind are applied without asking: both are reversible by a command that already
    # exists (ticket 118) and a wrong value shows up in `produtos listar`/`consultar`. Asking is
    # what left 32 of 79 UN products without content.
    applied: list[AppliedAction] = []
    for proposal in proposals:
        applied += curation.apply(conn, proposal, tag=proposal.auto_tag, content=True, kind=True)
    _log_actions(settings, applied)
    counts = Counter(action.field for action in applied)
    summary = ", ".join(f"{counts[field]} {label}" for field, label in _FIELD_LABELS if counts[field])
    if summary:
        console.print(f"Aplicado: {summary}.")
        console.print(
            "Desfazer: julius produtos renomear · julius produtos tag --remover · "
            "julius produtos definir-conteudo --remover · julius produtos tipo --remover"
        )

    pending = 0
    for proposal in proposals:
        if proposal.auto_tag is not None:
            continue
        chosen: str | None = None
        if interactive:
            chosen = _ask_tag(proposal)
        elif assume_yes:
            chosen = proposal.tags[0]
        if chosen:
            _log_actions(settings, curation.apply(conn, proposal, tag=chosen, content=False, kind=False))
        else:
            pending += 1

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
        console.print(f"Pendentes: {pending} produto(s) sem categoria.")

    return True
