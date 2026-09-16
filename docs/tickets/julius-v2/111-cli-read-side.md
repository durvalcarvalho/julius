# 111: CLI — endereço em `mercados listar`/`consultar`, fallback de IA na consulta, `comparar` com três motivos, `tag --remover`

> O lado "leitura" da v2: o usuário vê onde pagou, a consulta que deu vazio tenta a IA uma vez, `comparar` explica por que a IA ficou calada e uma tag errada pode ser removida pelo CLI.

## Contexto

`docs/design/ai-v2.md` §5.2, §5.3 (célula Mercado em duas linhas), §4.7 (`FOUND_VIA_AI`). Regra que não muda: `consultar` com resultado **nunca** chama IA; o fallback só roda quando a busca determinística veio vazia.

Depende de 104 (`untag_product`), 108 (`match_products`), 110 (`records_for_products`, `catalog_for_matching`, `after_ai_fallback`, textos). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/cli/stores.py`: coluna **Endereço** em `listar`.
- `julius/cli/receipts.py`: célula Mercado com endereço; fallback de IA em `search`.
- `julius/cli/products.py`: `comparar` com três mensagens; `tag --remover`.
- Testes: `tests/test_cli_catalog.py`, `tests/test_cli_receipts.py`.

### Fora
- Revisão/curadoria e `importar` (→ 112, 113). `exportar` (já feito em 103). Cache de fallback.

## Requisitos

### Funcionais
- `mercados listar`: colunas `CNPJ | Razão social | Apelido | Endereço` (`store.address or ""`).
- `consultar`, célula Mercado: quando `record.store_address` existe, `Text.assemble(record.store_nickname, "\n", (record.store_address, "dim"))`; senão só o apelido. Demais colunas inalteradas (os testes existentes de tabela continuam verdes).
- `consultar`, fallback (só quando `records` vazio **e** `term is not None` **e** `tag is None`): `settings = config.load()`; `client = HttpLlmClient.from_config(settings)`; se `client` e `suggestions.is_available(conn, settings)`: `ids = suggestions.match_products(conn, settings, client, term, search_service.catalog_for_matching(conn))`; se `ids`: `records = search_service.records_for_products(conn, ids, limit)` e `hints = guidance.after_ai_fallback(records)`; senão `hints = guidance.after_search(...)` como hoje. Tabelas e dicas impressas do mesmo jeito de sempre. IA indisponível/erro → comportamento atual, sem mensagem extra (o log conta a história).
- `produtos comparar`, quando `comparison.ai_suggestion is None`, exatamente uma destas linhas:
  1. `not settings.ai_configured` → dica `AI_NOT_CONFIGURED` (como hoje, via `guidance.for_compare`).
  2. `settings.ai_configured and not suggestions.is_available(conn, settings)` → `IA indisponível: orçamento do mês esgotado (US$ {gasto:.2f} de US$ {teto:.2f}).` com `gasto = suggestions.spent_this_month(conn)`.
  3. Senão → `IA indisponível: a chamada falhou — veja {settings.ai_log_path}.`
- `produtos tag ID TAG --remover`: opção booleana `--remover`; chama `catalog.untag_product`; imprime `Tag '{tag}' removida do produto {id}.`; `LookupError`/`ValueError` → `fail` (exit 1), mesma convenção dos outros comandos. Sem `--remover`, comportamento atual.

### Validação e erros
- `consultar --tag inexistente` continua sem chamar IA (dica `UNKNOWN_TAG`).
- Falha na IA nunca muda exit code nem esconde a saída principal.

## Especificação técnica

```
modificar julius/cli/stores.py
modificar julius/cli/receipts.py        (import de HttpLlmClient, config, suggestions; _table; search)
modificar julius/cli/products.py
modificar tests/test_cli_catalog.py
modificar tests/test_cli_receipts.py
```

Injeção do fake nos testes de CLI: `monkeypatch.setattr(julius.cli.receipts, "HttpLlmClient", StubFactory)` onde `StubFactory.from_config(config)` devolve o `ScriptedLlmClient` (ou `None`). A CLI **deve** referenciar `HttpLlmClient` pelo atributo do módulo (já é assim em `products.py`). Variáveis `JULIUS_AI_*` setadas via `monkeypatch.setenv` com preços `1.0`.

## Testes obrigatórios

1. `test_cli_catalog.py::test_mercados_listar_shows_address_column` — `qrcode-3.html` → `Endereço` e `GUARA II` na saída.
2. `test_cli_receipts.py::test_consultar_shows_store_address_under_nickname` — linha com o apelido seguida de linha com `GUARA II`.
3. `test_consultar_ai_fallback_finds_products_and_prints_hint` — `qrcode.html`; termo `carne` (a busca por texto não acha, caso documentado); fake `match` devolve o id de `PICANHA` → tabela `Preços por KG` com `PICANHA` + `Dica: Encontrado pela IA`; `len(fake.calls) == 1`.
4. `test_consultar_does_not_call_ai_when_there_are_results` — termo `picanha` → `fake.calls == []`.
5. `test_consultar_ai_fallback_with_no_ids_keeps_regular_hints` — fake devolve `{"ids": []}` → dica `NO_MATCH_TRY_TAGS`/`DID_YOU_MEAN` como antes.
6. `test_consultar_with_tag_never_calls_ai` — `consultar carne --tag x` → `fake.calls == []`.
7. `test_consultar_without_ai_configured_is_unchanged` — `from_config` → `None`.
8. `test_cli_catalog.py::test_comparar_budget_exhausted_message` — `JULIUS_AI_BUDGET_USD=0` → contém `orçamento do mês esgotado` e `US$ 0.00 de US$ 0.00` (dólar com ponto decimal; **não** use `_money`, que é para reais).
9. `test_comparar_call_failure_points_to_log` — fake com `error="HTTP 500"` (duas vezes) → contém `ai_calls.jsonl`.
10. `test_comparar_without_ai_shows_env_var_names` — existente.
11. `test_tag_remover_removes_and_reports` e `test_tag_remover_missing_link_exits_1`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `julius consultar picanha` num banco com endereço mostra o endereço em `dim` embaixo do apelido, mesma quantidade de colunas de antes.
- [ ] `tests/test_cli.py::test_importing_the_cli_has_no_side_effects_on_disk` continua verde (nenhuma conexão/`config.load()` em import).

## Notas para o agente
- `config.load()` e `HttpLlmClient.from_config` só dentro do handler, depois de saber que o resultado veio vazio — nada em tempo de import.
- Não adicione `--sem-ia`: sem `JULIUS_AI_API_KEY` já não há IA; é a decisão D4 dos requisitos.
- Não reordene colunas de `consultar`; o endereço vive dentro da célula Mercado.
