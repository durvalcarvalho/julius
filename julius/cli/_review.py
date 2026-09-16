from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import replace

import typer
from rich.table import Table

from julius.cli._common import console
from julius.config import Config
from julius.domain.models import ProductProposal
from julius.infra.llm_client import LlmClient
from julius.services import curation, suggestions


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _confirm_pt(text: str, *, default: bool) -> bool:
    """Portuguese yes/no: typer.confirm only understands y/n, our users type s/n."""
    suffix = "S/n" if default else "s/N"
    raw = typer.prompt(f"{text} [{suffix}]", default="", show_default=False).strip().lower()
    if not raw:
        return default
    return raw in ("s", "sim", "y", "yes")


def _table(proposals: Sequence[ProductProposal]) -> Table:
    table = Table("ID", "Cupom", "Nome", "Categoria", "Conteúdo")
    for proposal in proposals:
        name = proposal.readable_name or proposal.current_name
        category = proposal.auto_tag or ("? " + ", ".join(proposal.tags) if proposal.tags else "")
        content = f"{proposal.content.quantity:g} {proposal.content.unit}" if proposal.content else ""
        table.add_row(str(proposal.product_id), proposal.current_name, name, category, content)
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

    renamed = sum(1 for proposal in proposals if proposal.readable_name)
    auto_tagged = sum(1 for proposal in proposals if proposal.auto_tag)
    for proposal in proposals:
        curation.apply(conn, proposal, tag=proposal.auto_tag, content=False, kind=False)
    console.print(
        f"Aplicado: {renamed} nome(s), {auto_tagged} categoria(s). "
        'Desfazer: julius produtos renomear ID "Nome" · julius produtos tag ID TAG --remover'
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
            curation.apply(conn, proposal, tag=chosen, content=False, kind=False)
        else:
            pending += 1

    for proposal in proposals:
        if not proposal.content:
            continue
        quantity, unit = proposal.content.quantity, proposal.content.unit
        name = proposal.readable_name or proposal.current_name
        if interactive:
            if _confirm_pt(f"{proposal.product_id} · {name} — definir conteúdo {quantity:g} {unit}?", default=True):
                curation.apply(conn, replace(proposal, readable_name=None), tag=None, content=True, kind=False)
        else:
            console.print(f"julius produtos definir-conteudo {proposal.product_id} {quantity:g} {unit}")

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
