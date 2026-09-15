# 016: CLI — dicas de uso

> Traduz cada `HintKind` numa frase em português com o comando pronto, e liga as dicas em `consultar`, `importar` e `produtos comparar`.

## Contexto

Metade "texto" do módulo de dicas; a metade "dado" é o 015. Leia no `CLAUDE.md`: **"Dicas de uso (`guidance`) — v1.1"** (a tabela do catálogo tem a frase-modelo de cada kind — use-a como base, ajustando só o que ficar melhor em tela).

Depende de 015. Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/cli/_hints.py`: `TEXTS: dict[HintKind, str]` (templates; `{details}` já formatado como lista separada por `, `) e `print_hints(hints, *, to_stderr=False)`.
- `julius/cli/receipts.py`: `consultar` chama `guidance.after_search` e imprime; `importar` chama `guidance.after_import` após cada sucesso e `guidance.for_import_error` após cada falha (este em `stderr`). **Remover** a checagem ad hoc `has_imports`/`catalog.list_stores` — `NO_RECEIPTS_IMPORTED` a substitui.
- `julius/cli/products.py`: `comparar` imprime `guidance.for_compare(config)` no lugar da frase fixa "IA indisponível…" quando a causa é configuração ausente (orçamento esgotado continua com a frase atual, porque não é dica de configuração).
- Testes em `tests/test_cli_receipts.py`, `tests/test_cli_catalog.py` e novo `tests/test_cli_hints.py`.

### Fora
- Novos kinds. Dicas em `exportar`, `mercados`, `produtos listar/renomear/tag/fundir`. Cores além de `dim`. Flag pra desligar dicas.

## Requisitos

### Funcionais
- Formato: cada dica numa linha própria, `Dica: <frase>`, estilo `dim` (rich). Depois da saída normal do comando; nunca antes.
- `consultar`: resultado vazio → imprime `Nenhum resultado.` **só se** nenhuma dica cobriu o caso (com `NO_RECEIPTS_IMPORTED`, `NO_MATCH_*` ou `UNKNOWN_TAG` presentes, a dica substitui a frase). Exit code continua 0.
- `importar`: após `"{nome}: N itens novos, M já existiam"`, as dicas de `after_import`; após `"{nome}: erro — …"` em `stderr`, as dicas de `for_import_error` também em `stderr`. Exit codes inalterados.
- `comparar`: sem IA configurada → frase da dica `AI_NOT_CONFIGURED`; com IA configurada mas indisponível por orçamento → frase atual.
- `TEXTS` cobre todos os `HintKind`; `print_hints` ignora silenciosamente um kind sem texto (não pode quebrar o comando), mas o teste 1 garante que isso nunca acontece.

### Validação e erros
- Falha ao gerar/imprimir dica nunca altera exit code nem suprime a saída principal.

## Especificação técnica

```
criar     julius/cli/_hints.py
modificar julius/cli/receipts.py
modificar julius/cli/products.py
criar     tests/test_cli_hints.py
modificar tests/test_cli_receipts.py
modificar tests/test_cli_catalog.py
```

## Testes obrigatórios (`CliRunner`, `JULIUS_DB` em `tmp_path`, `COLUMNS=200`)

1. `tests/test_cli_hints.py::test_every_hint_kind_has_a_text` — itera `typing.get_args(HintKind)`.
2. `test_print_hints_formats_details_and_prefix` — saída contém `Dica:` e os `details` separados por vírgula.
3. `test_consultar_empty_db_shows_import_hint_not_generic_message` — contém `julius importar`, não contém `Nenhum resultado.` (substitui o teste equivalente já existente).
4. `test_consultar_did_you_mean` — termo próximo → nome do produto na dica.
5. `test_consultar_unrelated_term_suggests_tags` — `"carne"` → menciona `produtos tag` e `consultar --tag`.
6. `test_consultar_unknown_tag_lists_existing`
7. `test_consultar_with_results_prints_no_hint` — `"picanha"` → nenhuma linha começando com `Dica:`.
8. `test_importar_first_time_suggests_store_nicknames` — contém `mercados renomear`; após renomear todas, reimportar não mostra.
9. `test_importar_new_products_with_size_suggest_content` — `qrcode-5.html` → contém `definir-conteudo`.
10. `test_importar_missing_file_hint_in_stderr` — `stderr` contém `Dica:` e menciona `*.html`; exit 1.
11. `test_importar_pdf_or_garbage_explains_not_a_receipt` — arquivo `.html` com conteúdo inválido → `stderr` contém "Salvar página".
12. `test_comparar_without_ai_shows_env_var_names` — contém `JULIUS_AI_API_KEY`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; `tests/test_cli.py::test_importing_the_cli_has_no_side_effects_on_disk` continua verde.
- [ ] `julius consultar banana` num `JULIUS_DB` novo imprime a dica de import e exit 0.
- [ ] Nenhuma dica aparece em `julius consultar picanha` com dados.

## Notas para o agente
- Templates são a única fonte de texto de dica; nada de `console.print("Dica: …")` solto nos comandos.
- Mantenha a saída principal exatamente como está — os testes existentes de tabela/contagem não podem mudar.
