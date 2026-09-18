# 167: `bot/turn.py` — Modo A/B para as 4 leituras

> Onde tudo se junta: para cada leitura, decide se o resultado é pequeno o bastante para a IA substituir a tabela inteira (Modo A) ou grande demais e só ganha um comentário por cima (Modo B) — e o que fazer quando a IA não responde.

## Contexto

Fecha o design v2.7 para as leituras. Depende de **163** (`narrate`), **164** (`*_facts`), **165** (frases-molde) e **166** (`Deps.client`) — é o primeiro ticket que os une.

## Escopo

### Dentro
- Constantes `NARRATE_FULL_MAX_RECORDS = 6` e `NARRATE_FULL_MAX_GROUPS = 3` (chute inicial, documentado como não-medido — ver Notas).
- Helper privado `async def _narrate(deps: Deps, context: str, facts: str) -> str | None`: se `deps.client is None` ou `facts` vazio, devolve `None` sem tocar em thread nenhuma; senão, `await asyncio.to_thread(suggestions.narrate, deps.conn, deps.config, deps.client, context, facts)`.
- `_render_output` (já `async def` desde o protótipo descartado — se não estiver, torna-se) ganha, para cada uma das 4 leituras, a composição:
  - **`SearchOutcome`** com `len(records) <= NARRATE_FULL_MAX_RECORDS`: tenta `_narrate(deps, "histórico de preço de um produto", records_facts(records))`; se vier texto, `Reply(escape(texto))`; senão `Reply(search_fallback_line(records))`.
  - **`SearchOutcome`** maior, ou **`StoreComparison`** com mais de `NARRATE_FULL_MAX_GROUPS` grupos: comentário (Modo B) — tenta `_narrate` com fatos resumidos; se vier texto, `Reply(escape(texto) + "\n\n" + base)`; senão só `Reply(base)` (o `render_records`/`render_comparison` de sempre — **nenhuma mudança de comportamento aqui**, é o caminho de hoje).
  - **`StoreComparison`** com `len(comparison.comparisons) <= NARRATE_FULL_MAX_GROUPS`: mesma lógica do primeiro caso de busca, usando `comparison_facts`/`compare_fallback_line`.
  - **`ProductListing`/`StoreListing`**: sempre Modo B — `_narrate(deps, "catálogo de produtos"/"catálogo de mercados", products_facts(...)/stores_facts(...))`; comentário prependado se vier texto, senão o `render_products`/`render_stores` de sempre, sem comentário (nunca um molde novo aqui — RF4 não cobre listagens, só busca/comparação).
- Chamada em `handle_text`: `reply = await _render_output(result.output, state, deps)` (sem mudança de assinatura em relação ao protótipo anterior).

### Fora
- `PendingWrite`/`WriteResult`/`WriteFailed` (→ 168).
- Mudar `render_records`/`render_comparison`/`render_products`/`render_stores` — continuam exatamente como estão; este ticket só decide quando usá-los.
- Medir o corte de tamanho contra o banco real — fica para o smoke (169); as constantes aqui são um ponto de partida documentado como tal.

## Requisitos

### Funcionais
- Quando `deps.client is None` (IA não configurada, ou teste que não passa client): comportamento **idêntico** ao de antes deste ticket — mesma tabela, mesmo texto, nenhuma chamada de thread. É a garantia de não regressão dos testes de `test_bot_turn.py` já existentes.
- `output.records`/`comparison.comparisons` vazios nunca chamam `_narrate` (sem custo em cima de "Nenhum resultado.").
- O `asyncio.to_thread` é a única forma de chamar `suggestions.narrate` a partir do turno — nunca uma chamada síncrona direta dentro de uma corrotina.

### Validação e erros
- `_narrate` nunca propaga exceção (a chamada em si já não lança, por `narrate` do ticket 163; o helper não precisa de `try/except` próprio).
- Reply sempre não-vazia: se `_narrate` falhar E a frase-molde não se aplicar (não é o caso aqui, molde é sempre determinístico), cai no `base` de sempre.

## Especificação técnica

```
modificar julius/bot/turn.py — NARRATE_FULL_MAX_RECORDS/GROUPS, _narrate, _render_output (async), handle_text (await)
modificar tests/test_bot_turn.py — testes de composição Modo A/B com e sem client
```

### Padrão a seguir
- `handle_text` já é `async def` e já `await`s `agent.run` — o padrão de corrotina já existe neste arquivo, só falta a segunda chamada.
- `deps.client is None` como sinal de "sem IA" é o mesmo padrão que `Config.ai_configured`/`suggestions.is_available` já usam em outros lugares do bot — não duplique a checagem de orçamento aqui, `_ask` (dentro de `narrate`) já cuida disso.

## Testes obrigatórios

1. `test_search_reply_uses_the_persona_when_small_and_a_client_is_configured` — poucos registros, client com resposta válida → `reply.text` é a narração, sem `<pre>`.
2. `test_search_reply_falls_back_to_a_julius_line_when_the_model_fails` — client sem script válido / guarda rejeita → `reply.text == search_fallback_line(records)`, **não** a tabela.
3. `test_search_reply_above_the_cutoff_uses_comment_plus_table` — mais de `NARRATE_FULL_MAX_RECORDS` registros → tabela presente, comentário prependado quando o client responde.
4. `test_search_reply_without_a_client_is_unchanged` — `deps.client is None` → texto idêntico ao comportamento pré-167 (a tabela de sempre).
5. Os quatro testes espelhados para `StoreComparison` (poucos grupos / muitos grupos / sem client / sem grupo comparável).
6. `test_product_listing_gets_a_comment_but_keeps_the_table` / `test_store_listing_gets_a_comment_but_keeps_the_table`.
7. `test_search_reply_with_no_results_never_calls_narrate` / equivalente para comparação sem grupos.
8. Toda a suíte anterior de `test_bot_turn.py` (budget, histórico, pendência, prosa solta) continua verde sem edição.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "asyncio.to_thread" julius/bot/turn.py` mostra exatamente uma ocorrência (dentro de `_narrate`).
- [ ] Nenhum teste existente de `test_bot_turn.py` precisou de edição além de imports novos.

## Notas para o agente

- `NARRATE_FULL_MAX_RECORDS`/`NARRATE_FULL_MAX_GROUPS` são chute, não medição — documente isso com um comentário curto no código apontando para o smoke (169), na linha da disciplina deste projeto de nunca fingir que um número é medido quando não é.
- Não crie uma quinta função de composição genérica "para não repetir código" entre os 4 casos — a diferença de contexto/fatos/molde entre eles já é pequena o bastante para ficar direto em `_render_output`; abstrair aqui é a mesma dívida que o resto do projeto evita (ver `CLAUDE.md`, "Rejeitado explicitamente").
