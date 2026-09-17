from __future__ import annotations

from typing import Annotated, Optional

import typer
from rich.table import Table

from julius import config
from julius.cli import _review
from julius.cli._common import console, content_text, fail, open_db
from julius.cli._hints import print_hints
from julius.domain.models import Product
from julius.infra import ai_log
from julius.infra.llm_client import HttpLlmClient
from julius.services import catalog, curation, guidance, suggestions

app = typer.Typer()


@app.command("listar")
def list_products() -> None:
    """Lista os produtos do catálogo com id, nome, conteúdo da embalagem e tags."""
    conn = open_db()
    try:
        products = catalog.list_products(conn)
    finally:
        conn.close()
    if not products:
        console.print("Nenhum produto importado ainda.")
        return
    table = Table("ID", "Nome", "Tipo", "Conteúdo", "Tags")
    for product in products:
        table.add_row(
            str(product.id), product.canonical_name, product.kind or "", _content(product), ", ".join(product.tags)
        )
    console.print(table)


@app.command("renomear")
def rename_product(
    product_id: Annotated[int, typer.Argument(help="ID do produto (veja `produtos listar`).")],
    name: Annotated[str, typer.Argument(help="Novo nome.")],
) -> None:
    """Troca o nome automático (descrição do primeiro cupom) por um legível."""
    conn = open_db()
    try:
        catalog.rename_product(conn, product_id, name)
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    console.print(f"Produto {product_id} agora é '{name.strip()}'.")


@app.command("fundir")
def merge_products(
    source_id: Annotated[int, typer.Argument(help="ID do produto que vai desaparecer.")],
    target_id: Annotated[int, typer.Argument(help="ID do produto que fica com todo o histórico.")],
    yes: Annotated[bool, typer.Option("--sim", "-y", help="Não pedir confirmação.")] = False,
) -> None:
    """Funde dois produtos que são a mesma coisa. Irreversível."""
    conn = open_db()
    try:
        names = {product.id: product.canonical_name for product in catalog.list_products(conn)}
        source = names.get(source_id, f"#{source_id}")
        target = names.get(target_id, f"#{target_id}")
        if not yes and not typer.confirm(f"Fundir '{source}' em '{target}'? Não dá para desfazer."):
            console.print("Cancelado.")
            return
        catalog.merge_products(conn, source_id, target_id)
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    console.print(f"'{source}' fundido em '{target}'.")


@app.command("tag")
def tag_product(
    product_id: Annotated[int, typer.Argument(help="ID do produto.")],
    tag: Annotated[str, typer.Argument(help="Categoria livre, ex.: limpeza, hortifruti.")],
    remove: Annotated[bool, typer.Option("--remover", help="Remove a tag em vez de marcar.")] = False,
) -> None:
    """Marca ou remove a tag de um produto (filtra depois em `consultar --tag`)."""
    conn = open_db()
    try:
        if remove:
            catalog.untag_product(conn, product_id, tag)
        else:
            catalog.tag_product(conn, product_id, tag)
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    normalized = tag.strip().lower()
    if remove:
        console.print(f"Tag '{normalized}' removida do produto {product_id}.")
    else:
        console.print(f"Produto {product_id} marcado com '{normalized}'.")


@app.command("tipo")
def set_kind(
    product_id: Annotated[int, typer.Argument(help="ID do produto.")],
    kind: Annotated[Optional[str], typer.Argument(help="Tipo da coisa, ex.: tomate, leite uht.")] = None,
    remove: Annotated[bool, typer.Option("--remover", help="Remove o tipo em vez de definir.")] = False,
) -> None:
    """Define o tipo do produto — o grupo usado para comparar preço entre mercados."""
    if remove and kind is not None:
        fail("Use `--remover` sem informar o TIPO.")
    if not remove and kind is None:
        fail("Informe o TIPO ou use `--remover`.")
    conn = open_db()
    try:
        if remove:
            catalog.clear_product_kind(conn, product_id)
        else:
            catalog.set_product_kind(conn, product_id, kind)  # type: ignore[arg-type]
        name = _name_of(conn, product_id)
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    if remove:
        console.print(f"{product_id} · {name} → tipo removido")
    else:
        console.print(f'{product_id} · {name} → tipo "{kind.strip().lower()}"')  # type: ignore[union-attr]


@app.command("definir-conteudo")
def set_content(
    product_id: Annotated[int, typer.Argument(help="ID do produto.")],
    quantity: Annotated[Optional[float], typer.Argument(help="Quantidade na embalagem, ex.: 500.")] = None,
    unit: Annotated[Optional[str], typer.Argument(help="L, ML, KG, G ou UN.")] = None,
    remove: Annotated[bool, typer.Option("--remover", help="Remove o conteúdo em vez de definir.")] = False,
) -> None:
    """Informa o conteúdo da embalagem para comparar preço por litro/kg/unidade."""
    if remove and (quantity is not None or unit is not None):
        fail("Use `--remover` sem informar QTD e UNIDADE.")
    if not remove and (quantity is None or unit is None):
        fail("Informe QTD e UNIDADE ou use `--remover`.")
    conn = open_db()
    try:
        if remove:
            catalog.clear_product_content(conn, product_id)
        else:
            catalog.set_product_content(conn, product_id, quantity, unit)  # type: ignore[arg-type]
        name = _name_of(conn, product_id)
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    if remove:
        console.print(f"{product_id} · {name} → conteúdo removido")
    else:
        console.print(f"Conteúdo do produto {product_id} definido.")


@app.command("comparar")
def compare_products(
    id_a: Annotated[int, typer.Argument(help="ID do primeiro produto.")],
    id_b: Annotated[int, typer.Argument(help="ID do segundo produto.")],
) -> None:
    """Opina se dois produtos são a mesma coisa (texto + IA, se configurada). Não funde nada."""
    settings = config.load()
    conn = open_db()
    try:
        names = {product.id: product.canonical_name for product in catalog.list_products(conn)}
        comparison = catalog.compare_products(conn, settings, HttpLlmClient.from_config(settings), id_a, id_b)
        budget_exhausted = settings.ai_configured and not suggestions.is_available(conn, settings)
        spent = suggestions.spent_this_month(conn) if budget_exhausted else 0.0
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    console.print(f"A: {names[id_a]}")
    console.print(f"B: {names[id_b]}")
    console.print(f"Similaridade de texto: {comparison.text_similarity:.0%}")
    suggestion = comparison.ai_suggestion
    if suggestion is not None:
        verdict = "mesmo produto" if suggestion.same_product else "produtos diferentes"
        console.print(f"IA: {verdict} (confiança {suggestion.confidence:.1f}) — {suggestion.rationale}")
    elif budget_exhausted:
        console.print(f"IA indisponível: orçamento do mês esgotado (US$ {spent:.2f} de US$ {settings.ai_budget_usd:.2f}).")
    elif settings.ai_configured:
        console.print(f"IA indisponível: a chamada falhou — veja {settings.ai_log_path}.")
    console.print(f"Para fundir: julius produtos fundir {id_a} {id_b}")
    print_hints(guidance.for_compare(settings))


@app.command("revisar")
def review(
    yes: Annotated[bool, typer.Option(
            "--sim",
            "-y",
            help="Não perguntar nada; conteúdo que a IA não soube fica pendente para a próxima revisão.",
        )] = False,
    last_actions: Annotated[
        bool,
        typer.Option("--ultimas-acoes", help="Mostra as últimas ações que a IA aplicou, com o comando para desfazer."),
    ] = False,
) -> None:
    """Pede à IA nome legível, categoria, conteúdo e tipo para produtos ainda sem tag."""
    settings = config.load()
    if last_actions:
        _print_last_actions(settings.action_log_path)
        return
    client = HttpLlmClient.from_config(settings)
    conn = open_db()
    try:
        if client is None:
            print_hints(guidance.for_compare(settings))
            return
        ids = curation.pending_product_ids(conn)
        if not ids:
            console.print("Nenhum produto pendente de revisão.")
            return
        interactive = not yes and _review._is_interactive()
        _review.review_products(conn, settings, client, ids, assume_yes=yes, interactive=interactive)
    finally:
        conn.close()


def _print_last_actions(path) -> None:
    records = ai_log.tail(path)
    if not records:
        console.print("Nenhuma ação automática registrada ainda.")
        return
    table = Table("Quando", "ID", "Campo", "Antes", "Depois", "Desfazer")
    for record in records:
        when = str(record.get("at") or "")[:16].replace("T", " ")
        table.add_row(
            when,
            str(record.get("product_id") or ""),
            str(record.get("field") or ""),
            str(record.get("before") or ""),
            str(record.get("after") or ""),
            str(record.get("undo") or ""),
        )
    console.print(table)


def _name_of(conn, product_id: int) -> str:
    product = next((p for p in catalog.list_products(conn) if p.id == product_id), None)
    return f"#{product_id}" if product is None else product.canonical_name


def _content(product: Product) -> str:
    if product.content_quantity is None:
        return ""
    return content_text(product.content_quantity, product.content_unit)
