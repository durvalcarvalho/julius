# 107: `suggestions` — núcleo `_ask` (retry, custo por tentativa, log) e `suggest_merges`

> Reescreve o miolo do serviço de IA: uma função `_ask` que checa orçamento, tenta até 2 vezes, cobra cada tentativa, grava uma linha de log por tentativa e devolve JSON parseado; `suggest_merges` em lote com o prompt v2 (few-shot, `rationale` antes da decisão). `compare_products` passa a usá-la.

## Contexto

`docs/design/ai-v2.md` §4.5, §4.4 (campos do log), §6.2 (prompt), e a pesquisa (`claudedocs/research_llm_integration_best_practices_20260915.md` §3–§5). O gate T4 validou o formato `{"pairs": [...]}` com `deepseek-flash`. `suggest_content`/`suggest_tags` (sem chamador) saem neste ticket; as substitutas chegam no 108.

Depende de 106 (`LlmResponse.error`, `ScriptedLlmClient`) e 105 (`ai_log`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/services/suggestions.py`: constantes `PROMPT_VERSIONS`, `SYSTEM_PROMPTS`, `MAX_ATTEMPTS = 2`; `_ask`; `suggest_merges`; `spent_this_month`; **remover** `suggest_merge`, `suggest_content`, `suggest_tags`, `_JSON_BLOCK`, `_MAX_TAGS`, `_CONTENT_UNITS`.
- `julius/services/catalog.py::compare_products` → `suggestions.suggest_merges(conn, config, client, [(a.canonical_name, b.canonical_name)])[0]`.
- `tests/test_services_suggestions.py` reescrito; `tests/test_services_catalog.py` ajustado.

### Fora
- `enrich_products`/`match_products` e seus modelos (→ 108). CLI (→ 111). Cache de respostas.

## Requisitos

### Funcionais
- `PROMPT_VERSIONS = {"merge": "2"}` (108 adiciona `enrich`/`match`). `SYSTEM_PROMPTS["merge"]` = texto exato de §6.2 do design (SYSTEM), incluindo os 3 exemplos few-shot com o negativo `AVEIA FINO` × `REGU`.
- `is_available(conn, config, month=None)` inalterado. Novo `spent_this_month(conn, month: str | None = None) -> float` (wrapper de `ai_usage.spent_in_month` com o mês corrente; para a mensagem de orçamento na CLI, que não pode importar `repositories`).
- `_ask(conn, config, client, call_kind, user_prompt, *, max_tokens, month=None) -> object | None`:
  1. `not config.ai_configured` ou preços ausentes → `None`, **sem** log (nada a observar).
  2. Orçamento estourado → `ai_log.append(config.ai_log_path, {…, "attempt": 0, "error": "budget_exhausted", tokens 0, cost 0})` → `None`.
  3. Para `attempt` em `1..MAX_ATTEMPTS`: mede `time.monotonic()`; chama `client.complete(SYSTEM_PROMPTS[call_kind], user_prompt, max_tokens=max_tokens)` dentro de `try` (exceção → `LlmResponse("", 0, 0, error=f"client raised {type(exc).__name__}")`); `cost = in/1e6*price_in + out/1e6*price_out`; se `cost > 0`: `with conn: ai_usage.add_spent(conn, month, cost)` (**paga-se cada tentativa, inclusive as truncadas**); se `response.error is None`: `json.loads(response.text)` (`ValueError` → `error = "invalid json"`); grava a linha de log; se `error is None` → devolve o parseado; senão próxima tentativa.
  4. Esgotou → `None`.
- Linha de log (chaves exatas): `ts` (ISO 8601 com segundos, hora local), `call_kind`, `prompt_version`, `model` (`config.ai_model`), `attempt`, `user_prompt`, `raw_response` (`response.text`), `parsed_ok` (bool), `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms` (int), `error` (str ou `None`). `system_prompt` **não** vai (reconstruível por `call_kind`+`prompt_version`).
- `suggest_merges(conn, config, client, pairs: Sequence[tuple[str, str]], month=None) -> list[MergeSuggestion | None]`:
  - `pairs` vazio → `[]` sem chamada.
  - User prompt: uma linha por par, `f"{i} | A: {a} | B: {b}"`, `i` a partir de 1. `max_tokens = 80 * len(pairs) + 100`.
  - Resposta esperada `{"pairs": [{"id", "rationale", "same_product", "confidence"}]}`. Resultado tem `len(pairs)` posições; posição `i-1` recebe `MergeSuggestion` se o item com aquele `id` existe e valida: `same_product` é `bool` (não aceitar `"true"`/`1`), `confidence` numérico em `[0, 1]`, `rationale` string (pode ser vazia). Senão `None` naquela posição — **um item ruim não derruba o lote**.
  - Qualquer exceção interna → lista de `None` (nunca lança).
- `compare_products`: comportamento externo idêntico ao atual (`ai_suggestion` é `MergeSuggestion | None`).

### Validação e erros
- Nenhuma função pública lança. `is_available` em conexão fechada → `False` (teste existente).

## Especificação técnica

```
modificar julius/services/suggestions.py       (reescrever; mantém is_available)
modificar julius/services/catalog.py           (1 linha)
modificar tests/test_services_suggestions.py   (reescrever com ScriptedLlmClient de tests/_fakes.py)
modificar tests/test_services_catalog.py
```

Imports novos em `suggestions.py`: `time`, `julius.infra.ai_log`. Camada `services` pode importar `infra` (regra da DAG).

## Testes obrigatórios (`tests/test_services_suggestions.py`; `CONFIG` com `db_path=tmp_path/"prices.db"` para o log cair em `tmp_path`)

1. `test_not_configured_returns_none_without_call_or_log_line`
2. `test_budget_exhausted_logs_one_line_and_does_not_call` — `error == "budget_exhausted"`, `attempt == 0`.
3. `test_suggest_merges_parses_batch_in_order_and_records_cost` — 3 pares, resposta fora de ordem (`id` 3,1,2) → posições certas; `spent_in_month == tokens × preços`.
4. `test_invalid_json_then_valid_retries_once_and_charges_both` — 1ª resposta `"não sei"`, 2ª válida → resultado ok, `len(calls) == 2`, 2 linhas de log (`attempt` 1 e 2, `parsed_ok` False/True), gasto = soma.
5. `test_two_failures_return_none_for_every_pair_after_two_calls`.
6. `test_transport_error_is_logged_with_error_text` — `LlmResponse("", 0, 0, error="HTTP 429")` → linha com `error == "HTTP 429"`, `cost_usd == 0`.
7. `test_truncated_response_is_charged` — `LlmResponse("", 1200, 1200, error="finish_reason length")` duas vezes → `None`s, gasto > 0 (caso real do gate).
8. `test_client_raising_never_propagates_and_is_logged_as_client_raised`.
9. `test_item_with_invalid_fields_becomes_none_but_others_survive` — `confidence: 1.5` e `same_product: "sim"` → `None` só neles.
10. `test_log_line_has_exact_keys` — conjunto de chaves igual ao contrato acima.
11. `test_max_tokens_scales_with_pair_count` — 4 pares → `calls[0][2] == 420`.
12. `test_empty_pairs_returns_empty_without_call`.
13. `test_merge_prompt_asks_for_rationale_before_decision` — no `SYSTEM_PROMPTS["merge"]`, índice de `"rationale"` < índice de `"same_product"` na linha de formato.
14. `test_spent_this_month_reads_current_month`.
15. `test_services_catalog.py::test_compare_products_uses_batch_merge_and_returns_first` (ajuste do teste existente).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "suggest_merge\b\|suggest_content\|suggest_tags\|_JSON_BLOCK" julius/ -r` vazio.
- [ ] `tail -n 1 ~/.local/share/julius/ai_calls.jsonl` após um `julius produtos comparar 63 69` real mostra a linha com `call_kind: "merge"` e `parsed_ok: true` (teste manual do usuário; anote no commit se foi feito).

## Notas para o agente
- Prompt é constante de módulo com `PROMPT_VERSIONS`; quem editar o texto muda a versão. Sem isso comparar logs "antes × depois" é anedota.
- `json.loads` fica **dentro** do `try` de `_ask`; é o pitfall nº 1 da pesquisa.
- Não reintroduza extração por regex: se o provedor não obedece JSON mode, o log vai mostrar `invalid json` e é isso que queremos ver.
