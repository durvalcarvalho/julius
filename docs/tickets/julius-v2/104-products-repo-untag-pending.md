# 104: Repositório `products` — remover tag, pendentes e nome cru

> Três funções pequenas que a curadoria automática exige: desfazer tag, listar produtos sem tag e saber se um produto ainda tem o nome cru do cupom. Mais `catalog.untag_product`.

## Contexto

Princípio revisado do design (`docs/design/ai-v2.md` §2 dos requisitos, §4.6/§4.8 do design): a IA só grava o que é **reversível por comando**. Hoje não existe como remover uma tag pelo CLI (só `sqlite3`), então nenhuma tag pode ser aplicada automaticamente antes deste ticket. `has_raw_name` protege renomes manuais do usuário de serem sobrescritos pela IA.

Sem dependências. Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/repositories/products.py`: `remove_tag`, `untagged_product_ids`, `has_raw_name`.
- `julius/services/catalog.py`: `untag_product(conn, product_id, tag) -> None`.
- `tests/test_repositories_products.py`, `tests/test_services_catalog.py`.

### Fora
- Comando `--remover` na CLI (→ 111). Apagar linhas de `tags` sem uso. Qualquer coisa de IA.

## Requisitos

### Funcionais
- `remove_tag(conn, product_id, tag_name)`: `_require_exists`; `DELETE FROM product_tags WHERE product_id = ? AND tag_id = (SELECT id FROM tags WHERE name = ?)`; `rowcount == 0` → `LookupError(f"product {product_id} has no tag {tag_name!r}")`. A linha em `tags` **fica** (pode ser categoria semeada ou usada por outro produto).
- `untagged_product_ids(conn) -> list[int]`: `SELECT id FROM products WHERE id NOT IN (SELECT product_id FROM product_tags) ORDER BY id`.
- `has_raw_name(conn, product_id) -> bool`: `True` se existe linha em `prices` daquele produto com `description == products.canonical_name` (comparação exata). Produto sem nenhum preço → `False` (conservador: sem prova de que o nome é cru, não renomear).
- `catalog.untag_product(conn, product_id, tag)`: `with conn: products.remove_tag(conn, product_id, _non_blank(tag, "tag").lower())`.

### Validação e erros
- `remove_tag` em produto inexistente → `LookupError` (via `_require_exists`).
- `untag_product` com tag em branco → `ValueError` (via `_non_blank`).

## Especificação técnica

```
modificar julius/repositories/products.py
modificar julius/services/catalog.py
modificar tests/test_repositories_products.py
modificar tests/test_services_catalog.py
```

## Testes obrigatórios

1. `test_remove_tag_deletes_link_but_keeps_tag_row`
2. `test_remove_tag_unknown_product_or_missing_link_raises_lookup_error` (parametrizado nos dois casos)
3. `test_untagged_product_ids_lists_only_products_without_tags_in_id_order` — 3 produtos, 1 com tag.
4. `test_has_raw_name_true_after_import_false_after_rename` — importe `qrcode-2.html` (1 item), `has_raw_name` é `True`; `rename_product` → `False`.
5. `test_has_raw_name_false_for_product_without_prices` — produto inserido direto em `products`.
6. `test_services_catalog.py::test_untag_product_normalizes_and_removes` — `" Limpeza "` remove `limpeza`.
7. `test_untag_product_blank_tag_raises_value_error`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `tests/test_architecture.py` verde (nada novo importado fora da camada).

## Notas para o agente
- Não adicione coluna `renamed_by_user`/`name_source`: `has_raw_name` resolve sem schema, que é o objetivo.
