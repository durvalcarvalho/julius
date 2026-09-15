# 013: Comparar produtos (serviço + CLI)

> `catalog.compare_products` dá uma opinião sobre dois produtos serem a mesma coisa — similaridade de texto sempre, IA se disponível — e `julius produtos comparar` a exibe. Nunca funde.

## Contexto

Único ponto de IA acionado pelo usuário sob demanda. Leia no `CLAUDE.md`: "Identidade de produto e busca § 1" (reconciliação: sugestão pedida ≠ sugestão automática), "Camada opcional de IA § Módulo novo".

Depende de 007 (`catalog`), 010 (`cli/products.py`), 012 (`suggestions`), e de `normalize_text` (006). Regras comuns: `index.md`.

## Escopo

### Dentro
- `compare_products(conn, config: Config, client: LlmClient | None, id_a: int, id_b: int) -> ProductComparison` em `julius/services/catalog.py`.
- Comando `comparar ID_A ID_B` em `julius/cli/products.py`.
- Testes em `tests/test_services_catalog.py` e `tests/test_cli_catalog.py` (acrescentar).

### Fora
- Fundir automaticamente (proibido por design). Sugestão em `consultar`.

## Requisitos

### Funcionais
- `text_similarity = rapidfuzz.fuzz.token_set_ratio(normalize_text(a), normalize_text(b)) / 100` — sempre calculada.
- `ai_suggestion = suggestions.suggest_merge(...)` só se `client is not None` **e** `suggestions.is_available(...)`; senão `None`.
- CLI: monta `client = HttpLlmClient.from_config(config)` (pode ser `None`); imprime os dois nomes, `"Similaridade de texto: 87%"`, e ou `"IA: mesmo produto (confiança 0.9) — {rationale}"` / `"IA: produtos diferentes …"`, ou `"IA indisponível (não configurada ou orçamento do mês esgotado) — só similaridade de texto."`. Termina com `"Para fundir: julius produtos fundir {a} {b}"`.

### Validação e erros
- `id_a == id_b` → `ValueError`; id inexistente → `LookupError`; na CLI viram `fail(...)`.

## Especificação técnica

```
modificar julius/services/catalog.py
modificar julius/cli/products.py
modificar tests/test_services_catalog.py
modificar tests/test_cli_catalog.py
```

## Testes obrigatórios

1. `test_compare_returns_text_similarity_without_client` — `client=None` → `ai_suggestion is None`, `0 <= text_similarity <= 1`; tomates reais (cód. 22039 × 7147) têm similaridade alta (`> 0.7`).
2. `test_compare_uses_ai_when_available` — `FakeLlmClient` + config completo → `ai_suggestion` preenchido.
3. `test_compare_skips_ai_when_budget_exhausted`
4. `test_compare_same_id_raises` · `test_compare_unknown_id_raises`
5. CLI: `test_produtos_comparar_without_ai_prints_similarity_and_hint` — env sem `JULIUS_AI_*` → saída contém `"Similaridade de texto"`, `"IA indisponível"` e `"produtos fundir"`; nada foi fundido (`produtos listar` inalterado).
6. CLI: `test_produtos_comparar_unknown_id_exits_1`

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; zero rede.
- [ ] `grep -n "merge_products" julius/services/catalog.py` mostra que `compare_products` não a chama.

## Notas para o agente
- A CLI é o único lugar que instancia `HttpLlmClient`; o serviço recebe o `client` já pronto (ou `None`).
- Não formate `confidence` como porcentagem — é `0..1`, mostre com uma casa.
