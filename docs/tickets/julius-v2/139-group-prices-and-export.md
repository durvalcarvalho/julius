# 139: Os preços do grupo, e a origem preservada no CSV

> `prices_for_products` junta os preços de todos os membros do grupo sem reatribuir uma única linha; o CSV passa a levar os dois ids.

## Contexto

`docs/design/merge-and-unit-price-v2.4.md` §2.2 (por que o `product_id` que sai é a raiz), §7.3. Requisitos RF1a/RF1c/RF8 e a questão Q10.

Depende de **137** (a view). É independente do 138 e pode ir em paralelo com ele.

## Escopo

### Dentro
- `julius/repositories/prices.py`: `prices_for_products` resolve o grupo; `export_rows` ganha `group_product_id`; **`reassign_product` é removida**.
- `julius/domain/models.py`: `PriceRecord.source_product_id`.
- `tests/test_repositories_prices.py`.

### Fora
- `catalog.merge_products`, que é a única chamadora de `reassign_product` — ela **continua compilando** porque o 140 é que a reescreve. Ver "Ponte obrigatória".
- A composição de atributos do grupo (→ 138).
- Colapso de linhas e ordenação (→ 144).

## Requisitos

### Funcionais

- `prices_for_products(conn, product_ids)`: os ids recebidos são **raízes**; a query junta `product_group` e devolve os preços de todos os membros. `PriceRecord.product_id` passa a ser `g.root_id` e `canonical_name` o nome do produto da raiz.
- `PriceRecord.source_product_id: int` — o `prices.product_id` cru da linha, que é o produto de onde o preço veio. Nenhum outro campo muda.
- `export_rows`: coluna nova `group_product_id` em `EXPORT_COLUMNS`, com o id da raiz; `product_id`/`canonical_name` continuam sendo os **do produto da linha** (a verdade histórica da compra). Produto sem fusão: `group_product_id` igual a `product_id`.
- **`reassign_product` sai**, com o seu teste. Ninguém reatribui preço neste desenho.

### Ponte obrigatória em `julius/services/catalog.py`
Remover `reassign_product` quebra `merge_products`. Troque a linha `prices.reassign_product(conn, source_id, target_id)` por `products.set_merged_into(conn, source_id, target_id)` e **remova** o `products.reassign_skus`/`delete_product` da mesma função, deixando a cópia de tags/conteúdo como está. A validação de ciclo, o `unmerge` e a limpeza final são o 140 — esta ponte só mantém a suíte verde entre tickets. Efeito colateral aceito e desejado: a fusão já passa a ser reversível aqui.

## Especificação técnica

```
modificar julius/repositories/prices.py    — prices_for_products, export_rows, EXPORT_COLUMNS; remove reassign_product
modificar julius/domain/models.py          — PriceRecord.source_product_id
modificar julius/services/catalog.py       — ponte mínima (acima)
modificar tests/test_repositories_prices.py
modificar tests/test_services_catalog.py   — os testes de merge que assumiam DELETE
modificar tests/test_repositories_prices.py — a coluna nova em EXPORT_COLUMNS
modificar tests/test_services_export.py     — a ordem das colunas do CSV
```

### Padrão a seguir
- `prices_for_products` já monta `placeholders` com `",".join("?" * len(product_ids))`; o `WHERE` passa a ser `g.root_id IN (...)`.
- `EXPORT_COLUMNS` é a fonte da ordem das colunas do CSV; acrescente `group_product_id` no fim para não mexer na ordem existente.

## Testes obrigatórios

1. `test_prices_for_products_gathers_the_whole_group` — dois produtos com preços, um fundido no outro → pedir a raiz devolve as linhas dos dois.
2. `test_prices_for_products_reports_the_root_as_product_id` — todos os records vêm com `product_id` da raiz e `source_product_id` do produto de origem.
3. `test_merging_does_not_touch_the_prices_table` — guarda o `SELECT product_id, count(*) FROM prices GROUP BY product_id` antes e depois de fundir e compara: **idêntico**. É o teste que impede alguém de reintroduzir a reatribuição por parecer mais simples.
4. `test_prices_for_products_unmerged_is_unchanged` — sem fusão, resultado igual ao de hoje (regressão).
5. `test_export_has_group_product_id` (em `tests/test_repositories_prices.py`) — produto fundido: a linha traz `product_id` do produto da compra e `group_product_id` da raiz; produto sem fusão: os dois iguais.
6. `test_export_columns_order_is_stable` — `group_product_id` é a última coluna. Os testes existentes `test_export_rows_has_exact_columns_in_order_and_is_sorted` e `test_export_columns_in_exact_order` **mudam de expectativa** (a lista de colunas cresceu).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -rn "reassign_product" julius tests` **vazio**.
- [ ] `tests/test_architecture.py` verde sem edição.
- [ ] Nenhum `UPDATE prices` novo em nenhum lugar: `grep -rn "UPDATE prices" julius` só encontra o que já existia (nada).

## Notas para o agente

- `PriceRecord.product_id` **tem** de ser a raiz: `domain/comparison_basis.py` decide "série temporal × comparação entre embalagens" por `len({record.product_id})`. Deixar o id de origem faria dois preços do mesmo produto fundido parecerem produtos diferentes, trocando a base — o erro que a v2.2 consertou. Não toque em `comparison_basis`; se ele precisar mudar, o desenho está errado.
- Acrescente `source_product_id` com default, para não quebrar as construções posicionais de `PriceRecord` nos testes.
