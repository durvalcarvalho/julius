# 004: Repositório prices

> Inserção idempotente de itens de recibo, leitura para consulta e para export, e reatribuição de produto (usada pela fusão).

## Contexto

Camada `repositories` (L2), tabela `prices` — o registro imutável de "paguei X por Y em Z". Chave `(access_key, item_index)`. Leia no `CLAUDE.md`: "Armazenamento", "Preço por conteúdo", "Estrutura de pacote".

Depende de 002 (`ensure_store`) e 003 (`resolve_product_id`) para montar cenários nos testes. Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/repositories/prices.py` e `tests/test_repositories_prices.py`.

### Fora
- Decidir `highlight` (menor/maior) → 006. Ler/parsear arquivos → 005. Escrever CSV → 008 (aqui só a query em forma de dicionários).

## Requisitos

### Funcionais
- `insert_price(conn, receipt: Receipt, item: ReceiptItem, product_id: int) -> bool` — `INSERT OR IGNORE` mapeando `receipt.access_key`, `item.index`, `receipt.issued_at`, `receipt.store_cnpj`, `product_id`, `item.product_code`, `item.description`, `item.quantity`, `item.unit`, `item.unit_price`, `item.total_price`. Retorna `True` se inseriu, `False` se já existia (`rowcount`).
- `prices_for_products(conn, product_ids: Sequence[int]) -> list[PriceRecord]` — `JOIN stores` (nickname) e `JOIN products` (canonical_name, conteúdo). `price_per_content = unit_price / content_quantity` quando `content_quantity` não é `NULL`, senão `None` (aritmética derivada, não é regra — a regra de destaque fica no serviço). `highlight=None` sempre. Ordenado por `purchased_at DESC`, depois `unit_price`. Lista vazia de ids → lista vazia, sem erro.
- `export_rows(conn) -> list[dict[str, object]]` — uma linha por preço, chaves exatamente nesta ordem: `purchased_at, store_cnpj, store_nickname, product_id, canonical_name, product_code, description, quantity, unit, unit_price, total_price, access_key, item_index`. Ordenado por `purchased_at, access_key, item_index`.
- `reassign_product(conn, source_id: int, target_id: int) -> None` — `UPDATE prices SET product_id`.
- `count(conn) -> int`.

### Validação e erros
- FK inválida (loja ou produto inexistente) → deixar o `sqlite3.IntegrityError` propagar; nunca engolir.

## Especificação técnica

```
criar julius/repositories/prices.py
criar tests/test_repositories_prices.py
```

Nos testes, construa `Receipt`/`ReceiptItem` à mão (dataclasses de `julius/domain/models.py`) — não use o parser aqui; o repositório deve ser testável sem HTML.

## Testes obrigatórios

1. `test_insert_price_returns_true_then_false_for_same_receipt_line`
2. `test_repeated_code_in_same_receipt_are_separate_rows` — mesmo `product_code`, `index` 1 e 2 → 2 linhas.
3. `test_insert_price_with_unknown_store_raises_integrity_error`
4. `test_prices_for_products_joins_nickname_and_name`
5. `test_prices_for_products_orders_newest_first`
6. `test_price_per_content_is_none_without_content_and_computed_with_it` — sem conteúdo → `None`; após `set_content(… 2.0, "L")` e `unit_price 6.99` → `3.495`.
7. `test_prices_for_products_empty_ids_returns_empty`
8. `test_export_rows_has_exact_columns_in_order_and_is_sorted`
9. `test_reassign_product_moves_rows_and_leaves_others`
10. `test_count`

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] Módulo importa só `sqlite3`, `collections.abc`/`typing` e `julius.domain.models`.

## Notas para o agente
- `PriceRecord.unit` deve sair como `str` `"UN"`/`"KG"` direto da coluna; não reaplicar normalização aqui.
- Não adicione índices ao schema neste ticket; se a query pedir, anote no ticket como sugestão para uma migração futura.
