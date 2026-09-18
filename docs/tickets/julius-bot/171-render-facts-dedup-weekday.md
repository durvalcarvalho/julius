# 171: `bot/render.py` — sem preço repetido, sem data redundante nos fatos

> `records_facts` para de repetir a mesma loja com o mesmo preço em datas diferentes (a causa concreta do textão da screenshot), e as duas funções de fatos trocam "data + há X dias" por `weekday_phrase` (170).

## Contexto

Segue o design v2.7.1. Depende de **170** (`weekday_phrase`). Independente de 172–173.

## Escopo

### Dentro
- `_collapse_repeated_prices(records: Sequence[PriceRecord]) -> list[PriceRecord]` (privada): agrupa por `(store_nickname, unit_price)`, mantém a ocorrência de `purchased_at` mais recente de cada par, preserva a ordem da primeira aparição de cada par na lista original.
- `records_facts` chama `_collapse_repeated_prices` **antes** de montar as linhas (e antes de decidir a linha de diferença — a diferença usa `highlight`, que não muda com a colagem, já que preço/loja duplicados têm o mesmo `highlight`).
- `records_facts`/`comparison_facts`: trocam `f"{br_date(...)} ({relative_age(...)})"` por `weekday_phrase(purchased_at, today=today)` sozinho.

### Fora
- `_record_line`/`_comparison_block` (a tabela HTML) — continuam com `br_date`/`relative_age`, sem `weekday_phrase` e sem dedup. A tabela é o histórico completo; os fatos da persona são o resumo.
- `search_fallback_line`/`compare_fallback_line` — não usam data/dia da semana hoje (só preço, loja, e a diferença); este ticket não muda isso. Se quiser dia da semana ali também, é ajuste futuro, não pedido nesta rodada.
- `products_facts`/`stores_facts` — não têm data nenhuma, não mudam.

## Requisitos

### Funcionais
- `_collapse_repeated_prices([])` devolve `[]`.
- Dois registros do mesmo `(loja, preço)` com datas diferentes → um só, com a data mais recente das duas.
- Registros de lojas ou preços diferentes nunca colapsam entre si, mesmo com nomes de produto iguais.
- A linha de diferença (`"diferença entre o mais barato e o mais caro: ..."`) usa a lista **depois** da colagem — evita contar duas vezes o mesmo par na hora de achar `highlight == "lowest"/"highest"`, embora o resultado não mude (duplicata tem o mesmo `highlight` do original).

### Validação e erros
- Nenhuma exceção nova; `_collapse_repeated_prices` é função pura sobre uma lista, sem I/O.

## Especificação técnica

```
modificar julius/bot/render.py       — _collapse_repeated_prices; records_facts e comparison_facts passam a usar weekday_phrase
modificar tests/test_bot_render.py   — testes de dedup e da troca de formato de data
```

### Padrão a seguir
- `records_facts`/`comparison_facts` já existem (tickets 164, revisado no v2 do prompt) — este ticket edita o corpo delas, não recria.
- Import novo: `from julius.domain.formatting import weekday_phrase` (junto dos outros imports de `domain.formatting` já existentes no topo do arquivo).

## Testes obrigatórios

1. `test_collapse_repeated_prices_merges_same_store_and_price_keeping_latest_date`.
2. `test_collapse_repeated_prices_keeps_different_stores_or_prices_separate`.
3. `test_collapse_repeated_prices_empty_list`.
4. `test_records_facts_uses_weekday_phrase_not_the_calendar_date` — a data numérica (`"16/09/2026"`) não aparece mais no texto; o nome do dia aparece.
5. `test_records_facts_collapses_repeated_price_before_narration` — dois registros do mesmo par (loja, preço) em datas diferentes → uma linha só nos fatos.
6. `test_comparison_facts_uses_weekday_phrase_not_the_calendar_date`.
7. Testes existentes de `records_facts`/`comparison_facts` que hoje afirmam `br_date(...)`/`relative_age(...)` no texto — atualizar pra `weekday_phrase(...)` equivalente (ex.: `TODAY = date(2026, 9, 17)` e `purchased_at="2026-09-12..."` → 5 dias atrás → `"sexta-feira"`; ajustar a string exata esperada).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "br_date\|relative_age" julius/bot/render.py` mostra essas duas funções usadas **só** em `_record_line`/`_comparison_block`/`render_comparison` (rodapé "base: ... a ...") — nunca em `records_facts`/`comparison_facts`.
- [ ] `grep -n "16/09/2026\|dd/mm/yyyy" ` num teste de `records_facts` não aparece mais como saída esperada.

## Notas para o agente

- Não colapse por produto+data (isso apagaria histórico de preço real, dias em que o mesmo item foi comprado duas vezes por engano) — a chave é especificamente `(loja, preço)`, o caso exato que gerou o textão real.
- `search_fallback_line`/`compare_fallback_line` ficam de fora de propósito (ver Escopo/Fora) — não "aproveite a viagem" pra mexer neles sem pedido.
