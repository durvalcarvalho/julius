# 012: Serviço suggestions + repositório ai_usage

> Sugestões via LLM (fusão, conteúdo, tags) com orçamento mensal persistido e a garantia de nunca lançar exceção.

## Contexto

Regra de negócio da IA: quando pode chamar, quanto já gastou, como pergunta, como interpreta. Leia no `CLAUDE.md`: "Camada opcional de IA" inteira (orçamento US$1/mês, "nunca em `consultar`", separação rede × orçamento) e "Identidade de produto e busca" (o que é sugestão vs. decisão).

Depende de 011 (`LlmClient`/`LlmResponse`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/repositories/ai_usage.py`: `spent_in_month(conn, month: str) -> float` (0.0 se não há linha), `add_spent(conn, month: str, usd: float) -> None` (upsert acumulando).
- `julius/services/suggestions.py` com `is_available`, `suggest_merge`, `suggest_content`, `suggest_tags`.
- `tests/test_repositories_ai_usage.py`, `tests/test_services_suggestions.py`.

### Fora
- Chamar essas funções no `importar` (questão em aberto no `CLAUDE.md` — não ligar ainda). `compare_products` e CLI → 013. Escolher provedor/modelo.

## Requisitos

### Funcionais (assinaturas)
- `is_available(conn, config: Config, month: str | None = None) -> bool` — `config.ai_configured` **e** os dois preços por token configurados **e** `spent_in_month(month) < config.ai_budget_usd`. `month` default = mês corrente `YYYY-MM` (`datetime.now()`); parâmetro existe para teste.
- `suggest_merge(conn, config, client: LlmClient, description_a: str, description_b: str, month=None) -> MergeSuggestion | None`
- `suggest_content(conn, config, client, description: str, month=None) -> ContentSuggestion | None`
- `suggest_tags(conn, config, client, description: str, existing_tags: list[str], month=None) -> list[str]`
- Fluxo comum interno: se não disponível → `None`/`[]` **sem chamar o cliente**; `client.complete(system, user)`; `None` → `None`; calcular custo `input_tokens/1e6 * ai_input_price + output_tokens/1e6 * ai_output_price` e `add_spent` **antes** de interpretar a resposta (pagou, registra); extrair o primeiro bloco JSON do texto (tolerar cercas de código); validar campos; inválido → `None`/`[]`.
- Prompts em português, pedindo **somente JSON**: fusão → `{"same_product": bool, "confidence": 0..1, "rationale": str}`; conteúdo → `{"quantity": number, "unit": "L"|"KG"|"UN", "confidence": 0..1}` (unidade fora da lista ou `quantity <= 0` → `None`); tags → lista de strings, filtradas com `strip().lower()`, sem vazias/duplicadas, no máximo 3, preferindo as de `existing_tags`.

### Validação e erros
- **Nenhuma** das quatro funções lança: qualquer exceção interna (inclusive do cliente ou do banco) vira `None`/`[]`. `is_available` também nunca lança.

## Especificação técnica

```
criar julius/repositories/ai_usage.py
criar julius/services/suggestions.py
criar tests/test_repositories_ai_usage.py
criar tests/test_services_suggestions.py
```

Imports em `services/suggestions.py`: `json`, `re`, `datetime`, `sqlite3`, `julius.config`, `julius.domain.models`, `julius.infra.llm_client` (só tipos), `julius.repositories.ai_usage`.

## Testes obrigatórios

Repositório:
1. `test_spent_in_month_defaults_to_zero`
2. `test_add_spent_accumulates_within_month_and_isolates_months`

Serviço (com `FakeLlmClient` que devolve `LlmResponse` fixo ou `None` e registra chamadas; `Config` construído à mão com preços `1.0` por 1M para conta redonda):
3. `test_unavailable_without_api_key_and_client_not_called`
4. `test_unavailable_without_token_prices`
5. `test_unavailable_when_budget_reached` — `add_spent(month, 1.0)` com budget `1.0` → `False`, cliente não chamado.
6. `test_suggest_merge_parses_json_and_records_cost` — resposta com 1000/500 tokens → `spent_in_month` = `0.0015`.
7. `test_suggest_merge_tolerates_code_fences`
8. `test_malformed_json_returns_none_but_cost_is_recorded`
9. `test_client_none_returns_none_and_nothing_recorded`
10. `test_suggest_content_rejects_bad_unit_and_non_positive`
11. `test_suggest_tags_normalizes_dedups_and_caps_at_three`
12. `test_functions_never_raise_when_client_raises` — fake com `raise RuntimeError` → `None`/`[]`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; zero rede.
- [ ] `grep -n "search" julius/services/suggestions.py` vazio (nenhum acoplamento com a busca).

## Notas para o agente
- Registre o gasto **antes** de validar a resposta — o teste 8 existe exatamente para isso.
- `month` como parâmetro opcional evita `freezegun`; não adicione dependência.
