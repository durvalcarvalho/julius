from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from julius.cli._common import console, fail, open_db
from julius.domain.models import Product
from julius.services import catalog

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
    table = Table("ID", "Nome", "Conteúdo", "Tags")
    for product in products:
        table.add_row(str(product.id), product.canonical_name, _content(product), ", ".join(product.tags))
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
) -> None:
    """Marca um produto com uma tag para filtrar depois em `consultar --tag`."""
    conn = open_db()
    try:
        catalog.tag_product(conn, product_id, tag)
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    console.print(f"Produto {product_id} marcado com '{tag.strip().lower()}'.")


@app.command("definir-conteudo")
def set_content(
    product_id: Annotated[int, typer.Argument(help="ID do produto.")],
    quantity: Annotated[float, typer.Argument(help="Quantidade na embalagem, ex.: 500.")],
    unit: Annotated[str, typer.Argument(help="L, ML, KG, G ou UN.")],
) -> None:
    """Informa o conteúdo da embalagem para comparar preço por litro/kg/unidade."""
    conn = open_db()
    try:
        catalog.set_product_content(conn, product_id, quantity, unit)
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    console.print(f"Conteúdo do produto {product_id} definido.")


def _content(product: Product) -> str:
    if product.content_quantity is None:
        return ""
    return f"{product.content_quantity:g}".replace(".", ",") + f" {product.content_unit}"
