# 157: `bot/actions.py` — tipo, conteúdo, fundir e desfundir

<!-- status:done implemented:2026-09-17 commit:4850540 -->
<!-- adjustments: unmerge checa fusão por id devolvido (merged_into não chega por services); undo refunde na raiz -->

> As escritas que restam, no mesmo molde do 156: preview do banco, nada gravado até o tap, e o desfazer calculado do estado real.

## Contexto

`docs/design/telegram-bot.md` §3.1 (tabela de escrita) e §4.3. Estas quatro operações da CLI já são reversíveis (`tipo --remover`, `definir-conteudo --remover`, `desfundir`, `fundir`), e é por isso que entram no bot. O preview de conteúdo mostra a unidade **já normalizada** (`500 G` → `0,5 KG`), que é o que será gravado; o de fusão diz o que o grupo herda (`catalog.merge_inheritance`).

Depende de **156**.

## Escopo

### Dentro
- `julius/bot/actions.py`: `set_product_kind`, `clear_product_kind`, `set_product_content`, `clear_product_content`, `merge_products`, `unmerge_product`; os seis ramos novos em `execute`; `WRITE_ACTIONS` completo (10) e `ALL_ACTIONS = READ_ACTIONS + WRITE_ACTIONS`.
- `tests/test_bot_actions_write.py` (acrescenta).

### Fora
- Qualquer fusão sem tap (a curadoria da CLI continua com a dela; o bot só funde o que o usuário pediu **e** confirmou).
- `produtos comparar` (opinião da IA sobre um par) — fora do bot nesta rodada.

## Requisitos

### Funcionais

| Ação | Parâmetros | Pré-checagem (→ `ModelRetry`) | Preview |
|---|---|---|---|
| `set_product_kind` | `product: str, kind: str` | tipo em branco | `Definir o tipo do produto {id} «{nome}» como «{tipo}»` + ` (antes: «{antes}»)` se tinha |
| `clear_product_kind` | `product: str` | produto sem tipo → `"O produto {id} não tem tipo."` | `Remover o tipo «{tipo}» do produto {id} «{nome}»` |
| `set_product_content` | `product: str, quantity: float, unit: str` | `quantity <= 0`; `normalize_content` lança `ValueError` → `"Unidade «{u}» inválida; aceitas: L, ML, KG, G, UN."` | `Definir o conteúdo do produto {id} «{nome}» como {content_text(q_norm, u_norm)}` + ` (antes: {content_text(...)})` se tinha |
| `clear_product_content` | `product: str` | sem conteúdo → retry | `Remover o conteúdo {content_text} do produto {id} «{nome}»` |
| `merge_products` | `source: str, target: str` | mesmo id → `"Origem e destino são o mesmo produto."` | `Fundir o produto {sid} «{sname}» dentro de {tid} «{tname}»: o histórico dos dois passa a aparecer junto` + `; o grupo herda {o quê} de {de onde}` quando `catalog.merge_inheritance(conn, sid, tid)` não é `None` |
| `unmerge_product` | `product: str` | `product.merged_into is None` → `"O produto {id} não está fundido."` | `Desfundir o produto {id} «{nome}» de {tid} «{tname}»` |

- `args`: `product_id` + `kind` / `product_id` / `product_id`, `quantity` (**já normalizada**), `unit` (**já normalizada**) / `product_id` / `source_id`, `target_id` / `product_id`.
- `merge_products` resolve os dois pelo mesmo `resolve_product`; um `ModelRetry` de ambiguidade em qualquer dos dois interrompe a ação (o modelo pergunta).

`execute` — lê o estado atual antes de escrever e monta `undo`:

| Ação | Serviço | `undo` |
|---|---|---|
| `set_product_kind` | `catalog.set_product_kind` | `julius produtos tipo {id} "{antes}"` se tinha; senão `julius produtos tipo {id} --remover` |
| `clear_product_kind` | `catalog.clear_product_kind` | `julius produtos tipo {id} "{antes}"` |
| `set_product_content` | `catalog.set_product_content(conn, id, quantity, unit)` | `julius produtos definir-conteudo {id} {q_antes:g} {u_antes}` se tinha; senão `julius produtos definir-conteudo {id} --remover` |
| `clear_product_content` | `catalog.clear_product_content` | `julius produtos definir-conteudo {id} {q:g} {u}` |
| `merge_products` | `catalog.merge_products` | `julius produtos desfundir {source_id}` |
| `unmerge_product` | `catalog.unmerge_product` | `julius produtos fundir {id} {merged_into de antes}` |

- `summary` no mesmo espírito do 156 (o que ficou, e o que era).
- `ValueError` do serviço (ex.: ciclo de fusão, `"produto X já faz parte do grupo de Y"`) e `LookupError` → `WriteFailed(str(error))` — a pré-checagem da ação não tenta prever o ciclo (o serviço é a única guarda, e o design não a duplica).

### Validação e erros
- Nenhuma das seis ações grava (mesmo teste de "antes == depois" do 156).
- `set_product_content` recebe `quantity` como `float` do modelo; `"500"` vira `500.0` pela validação do PydanticAI — a ação não parseia string.

## Especificação técnica

```
modificar julius/bot/actions.py           — 6 ações, 6 ramos em execute, WRITE_ACTIONS/ALL_ACTIONS
modificar tests/test_bot_actions_write.py
```

### Padrão a seguir
- `cli/products.py::set_content`/`set_kind`/`merge_products`/`unmerge_product` — as mensagens da CLI são o precedente de tom; o `undo` reproduz exatamente a sintaxe dos comandos.
- `domain.normalization.normalize_content(quantity, raw_unit)` é quem normaliza — chame-a na ação (preview) **e** deixe `catalog.set_product_content` chamá-la de novo na execução (é idempotente: entrada já normalizada sai igual).

## Testes obrigatórios

1. `test_set_kind_pending_and_execute_with_and_without_previous` — sem tipo antes → `undo` com `--remover`; com tipo → `undo` com o antigo entre aspas.
2. `test_clear_kind_requires_a_kind` — sem tipo → retry; com tipo → pendência, execução e `undo` restaurando.
3. `test_set_content_preview_shows_normalized_unit` — `{"quantity": 500, "unit": "G"}` → preview `0,5 KG`, `args == {"product_id": id, "quantity": 0.5, "unit": "KG"}`; após `execute`, `content_quantity == 0.5`, `content_unit == "KG"`.
4. `test_set_content_invalid_unit_or_quantity_retries` — `"caixas"` → mensagem lista `L, ML, KG, G, UN`; `quantity=0` → retry.
5. `test_clear_content_pending_and_undo` — `undo == f"julius produtos definir-conteudo {id} 0.5 KG"` (`:g` formata `0.5`).
6. `test_merge_pending_mentions_inheritance` — destino sem conteúdo, origem com → preview contém "o grupo herda o conteúdo".
7. `test_merge_same_product_retries`.
8. `test_merge_execute_and_undo` — `products.group_root` do source passa a ser o target (via `catalog.get_product(...).merged_into`); `undo == f"julius produtos desfundir {source}"`.
9. `test_merge_cycle_fails_closed_at_execute` — A→B fundido; pendência B→A executa → `WriteFailed` com a mensagem do serviço; nada mudou.
10. `test_unmerge_requires_merged_and_undo_restores_target` — não fundido → retry; fundido → executa, `undo == f"julius produtos fundir {id} {target}"`.
11. `test_all_actions_have_unique_names_and_docstrings` — `len({a.__name__ for a in ALL_ACTIONS}) == 14`; todos com docstring não vazia contendo `Args:` (exceto `compare_stores`/`list_stores`, sem parâmetros).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `ALL_ACTIONS` tem 14 funções (4 leitura + 10 escrita).
- [ ] `grep -n "group_root\|set_merged_into\|repositories" julius/bot/actions.py` **vazio** — só `services`.

## Notas para o agente

- Não pré-verifique ciclo de fusão na ação (precisaria de `repositories.products.group_root`, proibido na camada): o serviço lança e `execute` traduz. Uma pendência que vai falhar no tap é aceitável; um atalho pela DAG não.
- `unmerge_product` só faz sentido para um produto **absorvido**; `resolve_product` por id acha absorvidos (`catalog.get_product` não filtra), por nome talvez não (`matching_product_ids` olha os nomes de todos os produtos) — documente no docstring que o modelo deve preferir o id que `list_products`/`search_prices` mostrou.
