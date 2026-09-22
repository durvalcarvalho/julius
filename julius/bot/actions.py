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
from datetime import datetime, timezone

from pydantic_ai import ModelRetry, RunContext

from julius.config import Config
from julius.domain.models import PriceCheck, Product, SaleUnit, SearchOutcome, ShoppingVerdict, Store, StoreComparison
from julius.domain.formatting import content_text
from julius.domain.normalization import digits_only, normalize_content, normalize_text
from julius.infra import ai_log
from julius.infra.llm_client import LlmClient
from julius.services import catalog, comparison as comparison_service, search as search_service

MAX_CANDIDATES = 8  # what fits in a question to the user without becoming a listing


@dataclass(frozen=True)
class Deps:
    conn: sqlite3.Connection
    config: Config
    # For turn.py's narrate() calls (voz do Julius, ticket 166) -- None means "answer without the
    # persona", same as IA not being configured at all.
    client: LlmClient | None = None
    # docs/design/bot-read-only-tier.md: só o papel, não a lista que o calcula -- app.py decide
    # *como* alguém vira confiável, esta camada só precisa saber *se*. Defaults preservam todo
    # teste/chamador existente (o caminho "dono").
    can_write: bool = True
    chat_id: int | None = None


@dataclass(frozen=True)
class ProductListing:
    """An empty `products` means "the catalogue has none", which a bare empty list cannot say."""

    products: tuple[Product, ...]
    containing: str | None = None


@dataclass(frozen=True)
class StoreListing:
    stores: tuple[Store, ...]


@dataclass(frozen=True)
class ShoppingComparison:
    """The scoped, item-by-item answer to "which market is cheaper" -- unlike bare
    StoreComparison (every kind ever bought), this always carries what the person actually asked
    to compare, plus what could not be matched, so nothing goes silently missing.

    `single_store_kinds` is the bucket `unmatched_terms` used to hide (docs/design/
    shopping-verdict-shape.md, Decisão 2): a term that DID match a known `kind`, but that kind has
    price registered in only one market -- `comparison_service.compare_stores` drops it silently,
    so this is the only place that still knows it existed. `requested_count` is `len(terms)`
    before any matching, so the reply can say how much of the original list this covers."""

    comparison: StoreComparison
    verdict: ShoppingVerdict | None
    unmatched_terms: tuple[str, ...]
    single_store_kinds: tuple[str, ...] = ()
    requested_count: int = 0


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


def _resolve_kind(conn: sqlite3.Connection, item: str) -> str | None:
    """Like `resolve_product`/`resolve_store`, but for `kind`: returns the resolved type, `None`
    for today's "not recognized" behavior, or raises `ModelRetry` when `match_kind` refused with
    concrete candidates to offer (a brand matching two real products that disagree on kind) --
    never picks between them on its own (docs/design/kind-resolution-in-routing.md, Decisão 3)."""
    kind = search_service.match_kind(conn, item)
    if kind is not None:
        return kind
    candidates = search_service.kind_candidates(conn, item)
    if candidates:
        raise ModelRetry(
            f"Mais de um tipo combina com «{item}»: {', '.join(candidates)}. "
            "Pergunte à pessoa qual, e chame de novo com o tipo escolhido."
        )
    return None


async def search_prices(
    ctx: RunContext[Deps], words: str, tag: str | None = None, limit: int = 20, note: str | None = None
) -> SearchOutcome:
    """Busca no histórico de preços já pagos, por nome de produto e/ou categoria.

    Args:
        words: palavras do nome do produto, como o usuário falou (ex.: "picanha", "leite"). Pode
            ficar vazio quando `tag` for informada.
        tag: categoria para filtrar (ex.: "hortifruti", "limpeza"). Use apenas quando o usuário
            pedir uma categoria inteira.
        limit: quantas linhas no máximo por unidade de venda. O padrão, 20, serve quase sempre.
        note: se o pedido original tinha mais de uma parte (ex.: "quanto paguei de tomate E qual
            mercado é mais barato pra cebola?"), diga aqui, em texto curto, que a outra parte vem
            na próxima mensagem (ex.: "cebola eu comparo a seguir"). Deixe de fora quando o pedido
            só tinha uma parte -- texto livre não pode conviver com a chamada desta ação no mesmo
            turno, então é este o único jeito de avisar sobre a segunda parte.
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


async def compare_stores(
    ctx: RunContext[Deps], items: tuple[str, ...], note: str | None = None
) -> ShoppingComparison:
    """Compara o preço dos mesmos tipos de produto entre os mercados, para dizer qual mercado sai
    mais barato para uma lista de compras.

    NUNCA chame com uma lista vazia: se a pessoa não disse o que quer comprar (nem nesta mensagem
    nem nas anteriores da conversa), pergunte em texto o que ela quer comprar em vez de chamar esta
    ação.

    Args:
        items: os itens que a pessoa quer comprar, como ela falou (ex.: ("tomate", "leite")).
            Junte itens mencionados nas últimas mensagens da conversa, não só na mais recente.
        note: se o pedido original tinha mais de uma parte, diga aqui, em texto curto, que a outra
            parte vem na próxima mensagem. Deixe de fora quando o pedido só tinha uma parte.
    """
    terms = [item.strip() for item in items if item.strip()]
    if not terms:
        raise ModelRetry("Informe pelo menos um item para comparar.")
    matched: list[str] = []
    unmatched: list[str] = []
    for term in terms:
        kind = _resolve_kind(ctx.deps.conn, term)
        if kind is None:
            unmatched.append(term)
        elif kind not in matched:
            matched.append(kind)
    comparison = comparison_service.compare_stores(ctx.deps.conn, kinds=matched) if matched else StoreComparison((), "", "")
    compared_kinds = {group.kind for group in comparison.comparisons}
    single_store_kinds = tuple(kind for kind in matched if kind not in compared_kinds)
    category_of = catalog.kind_categories(ctx.deps.conn)
    verdict = comparison_service.shopping_verdict(comparison, category_of=category_of) if comparison.comparisons else None
    ai_log.append(
        ctx.deps.config.query_log_path,
        {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "channel": "bot",
            "action": "compare_stores",
            "items": terms,
            "matched_kinds": matched,
            "unmatched_terms": unmatched,
            "single_store_kinds": list(single_store_kinds),
        },
    )
    return ShoppingComparison(
        comparison=comparison,
        verdict=verdict,
        unmatched_terms=tuple(unmatched),
        single_store_kinds=single_store_kinds,
        requested_count=len(terms),
    )


async def check_price(
    ctx: RunContext[Deps],
    item: str,
    price: float,
    quantity: float | None = None,
    unit: SaleUnit | None = None,
    note: str | None = None,
) -> PriceCheck:
    """Confere se um preço que a pessoa está vendo agora no mercado é bom, comparado ao histórico.

    Use SÓ quando a pessoa informar um valor que ela mesma está vendo (ex.: "os ovos tão a 14
    reais, tá bom?", "aqui o quilo do tomate tá 9,90"). NUNCA para "está caro?" sem nenhum preço
    dito -- isso continua indo para search_prices, sem veredito.

    NUNCA informe `quantity` nesta primeira chamada, mesmo que pareça razoável assumir "1" --
    deixe de fora e deixe esta ação decidir se precisa perguntar. Exemplo: "a picanha tá 60 reais
    o quilo, compro?" -> chame check_price(item="picanha", price=60), SEM quantity. Só informe
    quantity quando a pessoa já tiver dito quanto vai levar, ou ao responder a uma pergunta que uma
    chamada anterior sua já fez.

    Se o resultado vier com reason="quantity_needed", pergunte à pessoa quanto ela pretende
    comprar (na mesma unidade que reference_unit já diz) e chame esta ação de novo, com os mesmos
    item/price mais quantity. Se ela não responder de forma útil depois de perguntar de novo uma
    vez, chame de novo com uma quantidade pequena (ex.: 1) em vez de insistir -- nunca deixe a
    conversa travada numa pergunta sem resposta.

    Se o resultado vier com reason="ambiguous_unit", pergunte se o preço é por peso (quilo) ou por
    unidade, e chame de novo com o mesmo item/price mais unit="KG" ou unit="UN" conforme a
    resposta.

    Args:
        item: o produto, como a pessoa falou (ex.: "ovos").
        price: o valor que ela informou, em reais.
        quantity: quanto ela pretende comprar, na mesma unidade que reference_unit de uma resposta
            anterior. Só informe quando ela já disse isso, ou ao responder à pergunta que uma
            chamada anterior devolveu. NUNCA chute um valor.
        unit: "KG" ou "UN", só ao responder à pergunta que uma chamada anterior fez por causa de
            reason="ambiguous_unit". Nunca informe por conta própria.
        note: se o pedido original tinha mais de uma parte, diga aqui, em texto curto, que a outra
            parte vem na próxima mensagem. Deixe de fora quando o pedido só tinha uma parte.
    """
    if price <= 0:
        raise ModelRetry(f"O preço precisa ser maior que zero, recebi {price:g}. Confirme com a pessoa.")
    if quantity is not None and quantity <= 0:
        raise ModelRetry(f"A quantidade precisa ser maior que zero, recebi {quantity:g}.")
    kind = _resolve_kind(ctx.deps.conn, item)
    if kind is None:
        return PriceCheck(
            kind=None, verdict=None, informed_price=price, reference_price=None, reference_unit=None,
            reference_store=None, reference_at=None, diff_pct=None, reason="unknown_item",
        )
    return comparison_service.check_price(ctx.deps.conn, kind, price, quantity, unit)


async def list_products(
    ctx: RunContext[Deps], containing: str | None = None, note: str | None = None
) -> ProductListing:
    """Lista os produtos do catálogo, com id, tipo, conteúdo e categorias.

    Args:
        containing: filtra pelos produtos cujo nome contém este trecho. Use quando o catálogo for
            grande e o usuário estiver procurando um produto específico.
        note: se o pedido original tinha mais de uma parte, diga aqui, em texto curto, que a outra
            parte vem na próxima mensagem. Deixe de fora quando o pedido só tinha uma parte.
    """
    products = catalog.list_products(ctx.deps.conn)
    if containing:
        needle = normalize_text(containing)
        products = [product for product in products if needle in normalize_text(product.canonical_name)]
    return ProductListing(products=tuple(products), containing=containing)


async def list_stores(ctx: RunContext[Deps], note: str | None = None) -> StoreListing:
    """Lista os mercados já importados, com CNPJ, apelido e bairro.

    Args:
        note: se o pedido original tinha mais de uma parte, diga aqui, em texto curto, que a outra
            parte vem na próxima mensagem. Deixe de fora quando o pedido só tinha uma parte.
    """
    return StoreListing(stores=tuple(catalog.list_stores(ctx.deps.conn)))


READ_ACTIONS = (search_prices, compare_stores, list_products, list_stores, check_price)


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


async def set_product_kind(ctx: RunContext[Deps], product: str, kind: str) -> PendingWrite:
    """Define o tipo do produto — o grupo pelo qual preços são comparados entre mercados.

    O tipo diz "que coisa é esta" (tomate, leite uht, refrigerante). Marca, sabor e tamanho não
    entram: dois produtos do mesmo tipo têm de ser alternativas de compra um do outro.

    Args:
        product: o produto, pelo id ou pelo nome.
        kind: o tipo, em minúsculas e no singular (ex.: "tomate", "leite uht").
    """
    kind = _required(kind, "O tipo")
    found = resolve_product(ctx.deps.conn, product)
    previous = f" (antes: «{found.kind}»)" if found.kind else ""
    return _pending(
        "set_product_kind",
        {"product_id": found.id, "kind": kind},
        f"Definir o tipo do produto {found.id} «{found.canonical_name}» como «{kind}»{previous}",
    )


async def clear_product_kind(ctx: RunContext[Deps], product: str) -> PendingWrite:
    """Remove o tipo de um produto, tirando-o da comparação entre mercados.

    Args:
        product: o produto, pelo id ou pelo nome.
    """
    found = resolve_product(ctx.deps.conn, product)
    if not found.kind:
        raise ModelRetry(f"O produto {found.id} não tem tipo.")
    return _pending(
        "clear_product_kind",
        {"product_id": found.id},
        f"Remover o tipo «{found.kind}» do produto {found.id} «{found.canonical_name}»",
    )


def _content_of(product: Product) -> str | None:
    if product.content_quantity is None or not product.content_unit:
        return None
    return content_text(product.content_quantity, product.content_unit)


async def set_product_content(ctx: RunContext[Deps], product: str, quantity: float, unit: str) -> PendingWrite:
    """Define o conteúdo da embalagem, que é o que permite comparar tamanhos diferentes.

    Sem isso não dá para dizer se 20 ovos por R$12 é melhor que 30 por R$16,50. Informe o conteúdo
    TOTAL da embalagem.

    Args:
        product: o produto, pelo id ou pelo nome.
        quantity: a quantidade (ex.: 500 para "500 g", 1.5 para "1,5 L", 30 para "30 unidades").
        unit: a unidade como está no rótulo: L, ML, KG, G ou UN.
    """
    found = resolve_product(ctx.deps.conn, product)
    try:
        normalized_quantity, normalized_unit = normalize_content(quantity, unit)
    except ValueError:
        if quantity <= 0:
            raise ModelRetry(f"A quantidade precisa ser maior que zero, recebi {quantity:g}.") from None
        raise ModelRetry(f"Unidade «{unit}» inválida; aceitas: L, ML, KG, G, UN.") from None
    current = _content_of(found)
    previous = f" (antes: {current})" if current else ""
    return _pending(
        "set_product_content",
        {"product_id": found.id, "quantity": normalized_quantity, "unit": normalized_unit},
        f"Definir o conteúdo do produto {found.id} «{found.canonical_name}» como "
        f"{content_text(normalized_quantity, normalized_unit)}{previous}",
    )


async def clear_product_content(ctx: RunContext[Deps], product: str) -> PendingWrite:
    """Remove o conteúdo declarado de um produto.

    Args:
        product: o produto, pelo id ou pelo nome.
    """
    found = resolve_product(ctx.deps.conn, product)
    current = _content_of(found)
    if current is None:
        raise ModelRetry(f"O produto {found.id} não tem conteúdo definido.")
    return _pending(
        "clear_product_content",
        {"product_id": found.id},
        f"Remover o conteúdo {current} do produto {found.id} «{found.canonical_name}»",
    )


async def merge_products(ctx: RunContext[Deps], source: str, target: str) -> PendingWrite:
    """Diz que dois produtos são a mesma coisa, juntando o histórico de preço dos dois.

    É reversível: nada é apagado, e unmerge_product devolve o estado anterior. Use quando o mesmo
    item aparece com descrições diferentes em mercados diferentes.

    Args:
        source: o produto que será absorvido, pelo id ou pelo nome.
        target: o produto que passa a representar os dois, pelo id ou pelo nome.
    """
    absorbed = resolve_product(ctx.deps.conn, source)
    kept = resolve_product(ctx.deps.conn, target)
    if absorbed.id == kept.id:
        raise ModelRetry("Origem e destino são o mesmo produto.")
    preview = (
        f"Fundir o produto {absorbed.id} «{absorbed.canonical_name}» dentro de "
        f"{kept.id} «{kept.canonical_name}»: o histórico dos dois passa a aparecer junto"
    )
    inheritance = catalog.merge_inheritance(ctx.deps.conn, absorbed.id, kept.id)
    if inheritance is not None:
        what, where = inheritance
        preview += f"; o grupo herda {what} de {where}"
    return _pending("merge_products", {"source_id": absorbed.id, "target_id": kept.id}, preview)


async def unmerge_product(ctx: RunContext[Deps], product: str) -> PendingWrite:
    """Desfaz uma fusão, separando de novo um produto que foi fundido dentro de outro.

    Informe o id, não o nome: um produto absorvido não aparece nas listagens com o nome dele — o
    grupo mostra um nome só — então procurá-lo por nome encontra o grupo, não ele.

    Args:
        product: o id do produto ABSORVIDO (o que foi fundido dentro de outro).
    """
    reference = product.strip()
    group = resolve_product(ctx.deps.conn, reference)
    # Asking the id and comparing is how "is this one absorbed?" is answered without a repository:
    # reading any product resolves to its group's root, so getting a different id back IS the
    # merge. `Product.merged_into` never arrives filled through services.
    if not reference.isdigit() or int(reference) == group.id:
        raise ModelRetry(
            f"O produto {group.id} não está fundido. Se quiser desfundir outro, informe o id do "
            "produto absorvido, que list_products mostra dentro do grupo."
        )
    return _pending(
        "unmerge_product",
        {"product_id": int(reference)},
        f"Desfundir o produto {reference} do grupo {group.id} «{group.canonical_name}»",
    )


def _do_set_product_kind(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    product_id, kind = int(args["product_id"]), str(args["kind"])
    before = _product_now(deps.conn, product_id).kind
    catalog.set_product_kind(deps.conn, product_id, kind)
    undo = (
        f'julius produtos tipo {product_id} "{_quotable(before)}"'
        if before
        else f"julius produtos tipo {product_id} --remover"
    )
    tail = f" (antes: «{before}»)" if before else ""
    return WriteResult(summary=f"Produto {product_id} agora é do tipo «{kind}»{tail}", undo=undo)


def _do_clear_product_kind(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    product_id = int(args["product_id"])
    before = _product_now(deps.conn, product_id).kind
    catalog.clear_product_kind(deps.conn, product_id)
    return WriteResult(
        summary=f"Produto {product_id} ficou sem tipo (antes: «{before}»)",
        undo=f'julius produtos tipo {product_id} "{_quotable(before or "")}"',
    )


def _do_set_product_content(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    product_id = int(args["product_id"])
    quantity, unit = float(args["quantity"]), str(args["unit"])
    before = _product_now(deps.conn, product_id)
    catalog.set_product_content(deps.conn, product_id, quantity, unit)
    undo = (
        f"julius produtos definir-conteudo {product_id} {before.content_quantity:g} {before.content_unit}"
        if before.content_quantity is not None and before.content_unit
        else f"julius produtos definir-conteudo {product_id} --remover"
    )
    previous = _content_of(before)
    tail = f" (antes: {previous})" if previous else ""
    return WriteResult(
        summary=f"Produto {product_id} agora tem {content_text(quantity, unit)}{tail}",
        undo=undo,
    )


def _do_clear_product_content(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    product_id = int(args["product_id"])
    before = _product_now(deps.conn, product_id)
    catalog.clear_product_content(deps.conn, product_id)
    return WriteResult(
        summary=f"Produto {product_id} ficou sem conteúdo (antes: {_content_of(before)})",
        undo=f"julius produtos definir-conteudo {product_id} {before.content_quantity:g} {before.content_unit}",
    )


def _do_merge_products(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    source_id, target_id = int(args["source_id"]), int(args["target_id"])
    source = _product_now(deps.conn, source_id)
    target = _product_now(deps.conn, target_id)
    catalog.merge_products(deps.conn, source_id, target_id)
    return WriteResult(
        summary=f"Produto {source_id} «{source.canonical_name}» fundido dentro de {target_id} «{target.canonical_name}»",
        undo=f"julius produtos desfundir {source_id}",
    )


def _do_unmerge_product(deps: Deps, args: Mapping[str, object]) -> WriteResult:
    product_id = int(args["product_id"])
    group = _product_now(deps.conn, product_id)
    catalog.unmerge_product(deps.conn, product_id)
    separated = _product_now(deps.conn, product_id)
    # ponytail: the undo re-merges into the group ROOT, which is the direct parent for every merge
    # this system creates in one step. In a hand-built chain A->B->C it would put A under C instead
    # of B -- same group, so nothing visible changes, but a later unmerge of B would not carry A
    # out. Exact reversal needs the direct parent, and no service exposes it; add one to catalog if
    # chains ever appear.
    return WriteResult(
        summary=f"Produto {product_id} «{separated.canonical_name}» separado do grupo {group.id} «{group.canonical_name}»",
        undo=f"julius produtos fundir {product_id} {group.id}",
    )


_EXECUTORS = {
    "rename_product": _do_rename_product,
    "rename_store": _do_rename_store,
    "tag_product": _do_tag_product,
    "untag_product": _do_untag_product,
    "set_product_kind": _do_set_product_kind,
    "clear_product_kind": _do_clear_product_kind,
    "set_product_content": _do_set_product_content,
    "clear_product_content": _do_clear_product_content,
    "merge_products": _do_merge_products,
    "unmerge_product": _do_unmerge_product,
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


WRITE_ACTIONS = (
    rename_product,
    rename_store,
    tag_product,
    untag_product,
    set_product_kind,
    clear_product_kind,
    set_product_content,
    clear_product_content,
    merge_products,
    unmerge_product,
)

ALL_ACTIONS = READ_ACTIONS + WRITE_ACTIONS
