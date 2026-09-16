# 117: Migração 0003 + `products.kind` no domínio e nos repositórios

> Cria a coluna do grupo de comparação e o caminho de leitura/escrita dela, com a regra de grafia que impede o mesmo grupo de se fragmentar em `tomate`/`Tomate`/`TOMATE`.

## Contexto

`docs/design/comparability-v2.2.md` §2 (por que uma coluna e não `tags` nem tabela nova), §4.1 (migração), §4.2 (domínio), §4.3 (repositório — inclui **por que a regra de grafia vive aqui**), §4.4 (`prices`). Requisito RF1 de `docs/requirements/comparability-closure.md`.

O grupo de comparação é "que tipo de coisa isso é" (`tomate`, `cebola`, `leite uht`), e é ele que permite comparar preço entre lojas sem fundir produto — decisão medida em `comparability-closure.md` §3. Este ticket só cria a coluna e o acesso a ela: **ninguém atribui `kind` ainda** (a IA entra no 120/121, o comando manual no 118, os consumidores no 124/126).

## Escopo

### Dentro
- `julius/infra/migrations/0003_product_kind.sql` (novo).
- `julius/domain/models.py`: `Product.kind`, `PriceRecord.kind`.
- `julius/repositories/products.py`: `set_kind`, `all_kinds`, `clear_content`; `_to_product`/`list_products` passam a ler `kind`.
- `julius/repositories/prices.py`: `prices_for_products` passa a trazer `products.kind`.
- Testes: `tests/test_db.py`, `tests/test_repositories_products.py`, `tests/test_repositories_prices.py`.

### Fora
- `services/catalog.py` e qualquer CLI (→ 118).
- Qualquer coisa de IA: prompt, `ProductEnrichment`, `curation` (→ 120, 121).
- `domain/comparison_basis.py` e `_highlight_and_trim` (→ 119, independente deste ticket).
- Consumir `kind` para comparar (→ 124, 126).
- Índice em `kind`, `CHECK` na coluna, tabela `kinds` — decididos contra no design §2/§4.1.
- Migrar dado existente: todo produto nasce com `kind IS NULL`, e isso é o estado correto.

## Requisitos

### Funcionais

- **Migração** `0003_product_kind.sql`, conteúdo exato (comentário em inglês, como as outras):
  ```sql
  -- Comparison group: "what kind of thing is this", so prices of the same kind can be compared
  -- across stores. One column, not a table: a product belongs to at most one group, and a single
  -- column makes that the database's rule instead of the application's.
  ALTER TABLE products ADD COLUMN kind TEXT;
  ```
  Nada além disso no arquivo. `available_migrations` já descobre pelo prefixo `0003_`; nenhuma constante de versão a atualizar.

- `Product` ganha `kind: str | None = None` (último campo, default para não quebrar construção posicional existente).
- `PriceRecord` ganha `kind: str | None = None` (mesmo motivo; é o `kind` do produto daquela linha).

- `products.all_kinds(conn) -> list[str]` — `SELECT DISTINCT kind ... WHERE kind IS NOT NULL ORDER BY kind`. Lista vazia quando ninguém tem tipo.

- `products.set_kind(conn, product_id: int, kind: str | None) -> None`:
  - `_require_exists(conn, product_id)` primeiro, como as irmãs do arquivo.
  - `kind is None` → grava `NULL` (é o desfazer).
  - String: `strip()`; vazia depois do strip → `ValueError("kind must not be blank")`.
  - Minúsculo (`.lower()`).
  - **Regra de grafia (design §2/§4.3):** procura em `all_kinds` algum tipo existente cujo `normalize_text` seja igual ao `normalize_text` do proposto; achando, grava **a grafia já existente** em vez da proposta. Isso faz `Tomate`, `TOMATE` e `tomate` caírem todos no mesmo grupo, e preserva acento de quem entrou primeiro (`açaí` não vira `acai`).
  - Sem match, grava o valor minúsculo como veio (acento incluso).

- `products.clear_content(conn, product_id: int) -> None` — zera `content_quantity` **e** `content_unit` (as duas juntas; conteúdo pela metade é estado inválido). `_require_exists` antes.

- `_to_product` e `list_products` passam a preencher `Product.kind`; `prices_for_products` passa a preencher `PriceRecord.kind` — o join com `products` já existe na query, só falta a coluna no `SELECT`.

### Validação e erros
- `set_kind` com produto inexistente → o mesmo erro que `rename_product`/`set_content` já levantam via `_require_exists` (não inventar erro novo).
- `set_kind("")` ou `set_kind("   ")` → `ValueError`. `set_kind(None)` é operação válida, não erro.

## Especificação técnica

```
criar    julius/infra/migrations/0003_product_kind.sql
modificar julius/domain/models.py            — Product.kind, PriceRecord.kind
modificar julius/repositories/products.py    — set_kind, all_kinds, clear_content, _to_product, list_products
modificar julius/repositories/prices.py      — kind no SELECT de prices_for_products
modificar tests/test_db.py
modificar tests/test_repositories_products.py
modificar tests/test_repositories_prices.py
```

### Padrão a seguir
- `normalize_text` já existe em `julius/domain/normalization.py` e já é usado por `services/search.py`; importe-o, **não escreva uma segunda normalização**.
- **Assimetria intencional com o padrão de tag:** `catalog.tag_product` normaliza e valida antes de chamar `products.add_tag` (repositório "burro"). Para `kind` é o contrário: a regra vive no repositório. Motivo no design §4.3 — existem dois caminhos de escrita (comando manual e `curation.apply`, que grava direto pelos repositórios) e `services` não pode importar `services`; se a regra morasse em `catalog`, o caminho automático a burlaria. **Não "conserte" essa assimetria.**
- Leitura-antes-de-escrita no repositório já tem precedente no mesmo arquivo: `resolve_product_id`.

## Testes obrigatórios

1. `test_migration_0003_adds_kind_column` — banco novo tem a coluna `kind` em `products` e `schema_version` igual ao maior prefixo disponível.
2. `test_migration_0003_backs_up_existing_database` — banco criado na versão 2 e reaberto: `prices.db.bak-v2` existe e a coluna aparece sem perder linhas de `products`/`prices` (mesmo padrão do teste de backup que já existe para a 0002).
3. `test_set_kind_and_read_back` — `set_kind(id, "Tomate")` → `get_product(id).kind == "tomate"`.
4. `test_set_kind_reuses_existing_spelling` — produto A com `kind="açaí"`; `set_kind(B, "ACAI")` → `get_product(B).kind == "açaí"` (não `"acai"`, não `"ACAI"`).
5. `test_set_kind_none_clears` — depois de `set_kind(id, None)`, `get_product(id).kind is None`.
6. `test_set_kind_blank_raises` — `""` e `"   "` levantam `ValueError`.
7. `test_set_kind_unknown_product_raises` — id inexistente levanta o mesmo erro das irmãs.
8. `test_all_kinds_distinct_and_sorted` — três produtos, dois com o mesmo tipo → lista sem repetição, ordenada; banco sem tipos → `[]`.
9. `test_clear_content_clears_both_columns` — produto com conteúdo definido, depois de `clear_content` os dois campos são `None`.
10. `test_prices_for_products_carries_kind` — produto com tipo definido: o `PriceRecord` devolvido traz `kind`; produto sem tipo traz `None`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira — hoje 394 testes).
- [ ] `grep -rn NotImplementedError julius` vazio.
- [ ] Nenhum consumidor de `kind` foi criado (nada em `services/` além dos repositórios, nada em `cli/`).
- [ ] Rodar a migração contra uma **cópia** do banco real antes de commitar, como o 102 exigiu: `cp ~/.local/share/julius/prices.db /tmp/x.db && JULIUS_DB=/tmp/x.db julius produtos listar` deve funcionar e gerar `/tmp/x.db.bak-v2`.

## Notas para o agente
- A ordem dos campos novos nos dataclasses importa: `kind` entra **por último**, com default, porque há construção posicional de `PriceRecord` em testes existentes.
- Não adicione `kind` ao CSV de export neste ticket — não está no escopo e o 103 definiu as colunas do export.
- `ALTER TABLE ADD COLUMN` no SQLite não reescreve a tabela; a migração é instantânea mesmo com o banco cheio.
