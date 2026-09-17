# 140: `catalog` — fusão reversível, `unmerge` e a guarda de ciclo

> `merge_products` vira uma linha, ganha um irmão que desfaz, e a validação que impede o sistema de congelar.

## Contexto

`docs/design/merge-and-unit-price-v2.4.md` §4.1–§4.3, §7.5. Requisitos RF1a/RF1b/RF1g/RF7.

Depende de **137** (`set_merged_into`, `group_root`) e **139** (a ponte que já trocou a reatribuição de preços).

**A guarda de ciclo é o requisito mais sério deste ticket.** Medido no design: com `A→B` e `B→A`, a view recursiva **não retorna** — todo comando que lê produto para de responder, sem mensagem de erro. É o único risco deste desenho que não falha alto sozinho.

## Escopo

### Dentro
- `julius/services/catalog.py`: `merge_products` reescrita, `unmerge_product`, `merge_inheritance`.
- `julius/repositories/products.py`: remoção de `reassign_skus` e `delete_product` (ficam órfãs).
- `tests/test_services_catalog.py`, `tests/test_repositories_products.py`.

### Fora
- CLI (`desfundir`, texto do `fundir`, o campo `"merge"` no log) → 141.
- Fusão automática → 143.
- Guarda de conteúdo divergente → 142.

## Requisitos

### Funcionais

- **`merge_products(conn, source_id, target_id)`** — valida e grava, nada mais:
  1. `source_id != target_id` → `ValueError`;
  2. os dois produtos existem → `LookupError`;
  3. **`group_root(target_id) != source_id`** → `ValueError` com mensagem clara em português; é a guarda de ciclo;
  4. `products.set_merged_into(conn, source_id, target_id)`, dentro de `with conn`.

  Sai tudo o que ela fazia antes: reatribuição de SKUs e preços, cópia de tags e de conteúdo (virou leitura no 138) e o `delete_product`.

- **`unmerge_product(conn, product_id)`** — `products.set_merged_into(conn, product_id, None)`. `LookupError` se o produto não existe; `ValueError` se ele não está fundido (mensagem dizendo isso). Os produtos que foram fundidos **nele** continuam apontando para ele, que volta a ser raiz.

- **`merge_inheritance(conn, source_id, target_id) -> tuple[str, str] | None`** — o que o grupo passará a ter por causa desta fusão, para a notificação do 143: `("conteúdo 0,5 KG", "produto 80")` ou `None` quando nada é herdado. Calculada **antes** de fundir, comparando os dois produtos: conteúdo e tipo que o alvo não tem e a origem tem. Nunca lança.

- **`reassign_skus` e `delete_product` são removidas** de `repositories/products.py`, com seus testes. Verificado: `merge_products` era a única chamadora de cada uma. Com elas, sai o último caminho de código capaz de apagar um produto.

### Validação e erros
- Mensagens de erro em português (são texto de usuário, via `fail` na CLI).
- Nada é gravado quando qualquer validação falha.

## Especificação técnica

```
modificar julius/services/catalog.py        — merge_products, unmerge_product, merge_inheritance
modificar julius/repositories/products.py   — remove reassign_skus e delete_product
modificar tests/test_services_catalog.py
modificar tests/test_repositories_products.py
```

### Padrão a seguir
- `_require_product` já existe em `catalog.py` para o `LookupError`.
- `with conn:` em toda escrita, como as outras funções de `catalog`.
- O formato do texto de `merge_inheritance` usa `cli/_common.py::content_text` para o valor? **Não** — `services/` não importa `cli/`. Formate com `f"{quantity:g}"` e deixe a vírgula decimal para a CLI, ou devolva os dados crus e deixe a frase para o 141/143. Escolha e registre no docstring.

## Testes obrigatórios

1. `test_merge_records_the_relation_and_deletes_nothing` — depois de fundir: `products` continua com as duas linhas, `product_skus` e `prices` intocados, e `get_product(source)` devolve o grupo.
2. `test_merge_rejects_a_cycle` — `merge(A, B)` e depois `merge(B, A)` → `ValueError`, nada gravado, e **`group_root(A)` responde** (a view não travou). O teste tem de terminar; se pendurar, a guarda não está funcionando.
3. `test_merge_rejects_a_two_step_cycle` — A→B, B→C, depois `merge(C, A)` → `ValueError`.
4. `test_merge_same_id_raises_value_error` (existente, mantém).
5. `test_merge_unknown_id_raises_lookup_error_and_changes_nothing` (existente, mantém).
6. `test_unmerge_restores_the_previous_state` — funde, confere o grupo, desfunde, confere que os dois produtos voltaram a ser independentes com seus próprios atributos.
7. `test_unmerge_product_not_merged_raises` e `test_unmerge_unknown_product_raises`.
8. `test_unmerge_keeps_its_own_children` — A→B→C; `unmerge(B)` → A continua em B.
9. `test_merge_inheritance_reports_content_and_none` — alvo sem conteúdo e origem com → devolve a descrição; os dois com conteúdo → `None`.
10. Os testes existentes `test_merge_moves_skus_prices_and_tags_then_deletes_source`, `test_merge_copies_content_when_target_has_none` e `test_merge_keeps_target_content_when_present` **mudam de expectativa**: nada é movido, nada é apagado, e o conteúdo do grupo vem da composição do 138.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira) **e terminando** — nenhum teste pendura.
- [ ] `grep -rn "reassign_skus\|delete_product" julius tests` **vazio**.
- [ ] `grep -n "DELETE FROM products" julius -r` **vazio** — nenhum caminho apaga produto.
- [ ] `tests/test_architecture.py` verde sem edição.

## Notas para o agente

- **A guarda de ciclo vem antes de qualquer teste que monte um ciclo.** Escreva a validação primeiro, rode `pytest` com `timeout`, e só então escreva o teste 2/3. Um ciclo gravado no banco de teste trava a coleta da suíte inteira.
- Não implemente guarda de profundidade: a cadeia é finita por construção assim que o ciclo é impossível.
- Não reintroduza a cópia de tags/conteúdo "por segurança": duplicaria o que o 138 deriva e recriaria o problema de reverter.
