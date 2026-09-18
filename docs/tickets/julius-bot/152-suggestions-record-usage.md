# 152: `suggestions.record_usage` — cobrar e logar uma chamada vira função pública

> O bot vai gastar do mesmo orçamento e escrever no mesmo log da curadoria; para isso a cobrança que hoje é privada em `_ask` precisa ter nome.

## Contexto

`docs/design/telegram-bot.md` §5.1; RNF4 dos requisitos. O bot não pode importar `repositories` (DAG, ticket 153), então cobrar `ai_usage.add_spent` e escrever a linha em `ai_calls.jsonl` precisa passar por `services`. Hoje as duas coisas acontecem dentro de `suggestions._ask` (uma vez para `budget_exhausted`, uma vez por tentativa). Este ticket extrai esse trecho numa função pública e faz `_ask` usá-la — **comportamento idêntico**, provado pelos testes que já existem.

Não depende de nenhum ticket. 159 (turno do bot) consome.

## Escopo

### Dentro
- `julius/services/suggestions.py`: `record_usage(...)`; `_ask` reescrito para chamá-la nos dois pontos; `_log` ganha `prompt_version: str | None = None`.
- `tests/test_services_suggestions.py`: testes da função nova.

### Fora
- Qualquer mudança em prompts, `PROMPT_VERSIONS`, `MAX_ATTEMPTS`, `ENRICH_BATCH_SIZE`.
- Qualquer arquivo do bot.
- Cache, retry novo, segundo contador — não existem.

## Requisitos

### Funcionais

```python
def record_usage(
    conn: sqlite3.Connection,
    config: Config,
    call_kind: str,
    *,
    attempt: int,
    user_prompt: str,
    raw_response: str | None,
    parsed_ok: bool,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    error: str | None,
    month: str | None = None,
    prompt_version: str | None = None,
) -> float:
    """Charges the month and appends one line to ai_calls.jsonl; returns the cost in USD."""
```

- Custo = `input_tokens / 1e6 * ai_input_price + output_tokens / 1e6 * ai_output_price`; se **qualquer** dos dois preços for `None`, custo `0.0` (hoje `_ask` só chega à cobrança com preços configurados; a função pública precisa ser segura sem eles).
- Cobra (`ai_usage.add_spent`, dentro de `with conn:`) **só** quando custo `> 0`. Loga **sempre**, uma linha, com as mesmas chaves de hoje (`ts`, `call_kind`, `prompt_version`, `model`, `attempt`, `user_prompt`, `raw_response`, `parsed_ok`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`, `error`).
- `prompt_version=None` → `PROMPT_VERSIONS.get(call_kind, "")` (comportamento atual); explícito → usa o valor (é assim que o bot passa a versão do prompt dele sem entrar em `PROMPT_VERSIONS`).
- `month=None` → `_current_month()`.
- `_ask` chama `record_usage` para a linha `budget_exhausted` (tokens 0, custo 0) e para cada tentativa, passando exatamente o que passa hoje para `add_spent`/`_log`.

### Validação e erros
- Mesmas garantias de hoje: `ai_log.append` nunca lança; `add_spent` roda dentro de `with conn:`.
- Nenhuma assinatura pública existente muda (`is_available`, `spent_this_month`, `suggest_*`, `enrich_products`, `match_products`).

## Especificação técnica

```
modificar julius/services/suggestions.py       — record_usage; _ask usa; _log(prompt_version=)
modificar tests/test_services_suggestions.py   — testes novos; os existentes ficam como estão
```

### Padrão a seguir
- O bloco de `_ask` entre `cost = (...)` e `_log(...)` é o corpo de `record_usage` — mova-o, não o reescreva.
- Ler a linha do log nos testes: `json.loads(config.ai_log_path.read_text().splitlines()[-1])`, como os testes de `_ask` já fazem.

## Testes obrigatórios

1. `test_record_usage_charges_and_logs` — 1000/500 tokens com preços 0.30/1.20 → retorno `0.0009` (aprox., `pytest.approx`), `ai_usage.spent_in_month` igual, uma linha nova com `call_kind` e `cost_usd`.
2. `test_record_usage_with_zero_tokens_logs_without_charging` — tokens 0 → retorno `0.0`, `ai_usage` inalterada, linha gravada com `error="budget_exhausted"`.
3. `test_record_usage_without_prices_costs_nothing` — `Config` sem preços → `0.0`, sem cobrança, linha gravada.
4. `test_record_usage_prompt_version_override` — `prompt_version="7"` aparece na linha; sem override, `PROMPT_VERSIONS["enrich"]` aparece para `call_kind="enrich"`; `call_kind` desconhecido sem override → `""`.
5. `test_record_usage_accumulates_in_the_same_month` — duas chamadas somam em `ai_usage`.
6. Todos os testes existentes de `_ask`/`suggest_merges`/`enrich_products` passam **sem edição** — é a prova de que o comportamento não mudou.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde, `tests/test_services_suggestions.py` sem nenhum teste antigo alterado.
- [ ] `grep -n "add_spent" julius/services/suggestions.py` mostra **uma** ocorrência (dentro de `record_usage`).
- [ ] `grep -n "def record_usage" julius/services/suggestions.py` existe e a função não é prefixada com `_`.

## Notas para o agente

- Não "aproveite" para tratar exceção de `add_spent` com `try/except` — `_ask` não trata hoje e o design não pediu; mudar isso é outra decisão.
- Não crie um `services/ai_budget.py`: o design pede **uma** função em `suggestions.py`, ao lado de `is_available`/`spent_this_month`, para não haver dois lugares que sabem cobrar.
