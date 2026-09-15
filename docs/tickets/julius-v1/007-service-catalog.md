# 007: Serviço catalog

> Manutenção manual do catálogo: renomear loja/produto, fundir produtos, marcar tag, definir conteúdo da embalagem — com validação e transação.

## Contexto

Tudo o que o design decidiu que o usuário faz **à mão** (nunca automático) passa por aqui. Leia no `CLAUDE.md`: "Identidade de produto e busca § 1 e § 3", "Preço por conteúdo", "Decisões § 2".

Depende de 002, 003, 004. Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/services/catalog.py` e `tests/test_services_catalog.py`.

### Fora
- `compare_products` → 013. Comandos de CLI → 010. Qualquer sugestão automática.

## Requisitos

### Funcionais (todas recebem `conn` primeiro)
- `list_stores(conn) -> list[Store]` · `list_products(conn) -> list[Product]` — repasse direto.
- `rename_store(conn, cnpj: str, nickname: str) -> None` — `nickname.strip()`; vazio → `ValueError`; repassa `LookupError` do repositório.
- `rename_product(conn, product_id: int, name: str) -> None` — idem para `name`.
- `merge_products(conn, source_id: int, target_id: int) -> None` — `source_id == target_id` → `ValueError`; qualquer um inexistente → `LookupError`; numa única transação (`with conn:`): `products.reassign_skus`, `prices.reassign_product`, tags do `source` copiadas para o `target` (via `add_tag`, idempotente), `products.delete_product(source)`. Conteúdo do `target` é preservado; se `target` não tem conteúdo e `source` tem, copia.
- `tag_product(conn, product_id: int, tag: str) -> None` — normaliza `tag.strip().lower()`; vazio → `ValueError`.
- `set_product_content(conn, product_id: int, quantity: float, raw_unit: str) -> None` — `normalize_content(quantity, raw_unit)` (já valida positivo/unidade) e `products.set_content`.

### Validação e erros
- `ValueError` para entrada inválida; `LookupError` para id/cnpj inexistente. Nenhuma exceção própria nova.

## Especificação técnica

```
criar julius/services/catalog.py
criar tests/test_services_catalog.py
```

Imports: `sqlite3`, `julius.domain.*`, `julius.repositories.{stores,products,prices}`.

## Testes obrigatórios

1. `test_rename_store_strips_and_saves` · `test_rename_store_blank_raises_value_error` · `test_rename_store_unknown_raises_lookup_error`
2. `test_rename_product_and_errors` (mesmos três casos)
3. `test_merge_moves_skus_prices_and_tags_then_deletes_source` — cenário real: `qrcode.html` + `qrcode-3.html`, fundir os dois "TOMATE ITALIANO" → `search_prices("tomate")` (006) devolve um só `product_id`; `products` tem uma linha a menos; `prices.count` inalterado.
4. `test_merge_same_id_raises_value_error`
5. `test_merge_unknown_id_raises_lookup_error_and_changes_nothing`
6. `test_merge_copies_content_when_target_has_none`
7. `test_tag_product_normalizes_case_and_whitespace` — `" Limpeza "` e `"limpeza"` → uma tag.
8. `test_tag_product_blank_raises`
9. `test_set_product_content_normalizes_grams_to_kilograms` — `(500, "G")` → `content_quantity == 0.5`, `content_unit == "KG"`.
10. `test_set_product_content_rejects_bad_unit_and_non_positive`

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `merge_products` é atômico: teste 5 prova que uma falha no meio não deixa SKU já movido.

## Notas para o agente
- Para provar atomicidade, use `target_id` inexistente com `source_id` válido: a checagem de existência deve vir **antes** de qualquer `UPDATE`, ou o rollback do `with conn:` deve desfazer.
- Não adicione `unmerge`; irreversibilidade é aceita (há backup do banco em migração, e o usuário tem `sqlite3` na mão).
