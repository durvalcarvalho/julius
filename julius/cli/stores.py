from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from julius.cli._common import console, fail, open_db
from julius.domain.normalization import digits_only
from julius.services import catalog

app = typer.Typer()


@app.command("listar")
def list_stores() -> None:
    """Lista os mercados já importados, com CNPJ, razão social e apelido."""
    conn = open_db()
    try:
        stores = catalog.list_stores(conn)
    finally:
        conn.close()
    if not stores:
        console.print("Nenhum mercado importado ainda.")
        return
    table = Table("CNPJ", "Razão social", "Apelido", "Endereço")
    for store in stores:
        table.add_row(store.cnpj, store.legal_name, store.nickname, store.address or "")
    console.print(table)


@app.command("renomear")
def rename_store(
    cnpj: Annotated[str, typer.Argument(help="CNPJ do mercado, formatado ou só dígitos.")],
    nickname: Annotated[str, typer.Argument(help="Apelido pelo qual você reconhece o mercado.")],
) -> None:
    """Dá um apelido legível a um mercado (a razão social do cupom raramente ajuda)."""
    cnpj = digits_only(cnpj)
    conn = open_db()
    try:
        catalog.rename_store(conn, cnpj, nickname)
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    console.print(f"Mercado {cnpj} agora é '{nickname.strip()}'.")
