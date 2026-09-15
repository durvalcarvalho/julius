# 011: Cliente HTTP de LLM

> `HttpLlmClient` implementa o `Protocol LlmClient` contra um endpoint `/chat/completions` genérico, com `urllib` da stdlib, e **nunca lança**.

## Contexto

Camada `infra`. O `Protocol LlmClient` e o `LlmResponse` já existem em `julius/infra/llm_client.py`. Orçamento, prompts e interpretação de resposta **não** ficam aqui (→ 012). Leia no `CLAUDE.md`: "Camada opcional de IA" (por que `urllib`, por que `/chat/completions`, invariante "nunca lança").

Sem dependência de outro ticket. Regras comuns: `index.md`.

## Escopo

### Dentro
- `class HttpLlmClient` no mesmo módulo `julius/infra/llm_client.py`, e `tests/test_llm_client.py`.

### Fora
- Checar orçamento, montar prompts de domínio, parsear JSON de negócio → 012. Streaming. Retry/backoff. SDKs de provedor.

## Requisitos

### Funcionais
- `HttpLlmClient(base_url: str, api_key: str, model: str, timeout_seconds: float = 30.0)`.
- `@classmethod from_config(cls, config: Config) -> HttpLlmClient | None` — `None` se `not config.ai_configured`.
- `complete(system_prompt, user_prompt) -> LlmResponse | None`: `POST {base_url.rstrip("/")}/chat/completions`, headers `Authorization: Bearer {api_key}`, `Content-Type: application/json`; corpo `{"model": …, "messages": [{"role":"system","content":…},{"role":"user","content":…}], "temperature": 0}`. Resposta: `text = choices[0].message.content`, `input_tokens = usage.prompt_tokens`, `output_tokens = usage.completion_tokens`.
- Módulo faz `from urllib.request import Request, urlopen` no topo — os testes substituem `julius.infra.llm_client.urlopen` via `monkeypatch`.

### Validação e erros
- **Qualquer** exceção (`HTTPError`, `URLError`, timeout, JSON inválido, chave ausente em `choices`/`usage`, `content` não-string) → retorna `None`. Sem `usage` → `None` (sem contagem de tokens não dá para debitar orçamento; melhor não sugerir do que gastar sem registrar).
- Status HTTP fora de 2xx → `None`.

## Especificação técnica

```
modificar julius/infra/llm_client.py     # + HttpLlmClient
criar     tests/test_llm_client.py
```

Imports: `json`, `urllib.request`, `urllib.error`, `dataclasses`, `typing`, `julius.config` (para `from_config`). `infra` pode importar `config` pela DAG.

## Testes obrigatórios (fake de `urlopen` que devolve objeto com `read()`, `status` e suporte a `with`)

1. `test_complete_parses_text_and_token_counts`
2. `test_complete_sends_expected_url_headers_and_body` — captura o `Request`: URL termina em `/chat/completions` (com `base_url` terminando ou não em `/`), `Authorization` correto, corpo JSON com `model` e as duas mensagens na ordem, `timeout` repassado.
3. `test_http_error_returns_none` — fake levanta `urllib.error.HTTPError(…, 500, …)`.
4. `test_network_error_returns_none` — `URLError`.
5. `test_invalid_json_returns_none`
6. `test_missing_usage_returns_none`
7. `test_missing_choices_returns_none`
8. `test_from_config_returns_none_when_not_configured` e `test_from_config_builds_client_when_configured`.
9. `test_complete_never_raises_even_on_unexpected_exception` — fake levanta `RuntimeError` → `None`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; nenhum teste toca a rede.
- [ ] Nenhuma dependência nova no `pyproject.toml`.

## Notas para o agente
- Não use `requests`/`httpx` — decisão registrada no `CLAUDE.md`.
- Não logue o `api_key` em mensagem nenhuma, nem em exceção engolida.
