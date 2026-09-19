# 177: `bot/render.py` — fatos e frase-molde do veredito de lista de compras

<!-- status:done implemented:2026-09-19 commit:f7cee3e -->

> O par `shopping_comparison_facts`/`shopping_verdict_line`, no mesmo molde de `comparison_facts`/`compare_fallback_line` — um pra a IA comentar, outro pra quando não há IA.

## Contexto

`docs/design/shopping-list-conversation-context.md`, Decisão 2 (RNF1: o veredito — contagem N de M, nomes de loja — é conta feita em código, a IA só veste a fala). Depende de **175** (`ShoppingVerdict`) e **176** (`ShoppingComparison`) só pelos tipos — pode ser feito em paralelo a 176 assim que 175 estiver de pé (ver diagrama no índice).

## Escopo

### Dentro
- `julius/bot/render.py`: `shopping_comparison_facts(shopping: ShoppingComparison, *, today=None) -> str` e `shopping_verdict_line(shopping: ShoppingComparison, *, today=None) -> str`.
- `tests/test_bot_render.py`: casos novos.

### Fora
- `turn.py` (integração, → 179).
- Mudar `comparison_facts`/`compare_fallback_line`/`render_comparison` existentes — continuam servindo só `StoreComparison` sem escopo (a CLI, indiretamente).

## Requisitos

### Funcionais

`shopping_comparison_facts(shopping, *, today=None)`:
- Linha a linha por grupo: reaproveitar `comparison_facts(shopping.comparison, today=today)` (chamada interna) para as linhas de fato por `kind`/loja/preço/diferença — **não duplicar** essa lógica.
- Se `shopping.verdict` não for `None`, acrescentar:
  - uma linha `"veredito: {total_items} de {total_items} itens..."` — não, **corrigir**: `"veredito: {len(won_kinds)} de {total_items} itens mais baratos em {lojas}"`, `{lojas}` = `winner_stores` juntos com " e " quando houver mais de um.
  - se `runner_up_store` não for `None`: uma segunda linha, `"o resto ({N} item(ns): {kinds}) sai mais em conta em {runner_up_store}"`, `N = len(runner_up_kinds)`, `kinds` = `runner_up_kinds` juntos por ", ".
- Se `shopping.unmatched_terms` não for vazio: uma linha `"sem preço comparável registrado ainda para: {termos}"`, termos juntos por ", ", **exatamente como vieram** (não reformatar/capitalizar).
- Tudo em texto puro — sem HTML (`escape`/`<b>`/`<pre>`), mesma disciplina de `records_facts`/`comparison_facts`: é o texto que alimenta `narrate()`, não o que vai pro Telegram.

`shopping_verdict_line(shopping, *, today=None)`:
- Determinístico, sem IA — mesmo espírito de `compare_fallback_line`/`search_fallback_line`.
- `shopping.comparison.comparisons` vazio **e** `shopping.unmatched_terms` vazio → `"Não achei preço comparável entre mercados pra esses itens ainda."`.
- `shopping.comparison.comparisons` vazio **e** `unmatched_terms` não vazio → cita os termos: `"Não achei preço comparável entre mercados pra: {termos}."`.
- `shopping.verdict` não `None`: frase com a contagem e a(s) loja(s) vencedora(s) (mesmo dado de `shopping_comparison_facts`, em prosa: `"{N} de {total} produtos mais baratos em {lojas}, vale ir lá."`); se `runner_up_store`: frase extra, `" O resto sai mais em conta em {runner_up_store}."`; se `unmatched_terms`: frase extra citando os termos não achados.

### Validação e erros
- Nenhuma das duas funções lança — mesma disciplina de todo `render.py`.

## Especificação técnica

```
modificar julius/bot/render.py — shopping_comparison_facts, shopping_verdict_line
modificar tests/test_bot_render.py
```

Import novo em `render.py`: `ShoppingComparison`, `ShoppingVerdict` (via `TYPE_CHECKING`, como `PendingWrite`/`WriteResult` já entram hoje — `render.py` não pode importar `pydantic_ai` em tempo de execução, e `ShoppingComparison` mora em `bot/actions.py`).

### Padrão a seguir
- `comparison_facts`/`compare_fallback_line` (mesmo arquivo, `bot/render.py:176-201` e `:271-290`) são o par a espelhar na forma exata: mesma assinatura `(objeto, *, today=None) -> str`, mesmo estilo de docstring citando a guarda de dinheiro.
- `money()` de `domain.formatting` para todo valor — nunca `f"R$ {x:.2f}"` solto (mas nesta função não deveria nem aparecer valor novo: os únicos números são contagens de itens, que não passam por `money()`).

## Testes obrigatórios

1. `test_shopping_comparison_facts_includes_verdict_line` — com `verdict` preenchido, a string contém "veredito:" e a contagem certa (`N de M`).
2. `test_shopping_comparison_facts_includes_runner_up` — `runner_up_store` preenchido → linha própria citando a loja e os kinds restantes.
3. `test_shopping_comparison_facts_includes_unmatched` — termo não casado aparece como fato próprio, com o texto original preservado.
4. `test_shopping_comparison_facts_no_verdict_no_unmatched` — só as linhas de `comparison_facts`, nada extra.
5. `test_shopping_verdict_line_with_winner_and_runner_up` — frase cita loja vencedora, contagem e a loja do resto.
6. `test_shopping_verdict_line_tie_names_both_stores` — `winner_stores` com duas lojas → as duas aparecem na frase.
7. `test_shopping_verdict_line_nothing_comparable` — comparação e `unmatched_terms` vazios → frase fixa.
8. `test_shopping_verdict_line_with_unmatched_only` — sem `verdict`, com `unmatched_terms` → frase citando só os termos.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] Nenhum valor numérico em `shopping_comparison_facts`/`shopping_verdict_line` que não venha de `comparison_facts` ou dos campos de `ShoppingVerdict` — todo número citado tem origem rastreável (checagem manual na revisão do ticket).

## Notas para o agente

- Não formate dinheiro diferente do resto do arquivo — se algum valor precisar aparecer (não deveria, mas se aparecer), use `money()`.
- `shopping_comparison_facts` **não é HTML** — texto puro, é o que vai pro prompt da IA (`narrate()`), não pro Telegram diretamente.
- Não invente uma terceira função "resumida" — o par fatos/frase-molde é suficiente, mesmo padrão de todo o resto de `render.py`.
