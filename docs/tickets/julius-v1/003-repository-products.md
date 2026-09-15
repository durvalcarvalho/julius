# 003: Repositório products

> Persistência do agregado **Product**: resolução SKU→produto, tags, conteúdo, e as primitivas que a fusão de produtos usa.

## Contexto

Camada `repositories` (L2). Tabelas `products`, `product_skus`, `tags`, `product_tags` (schema em `julius/infra/migrations/0001_initial_schema.sql`). Leia no `CLAUDE.md`: "Identidade de produto e busca" (por que `(store_cnpj, product_code)` é a chave e por que nunca se funde automaticamente), "Preço por conteúdo", "Estrutura de pacote".

Sem dependência de outro ticket (testes inserem a loja com SQL direto ou via `ensure_store` se 002 já existir). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/repositories/products.py` e `tests/test_repositories_products.py`.

### Fora
- Fusão como operação completa (transação + reatribuir `prices`) → 007; aqui só as primitivas. Normalizar tag (`lower/strip`) e conteúdo (`G→KG`) → 007. Fuzzy search → 006. Tocar em `prices`.

## Requisitos

### Funcionais
- `resolve_product_id(conn, store_cnpj: str, product_code: str, description: str) -> int` — se `(store_cnpj, product_code)` existe em `product_skus`, devolve o `product_id`; senão cria `products(canonical_name=description)` e o SKU, devolve o novo id. **Nunca** cria um segundo produto para um SKU já visto, mesmo que a `description` tenha mudado.
- `get_product(conn, product_id: int) -> Product | None` — inclui `tags` como tupla ordenada.
- `list_products(conn) -> list[Product]` — ordenado por `canonical_name`, com tags.
- `product_names(conn) -> list[tuple[int, str]]` — `(id, canonical_name)` para o fuzzy search.
- `rename_product(conn, product_id, name) -> None` — `LookupError` se não existe.
- `set_content(conn, product_id, quantity: float, unit: ContentUnit) -> None` — grava como recebido (já normalizado); `LookupError` se não existe.
- `add_tag(conn, product_id, tag_name) -> None` — `INSERT OR IGNORE` em `tags`, depois em `product_tags`; idempotente; `LookupError` se produto não existe.
- `product_ids_with_tag(conn, tag_name) -> list[int]` — vazio se a tag não existe.
- `all_tag_names(conn) -> list[str]` — ordenado.
- `reassign_skus(conn, source_id, target_id) -> None` e `delete_product(conn, product_id) -> None` (apaga `product_tags` do produto e depois o produto). Se ainda houver `prices`/`product_skus` apontando para ele, o `IntegrityError` do SQLite deve **propagar** — é a FK protegendo.

### Validação e erros
- `LookupError` para produto inexistente nas operações de escrita. Nada mais; validação de texto é do serviço.

## Especificação técnica

```
criar julius/repositories/products.py
criar tests/test_repositories_products.py
```

Sem `commit` dentro das funções. `Product.tags` é `tuple[str, ...]` (dataclass frozen).

## Testes obrigatórios

1. `test_resolve_creates_product_and_sku_on_first_sight`
2. `test_resolve_reuses_product_for_known_sku_even_if_description_changed`
3. `test_same_code_in_different_stores_are_different_products` — cód. `4134` em duas lojas → dois ids (caso real: desengordurante × brócolis).
4. `test_get_product_includes_sorted_tags`
5. `test_get_product_missing_returns_none`
6. `test_list_products_sorted_by_name`
7. `test_rename_product_and_missing_raises`
8. `test_set_content_and_missing_raises`
9. `test_add_tag_is_idempotent_and_reuses_tag_row` — duas chamadas iguais → 1 linha em `tags`, 1 em `product_tags`.
10. `test_product_ids_with_tag_and_unknown_tag_returns_empty`
11. `test_reassign_skus_moves_all_skus`
12. `test_delete_product_removes_tags_and_fails_if_still_referenced` — com SKU ainda apontando → `sqlite3.IntegrityError`; após `reassign_skus` → apaga.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] Módulo importa só `sqlite3` e `julius.domain.models`.

## Notas para o agente
- Para inserir uma loja nos testes use `ensure_store` de 002 se já existir; senão `INSERT INTO stores VALUES (?, ?, ?)` direto — não crie helper extra.
- `INSERT ... RETURNING` exige SQLite ≥ 3.35; prefira `cursor.lastrowid` para portabilidade.
