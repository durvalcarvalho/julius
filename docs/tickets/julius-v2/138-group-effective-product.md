# 138: O produto efetivo do grupo nas leituras de catálogo

> As leituras de produto passam a ver grupos: só raízes aparecem, e a raiz carrega a melhor informação dos absorvidos.

## Contexto

`docs/design/merge-and-unit-price-v2.4.md` §2.1, §3 (a tabela de regras por campo), §7.2. Requisitos RF1c/RF1d/RF1i–RF1n.

A decisão central do design: **a herança de atributos é regra de leitura, não gravação**. Nada é copiado para a raiz, então desfundir devolve o estado anterior sem código de reversão.

Depende de **137** (`group_root`, `group_members`, a view).

## Escopo

### Dentro
- `julius/repositories/products.py`: `get_product` devolve o produto **efetivo** do grupo; `list_products`, `product_names`, `untagged_product_ids`, `incomplete_product_ids` listam **só raízes**; `product_ids_with_tag` resolve para a raiz e deduplica; `has_raw_name`, `sold_by_unit_ids`, `receipt_descriptions` passam a olhar o grupo inteiro.
- `tests/test_repositories_products.py`.

### Fora
- `prices_for_products` e o `exportar` (→ 139).
- `catalog.merge_products`/`unmerge` (→ 140) — os testes deste ticket montam a fusão com `products.set_merged_into`.
- Qualquer mudança em `services/` ou `cli/`: o efeito tem de chegar lá **sem** editar nada (ver "Padrão a seguir").
- Escrita: `rename_product`, `set_content`, `set_kind`, `add_tag` continuam gravando no id que receberam, sem resolver raiz.

## Requisitos

### Funcionais

- **`get_product(conn, product_id)`** resolve o id para a raiz e devolve um `Product` composto do grupo:

  | Campo | Regra |
  |---|---|
  | `id` | o da raiz |
  | `canonical_name` | o primeiro nome do grupo que **não** é a descrição crua de um cupom (`has_raw_name`), tentando a raiz primeiro e depois os absorvidos por id; todos crus → o da raiz |
  | `content_quantity`/`content_unit` | o da raiz; nulo na raiz → o primeiro não-nulo entre os absorvidos, por id (os dois campos sempre do mesmo produto) |
  | `kind` | mesma regra do conteúdo |
  | `tags` | união das tags do grupo, ordenada |

  Produto sem fusão nenhuma: resultado idêntico ao de hoje.

- **Só raízes aparecem**: `list_products`, `product_names`, `untagged_product_ids` e `incomplete_product_ids` filtram `merged_into IS NULL`. Em `list_products`, cada linha é o produto **efetivo** (mesma composição de `get_product`).
- **`product_ids_with_tag(conn, tag_name)`** devolve raízes, sem repetir: a tag que está só no absorvido tem de trazer a raiz, senão `consultar --tag` deixaria de achar um grupo que `produtos listar` mostra como marcado.
- **`has_raw_name(conn, product_id)`** passa a ser verdade quando **algum** membro do grupo tem o nome igual a uma `prices.description` sua — é o que impede a IA de renomear um grupo cujo nome já foi editado à mão.
- **`sold_by_unit_ids`** e **`receipt_descriptions`** recebem ids de raiz e olham os preços de todo o grupo (`receipt_descriptions` devolve a descrição da compra mais recente do grupo).
- **`incomplete_product_ids`** usa o conteúdo/tipo/tags **efetivos**: um grupo cuja raiz não tem conteúdo mas o absorvido tem **não** é pendente.

### Validação e erros
- `get_product` de id inexistente continua devolvendo `None`.
- Nenhuma função nova; nenhuma assinatura muda.

## Especificação técnica

```
modificar julius/repositories/products.py
modificar tests/test_repositories_products.py
```

### Padrão a seguir
- Resolva pela view (`JOIN product_group`), como o 137 fez; não recalcule a cadeia em Python.
- `list_products` já tem uma nota `ponytail:` assumindo uma query de tags por produto — o mesmo compromisso vale para a composição do grupo; não introduza cache.
- **O efeito propaga sem tocar `services/`**: `catalog_for_matching`, `closest_names`, `_matching_ids` (search), `duplicate_candidates` (curation) e `compare_stores`/`new_extremes` (comparison) derivam todos de `list_products`/`product_names`. Verifique isso rodando a suíte — nenhum arquivo de serviço deve precisar de edição neste ticket.

## Testes obrigatórios

1. `test_get_product_inherits_content_from_absorbed` — raiz sem conteúdo, absorvido com `0,5 KG` → o grupo tem `0,5 KG`; depois `set_merged_into(absorvido, None)` → a raiz volta a não ter (prova o RF1n sem código de reversão).
2. `test_get_product_inherits_kind_from_absorbed` — idem para `kind`.
3. `test_get_product_keeps_root_value_when_both_have_one` — raiz e absorvido com conteúdos diferentes → vale o da raiz.
4. `test_get_product_prefers_the_readable_name` — raiz com o nome cru do cupom, absorvido renomeado à mão → o grupo usa o nome legível.
5. `test_get_product_unions_tags` — tags diferentes nos dois lados → união ordenada.
6. `test_get_product_resolves_any_member_to_the_group` — `get_product(absorvido)` devolve o mesmo que `get_product(raiz)`, com `id` da raiz.
7. `test_list_products_hides_absorbed` — 3 produtos, um fundido → 2 linhas, e a que sobrou tem os atributos do grupo.
8. `test_product_names_and_untagged_hide_absorbed`.
9. `test_product_ids_with_tag_returns_the_root_once` — tag só no absorvido → devolve a raiz; tag nos dois → devolve a raiz uma vez só.
10. `test_has_raw_name_true_when_any_member_has_it`.
11. `test_incomplete_excludes_group_whose_absorbed_has_the_content` — o caso que fecha o RF1k.
12. `test_receipt_descriptions_and_sold_by_unit_cover_the_whole_group`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `git diff --stat julius/services julius/cli` **vazio** — o efeito chegou lá sem edição.
- [ ] `tests/test_architecture.py` verde sem edição.
- [ ] `grep -rn NotImplementedError julius` vazio.

## Notas para o agente

- **Não grave nada na raiz para "materializar" a herança.** O ponto do design é que a composição é derivada; gravar reintroduz o problema de reverter (e um `UPDATE` numa leitura é o tipo de coisa que ninguém espera).
- Escrever continua sem resolver raiz: `set_kind(absorvido, ...)` grava no absorvido e fica inerte enquanto ele estiver fundido. É intencional (design §3).
- Se algum teste de serviço quebrar, a causa provável é a suíte ter suposto que `list_products` devolve tudo. Corrija o teste, não volte a expor absorvidos.
