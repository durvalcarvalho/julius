# 137: Migração 0004 — `products.merged_into` e a view do grupo

> A coluna que torna a fusão reversível e a view que resolve o grupo. Ninguém as consome ainda.

## Contexto

`docs/design/merge-and-unit-price-v2.4.md` §1 (o schema), §2.3 (o que foi medido). Requisitos RF1a/RF1b/RF1g de `docs/requirements/auto-merge-and-unit-price-v2.4.md`.

Hoje `catalog.merge_products` reatribui SKUs e preços e **apaga** a linha de origem — não existe como desfazer. Este ticket cria só o schema e as três leituras cruas; quem funde continua sendo o código antigo (muda no 140).

## Escopo

### Dentro
- `julius/infra/migrations/0004_product_merge.sql`.
- `julius/repositories/products.py`: `set_merged_into`, `group_root`, `group_members`.
- `tests/test_db.py` (a migração), `tests/test_repositories_products.py`.

### Fora
- Mudar qualquer leitura existente (→ 138, 139). `get_product`/`list_products` continuam como estão.
- `catalog.merge_products`, a guarda de ciclo e o `unmerge` (→ 140).
- Índice em `merged_into`: são 105 linhas e a resolução custa 0,035 ms (design §2.3).
- `CHECK` de coluna contra auto-referência: não vê ciclo de dois passos, e a guarda é na escrita (→ 140).

## Requisitos

### Funcionais

- A migração é exatamente o SQL do design §1: a coluna `merged_into INTEGER REFERENCES products(id)` e a view `product_group` com a CTE recursiva. **Copie o SQL verbatim** — ele foi executado contra uma cópia do banco real.
- `set_merged_into(conn, product_id: int, target_id: int | None) -> None` — grava ou limpa a relação. `LookupError` se `product_id` não existe. **Nenhuma validação de ciclo aqui**: é regra de domínio e mora em `catalog` (140); este é o escritor cru.
- `group_root(conn, product_id: int) -> int` — a raiz do grupo, pela view. Produto não fundido é raiz de si mesmo. Produto inexistente → `LookupError`.
- `group_members(conn, root_id: int) -> list[int]` — a raiz e todos os absorvidos, ordenados por id (a raiz não é necessariamente a primeira; ordenar por id é o contrato). Id que não é raiz → devolve o grupo dele mesmo assim, resolvido pela view.

### Validação e erros
- `set_merged_into` não valida ciclo (ver acima) nem se o alvo existe — a FK do banco cuida do alvo.
- `group_root`/`group_members` nunca lançam para produto existente.

## Especificação técnica

```
criar    julius/infra/migrations/0004_product_merge.sql
modificar julius/repositories/products.py   — set_merged_into, group_root, group_members
modificar tests/test_db.py
modificar tests/test_repositories_products.py
```

### Padrão a seguir
- A migração é o quarto arquivo numerado; `infra/db.py::available_migrations` lê o prefixo e `apply_migrations` faz backup automático antes de aplicar — nada a fazer além de soltar o `.sql` na pasta.
- `_require_exists` já existe em `repositories/products.py` para o `LookupError`.
- Consulte a view por `JOIN`/`WHERE`, nunca reescreva a CTE numa função Python: uma definição só, na migração.

## Testes obrigatórios

1. `test_migration_0004_adds_merged_into_and_view` — em `tests/test_db.py`: `PRAGMA user_version` chega a 4, a coluna existe em `products` e `SELECT count(*) FROM product_group` devolve o número de produtos.
2. `test_product_group_has_one_row_per_product` — 3 produtos, nenhum fundido → 3 linhas, cada uma raiz de si mesma.
3. `test_group_root_resolves_a_chain` — A→B→C (`set_merged_into` duas vezes) → `group_root` de A, B e C devolve C.
4. `test_group_members_lists_root_and_absorbed_in_id_order` — dois absorvidos na mesma raiz → lista ordenada com os três ids.
5. `test_unmerging_the_middle_restores_the_previous_parent` — A→B→C, depois `set_merged_into(B, None)` → `group_root(A)` volta a ser B (**não** C). É o teste que prova o RF1b; sem ele, alguém "simplifica" guardando a raiz em vez do alvo direto.
6. `test_set_merged_into_unknown_product_raises` — `LookupError`.
7. `test_group_root_unknown_product_raises` — `LookupError`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira — hoje 589 testes).
- [ ] `grep -rn NotImplementedError julius` vazio.
- [ ] `grep -rn "set_merged_into\|group_root\|group_members" julius/services julius/cli` **vazio** — ninguém consome ainda.
- [ ] `tests/test_architecture.py` verde sem edição.
- [ ] Rodar contra uma cópia do banco real: `SELECT count(*) FROM product_group` devolve 105 e `PRAGMA user_version` devolve 4, com o backup `prices.db.bak-v3` criado.

## Notas para o agente

- **Não escreva nenhum teste que crie um ciclo** (A→B e B→A). Medido no design: a view entra em loop infinito e o processo **não retorna** — a suíte travaria para sempre, sem mensagem. A guarda que torna o ciclo impossível é o ticket 140; até ele existir, nenhum teste pode montar essa situação.
- A ordem de `group_members` é por id, não "raiz primeiro". Quem precisa da raiz chama `group_root`.
- Não acrescente `Product.merged_into` ao domínio aqui — só no 141, onde a CLI de `desfundir` precisa.
