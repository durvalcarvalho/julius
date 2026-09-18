"""The closed menu the model may choose from. Each action is a plain function: PydanticAI builds
its schema from the type hints and the docstring, and calling one ends the run -- what it returns
is what the bot renders, so the model never narrates an effect it did not have.

The model never sees `conn` or `config`: those arrive through RunContext[Deps], out of its reach.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from collections.abc import Mapping
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


@dataclass(frozen=True)
class PendingWrite:
    """What a write *would* do. Nothing is stored until the tap calls execute.

    `args` carries resolved ids, never the text the model typed: re-resolving a name at execution
    time could land on a different product than the one the preview described."""

    action: str
    args: Mapping[str, object]
    preview: str
    nonce: str
    created_at: float


@dataclass(frozen=True)
class WriteResult:
    summary: str
    undo: str


class WriteFailed(Exception):
    """A escrita não aconteceu; str(exc) é o motivo, em português."""


def _pending(action: str, args: Mapping[str, object], preview: str) -> PendingWrite:
    return PendingWrite(
        action=action,
        args=args,
        preview=preview,
        nonce=secrets.token_urlsafe(8),
        created_at=time.monotonic(),
    )


def _required(value: str, what: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ModelRetry(f"{what} não pode ficar vazio.")
    return stripped


async def rename_product(ctx: RunContext[Deps], product: str, name: str) -> PendingWrite:
    """Dá um nome legível a um produto (o nome inicial é a descrição crua do cupom).

    Args:
        product: o produto, pelo id que uma listagem mostrou ou pelo nome como o usuário falou.
        name: o nome novo, em português e com acentos.
    """
    name = _required(name, "O nome")
    found = resolve_product(ctx.deps.conn, product)
    return _pending(
        "rename_product",
        {"product_id": found.id, "name": name},
        f"Renomear o produto {found.id} «{found.canonical_name}» para «{name}»",
    )


async def rename_store(ctx: RunContext[Deps], store: str, nickname: str) -> PendingWrite:
    """Dá um apelido reconhecível a um mercado (a razão social do cupom raramente ajuda).

    Args:
        store: o mercado, pelo CNPJ ou por um trecho do apelido/razão social.
        nickname: o apelido novo. Vale incluir o bairro quando há duas filiais da mesma rede.
    """
    nickname = _required(nickname, "O apelido")
    found = resolve_store(ctx.deps.conn, store)
    return _pending(
        "rename_store",
        {"cnpj": found.cnpj, "nickname": nickname},
        f"Dar ao mercado {found.cnpj} «{found.nickname}» o apelido «{nickname}»",
    )


async def tag_product(ctx: RunContext[Deps], product: str, tag: str) -> PendingWrite:
    """Marca um produto com uma categoria de corredor (hortifruti, limpeza, bebidas...).

    Args:
        product: o produto, pelo id ou pelo nome.
        tag: a categoria, uma palavra em minúsculas.
    """
    tag = _required(tag, "A tag").lower()
    found = resolve_product(ctx.deps.conn, product)
    if tag in found.tags:
        raise ModelRetry(f"O produto {found.id} já tem a tag «{tag}».")
    return _pending(
        "tag_product",
        {"product_id": found.id, "tag": tag},
        f"Marcar o produto {found.id} «{found.canonical_name}» com a tag «{tag}»",
    )


async def untag_product(ctx: RunContext[Deps], product: str, tag: str) -> PendingWrite:
    """Tira uma categoria de um produto.

    Args:
        product: o produto, pelo id ou pelo nome.
        tag: a categoria a remover.
    """
    tag = _required(tag, "A tag").lower()
    found = resolve_product(ctx.deps.conn, product)
    if tag not in found.tags:
        have = ", ".join(found.tags) if found.tags else "nenhuma"
        raise ModelRetry(f"O produto {found.id} não tem a tag «{tag}»; tem: {have}.")
    return _pending(
        "untag_product",
        {"product_id": found.id, "tag": tag},
        f"Remover a tag «{tag}» do produto {found.id} «{found.canonical_name}»",
    )


def _quotable(text: str) -> str:
    """A name with a double quote would break the undo command the user is meant to paste."""
    return text.replace('"', "'")


def _product_now(conn: sqlite3.Connection, product_id: int) -> Product:
    product = catalog.get_product(conn, product_id)
    if product is None:
        raise WriteFailed(f"O produto {product_id} não existe mais.")
    return product


def _store_now(conn: sqlite3.Connection, cnpj: str) -> Store:
    for store in catalog.list_stores(conn):
        if store.cnpj == cnpj:
            return store
    raise WriteFailed(f"O mercado {cnpj} não existe mais.")


def _do_rename_product(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    product_id, name = int(args["product_id"]), str(args["name"])
    before = _product_now(deps.conn, product_id).canonical_name
    catalog.rename_product(deps.conn, product_id, name)
    return WriteResult(
        summary=f"Produto {product_id} agora é «{name}» (antes: «{before}»)",
        undo=f'julius produtos renomear {product_id} "{_quotable(before)}"',
    )


def _do_rename_store(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    cnpj, nickname = str(args["cnpj"]), str(args["nickname"])
    before = _store_now(deps.conn, cnpj).nickname
    catalog.rename_store(deps.conn, cnpj, nickname)
    return WriteResult(
        summary=f"Mercado {cnpj} agora é «{nickname}» (antes: «{before}»)",
        undo=f'julius mercados renomear {cnpj} "{_quotable(before)}"',
    )


def _do_tag_product(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    product_id, tag = int(args["product_id"]), str(args["tag"])
    product = _product_now(deps.conn, product_id)
    catalog.tag_product(deps.conn, product_id, tag)
    return WriteResult(
        summary=f"Produto {product_id} «{product.canonical_name}» marcado com «{tag}»",
        undo=f"julius produtos tag {product_id} {tag} --remover",
    )


def _do_untag_product(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    product_id, tag = int(args["product_id"]), str(args["tag"])
    product = _product_now(deps.conn, product_id)
    catalog.untag_product(deps.conn, product_id, tag)
    return WriteResult(
        summary=f"Tag «{tag}» removida do produto {product_id} «{product.canonical_name}»",
        undo=f"julius produtos tag {product_id} {tag}",
    )


_EXECUTORS = {
    "rename_product": _do_rename_product,
    "rename_store": _do_rename_store,
    "tag_product": _do_tag_product,
    "untag_product": _do_untag_product,
}


def execute(deps: Deps, pending: PendingWrite) -> WriteResult:
    """Applies a confirmed write. Reads the state as it is *now* to build the undo, not the state
    the preview described -- the user may have changed it from the CLI in between."""
    executor = _EXECUTORS.get(pending.action)
    if executor is None:
        raise WriteFailed(f"ação desconhecida: {pending.action}")
    try:
        return executor(deps, pending.args)
    except (ValueError, LookupError) as error:
        raise WriteFailed(str(error)) from None


WRITE_ACTIONS = (rename_product, rename_store, tag_product, untag_product)
