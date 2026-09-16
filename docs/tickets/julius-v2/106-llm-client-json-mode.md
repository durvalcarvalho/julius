# 106: Cliente LLM — JSON mode, `max_tokens`, extras e `LlmResponse.error`

> `HttpLlmClient` pede JSON estruturado, fixa `max_tokens`, mescla os extras da config e nunca mais devolve `None`: toda falha vira `LlmResponse` com `error` preenchido (e tokens contabilizados quando houve resposta).

## Contexto

`docs/design/ai-v2.md` §4.3 e §1.1. Achados do gate que este ticket materializa: (a) `response_format json_object` funciona na DeepSeek; (b) com thinking ligado a resposta vem com `finish_reason: length` e `content` vazio **mas com `usage`** — pagou-se e nada veio, então isso é erro com custo; (c) `thinking: disabled` é aceito e vai via `ai_request_extras`. O `error` textual é o que o log (→ 107) precisa para distinguir 401 de timeout de resposta truncada.

Depende de 105 (`ai_request_extras`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/infra/llm_client.py`: `LlmResponse.error`, nova assinatura de `complete`, corpo do request, mapa de falhas, `request_extras` no construtor e em `from_config`.
- Ajuste **mínimo** para a suíte continuar verde: `julius/services/suggestions.py::_ask` passa `max_tokens=300` e trata `response.error` como "sem resposta"; fakes em `tests/test_services_suggestions.py` e `tests/test_services_catalog.py` adotam a nova assinatura.
- Novo `tests/_fakes.py` com `ScriptedLlmClient` (reutilizado por 107–114).
- `tests/test_llm_client.py` reescrito.

### Fora
- Retry, log, prompts, custo (→ 107). Remover/adicionar funções de `suggestions` (→ 107/108).

## Requisitos

### Funcionais
- `LlmResponse(text: str, input_tokens: int, output_tokens: int, error: str | None = None)` — continua em `infra/llm_client.py`. Contrato: `error` preenchido ⇒ `text == ""`; tokens podem ser > 0 (houve resposta cobrada).
- `class LlmClient(Protocol): def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> LlmResponse` — docstring: "Never raises and never returns None; failures come back as `error`."
- `HttpLlmClient.__init__(base_url, api_key, model, timeout_seconds=30.0, request_extras: Mapping[str, object] | None = None)`; `from_config` passa `config.ai_request_extras`.
- Corpo do POST, nesta ordem lógica: `model`, `messages` (system, user), `temperature: 0`, `max_tokens`, `response_format: {"type": "json_object"}`, depois `body.update(request_extras)` (extras podem sobrescrever qualquer chave — documentado no docstring).
- Mapa de falhas → `error` (strings curtas, estáveis, em inglês):

  | situação | `error` | tokens |
  |---|---|---|
  | `HTTPError` (4xx/5xx) | `"HTTP {code}"` | 0 |
  | status fora de 2xx sem exceção | `"HTTP {status}"` | 0 |
  | `TimeoutError`/`socket.timeout` | `"timeout"` | 0 |
  | `URLError` | `"network: {reason}"` | 0 |
  | corpo não é JSON | `"invalid json body"` | 0 |
  | sem `choices`/vazio | `"no choices"` | do `usage` se houver |
  | sem `usage` | `"no usage"` | 0 |
  | `finish_reason` presente e ≠ `"stop"` | `"finish_reason {valor}"` | do `usage` |
  | `content` ausente, `None`, não-string ou vazio/só espaços | `"empty content"` | do `usage` |
  | qualquer outra exceção | `"{TypeName}: {mensagem}"[:200]` | 0 |
- Sucesso: `LlmResponse(content, prompt_tokens, completion_tokens)`.
- `tests/_fakes.py::ScriptedLlmClient(responses: Sequence[LlmResponse] = (), *, by_kind: Mapping[str, LlmResponse] | None = None)`: `complete` grava `calls: list[tuple[str, str, int]]` (system, user, max_tokens) e devolve, em ordem, os `responses` (repetindo o último quando acabam); com `by_kind`, escolhe pela marca no **system prompt**: `'"products"' → "enrich"`, `'"pairs"' → "merge"`, `'"ids"' → "match"` (as três chaves do formato JSON de cada prompt, §6 do design). Também `RaisingLlmClient` (lança `RuntimeError`).

### Validação e erros
- `complete` **nunca** lança — teste com `RuntimeError` inesperado dentro de `urlopen`.

## Especificação técnica

```
modificar julius/infra/llm_client.py
modificar julius/services/suggestions.py        (só _ask: max_tokens=300, `if response.error: return None`)
criar     tests/_fakes.py
modificar tests/test_llm_client.py              (reescrever)
modificar tests/test_services_suggestions.py    (fake → ScriptedLlmClient; "client None" vira "client error")
modificar tests/test_services_catalog.py        (fake → ScriptedLlmClient)
```

## Testes obrigatórios (`tests/test_llm_client.py`)

1. `test_complete_parses_text_and_token_counts` — `LlmResponse("hello", 12, 3)` sem `error`.
2. `test_body_has_json_mode_max_tokens_temperature_and_messages`.
3. `test_request_extras_are_merged_into_body_and_can_override` — extras `{"thinking": {"type": "disabled"}, "temperature": 0.2}` → ambos no corpo.
4. `test_from_config_passes_request_extras`.
5. `test_http_error_maps_to_http_code` — 500 → `"HTTP 500"`, text `""`, tokens 0.
6. `test_timeout_and_network_errors` — parametrizado: `TimeoutError()` → `"timeout"`; `URLError("dns down")` → começa com `"network:"`.
7. `test_non_2xx_status_without_exception` — 429 → `"HTTP 429"`.
8. `test_invalid_json_body`.
9. `test_finish_reason_length_is_error_but_keeps_tokens` — payload com `finish_reason: "length"`, `content: ""`, `usage {prompt_tokens: 1200, completion_tokens: 1200}` → `error == "finish_reason length"`, `input_tokens == 1200`, `output_tokens == 1200` (o caso real do gate T3).
10. `test_empty_content_is_error_with_tokens` — `content: None` e `content: "   "`.
11. `test_missing_usage_and_missing_choices` — `"no usage"` / `"no choices"`.
12. `test_unexpected_exception_never_propagates` — `RuntimeError("unexpected")` → `error == "RuntimeError: unexpected"`.
13. `test_from_config_returns_none_when_not_configured` (existente).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (inclusive `tests/test_services_suggestions.py` e `tests/test_services_catalog.py` com o fake novo).
- [ ] `grep -n "return None" julius/infra/llm_client.py` só em `from_config`.

## Notas para o agente
- Não adicione `requests`/`httpx`: continua `urllib.request` (stdlib), decisão do `CLAUDE.md`.
- Não tente extrair JSON de dentro de texto no cliente: isso é o que JSON mode elimina; o serviço faz `json.loads` direto (→ 107).
- `HTTPError` tem `.code`; o corpo do erro não vai no `error` (pode ter tamanho arbitrário) — o log crua da resposta é do serviço.
