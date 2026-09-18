"""The closed menu the model may choose from. Each action is a plain function: PydanticAI builds
its schema from the type hints and the docstring, and calling one ends the run -- what it returns
is what the bot renders, so the model never narrates an effect it did not have.

The model never sees `conn` or `config`: those arrive through RunContext[Deps], out of its reach.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pydantic_ai import ModelRetry, RunContext

from julius.config import Config
from julius.domain.models import Product, SearchOutcome, Store, StoreComparison
from julius.domain.normalization import digits_only, normalize_text
from julius.services import catalog, comparison as comparison_service, search as search_service

MAX_CANDIDATES = 8  # what fits in a question to the user without becoming a listing


@dataclass(frozen=True)
class Deps:
    conn: sqlite3.Connection
    config: Config


@dataclass(frozen=True)
class ProductListing:
    """An empty `products` means "the catalogue has none", which a bare empty list cannot say."""

    products: tuple[Product, ...]
    containing: str | None = None


@dataclass(frozen=True)
class StoreListing:
    stores: tuple[Store, ...]


def _candidate_list(pairs: list[tuple[int, str]]) -> str:
    return "; ".join(f"{identifier} · {name}" for identifier, name in pairs[:MAX_CANDIDATES])


def resolve_product(conn: sqlite3.Connection, reference: str) -> Product:
    """Turns "o tomate" or "14" into one Product, or refuses with a reason.

    Every bad outcome is a ModelRetry because the message is read by the model, not the user: it
    is what lets it ask the right question instead of guessing an id."""
    reference = reference.strip()
    if reference.isdigit():
        product = catalog.get_product(conn, int(reference))
        if product is None:
            raise ModelRetry(f"Não existe produto com id {reference}. Pergunte ao usuário ou use list_products.")
        return product

    ids = search_service.matching_product_ids(conn, reference)
    if len(ids) == 1:
        product = catalog.get_product(conn, next(iter(ids)))
        if product is not None:
            return product
        ids = set()
    if len(ids) > 1:
        found = [(product.id, product.canonical_name) for product in catalog.list_products(conn) if product.id in ids]
        raise ModelRetry(
            f"Mais de um produto combina com «{reference}»: {_candidate_list(sorted(found))}. "
            "Pergunte ao usuário qual, e chame de novo com o id."
        )
    close = search_service.closest_names(conn, reference)
    if close:
        names = ", ".join(name for name, _ in close)
        raise ModelRetry(f"Nenhum produto chamado «{reference}». Parecidos: {names}. Confirme com o usuário.")
    raise ModelRetry(f"Nenhum produto chamado «{reference}». Use list_products para ver o catálogo.")


def resolve_store(conn: sqlite3.Connection, reference: str) -> Store:
    """Turns "o Assaí" or a CNPJ into one Store, or refuses with a reason."""
    reference = reference.strip()
    stores = catalog.list_stores(conn)
    digits = digits_only(reference)
    if len(digits) == 14:
        for store in stores:
            if store.cnpj == digits:
                return store
        raise ModelRetry(f"Nenhum mercado com o CNPJ {digits}. Use list_stores para ver os mercados.")

    needle = normalize_text(reference)
    matches = [
        store
        for store in stores
        if needle and (needle in normalize_text(store.nickname) or needle in normalize_text(store.legal_name))
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        candidates = "; ".join(f"{store.cnpj} · {store.nickname}" for store in matches[:MAX_CANDIDATES])
        raise ModelRetry(
            f"Mais de um mercado combina com «{reference}»: {candidates}. "
            "Pergunte ao usuário qual, e chame de novo com o CNPJ."
        )
    raise ModelRetry(f"Nenhum mercado chamado «{reference}». Use list_stores para ver os mercados.")


async def search_prices(ctx: RunContext[Deps], words: str, tag: str | None = None, limit: int = 20) -> SearchOutcome:
    """Busca no histórico de preços já pagos, por nome de produto e/ou categoria.

    Args:
        words: palavras do nome do produto, como o usuário falou (ex.: "picanha", "leite"). Pode
            ficar vazio quando `tag` for informada.
        tag: categoria para filtrar (ex.: "hortifruti", "limpeza"). Use apenas quando o usuário
            pedir uma categoria inteira.
        limit: quantas linhas no máximo por unidade de venda. O padrão, 20, serve quase sempre.
    """
    parts = words.split()
    if not parts and tag is None:
        raise ModelRetry("Informe um termo de busca ou uma tag.")
    if limit < 1:
        raise ModelRetry(f"limit precisa ser pelo menos 1, recebi {limit}.")
    try:
        return search_service.search_free_text(
            ctx.deps.conn, parts, tag=tag.lower() if tag else None, limit=limit
        )
    except ValueError as error:
        raise ModelRetry(str(error)) from None


async def compare_stores(ctx: RunContext[Deps]) -> StoreComparison:
    """Compara o preço dos mesmos tipos de produto entre os mercados, para dizer qual sai mais barato."""
    return comparison_service.compare_stores(ctx.deps.conn)


async def list_products(ctx: RunContext[Deps], containing: str | None = None) -> ProductListing:
    """Lista os produtos do catálogo, com id, tipo, conteúdo e categorias.

    Args:
        containing: filtra pelos produtos cujo nome contém este trecho. Use quando o catálogo for
            grande e o usuário estiver procurando um produto específico.
    """
    products = catalog.list_products(ctx.deps.conn)
    if containing:
        needle = normalize_text(containing)
        products = [product for product in products if needle in normalize_text(product.canonical_name)]
    return ProductListing(products=tuple(products), containing=containing)


async def list_stores(ctx: RunContext[Deps]) -> StoreListing:
    """Lista os mercados já importados, com CNPJ, apelido e bairro."""
    return StoreListing(stores=tuple(catalog.list_stores(ctx.deps.conn)))


READ_ACTIONS = (search_prices, compare_stores, list_products, list_stores)
