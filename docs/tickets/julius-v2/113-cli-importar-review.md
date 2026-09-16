# 113: CLI — `importar` roda a revisão dos produtos novos

> Depois de gravar todos os arquivos, `importar` chama a mesma revisão de 112 para os produtos criados naquele comando (se a IA está configurada), com `--sim` para uso sem terminal, e só então imprime as dicas — `reviewed` decide se `PRODUCTS_PENDING_REVIEW`/`PACKAGE_SIZE` aparecem.

## Contexto

`docs/design/ai-v2.md` §2 (fluxo), §5.2 (`importar`), §0 (decisão "Interação": as duas portas, um só fluxo). Invariante: **o import é gravado antes de qualquer IA**; falha de IA não desfaz nada e não muda exit code.

Depende de 112 (`review_products`, `_is_interactive`) e 110 (`after_import(reviewed=)`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/cli/receipts.py::import_receipts`: opção `--sim/-y`, chamada da revisão, `after_import(..., reviewed=...)`.
- `tests/test_cli_receipts.py`.

### Fora
- Mudar `import_receipt` (serviço). Revisar produtos antigos no `importar` (isso é `revisar`). Flag para desligar a IA.

## Requisitos

### Funcionais
- Assinatura: `import_receipts(files, yes: bool = False)` com `typer.Option("--sim", "-y", help="Aplicar as sugestões da IA sem perguntar.")`.
- Depois do loop de arquivos (que não muda: resumo por arquivo, erros em `stderr`, `failed` → exit 1):
  1. `merged = _merge(results)`; `reviewed = False`.
  2. Se `results` e `merged.new_product_ids`: `settings = config.load()`; `client = HttpLlmClient.from_config(settings)`; se `client`: `reviewed = review_products(conn, settings, client, merged.new_product_ids, assume_yes=yes, interactive=not yes and _review._is_interactive())`.
  3. `print_hints(guidance.after_import(conn, merged, reviewed=reviewed))`.
- Ordem na tela: resumos por arquivo → (revisão) → dicas. Exit code: 1 se algum arquivo falhou, senão 0 — independente da IA.
- Reimportar arquivos já conhecidos (`new_product_ids` vazio) **não** chama a IA.

### Validação e erros
- Qualquer exceção vinda da revisão (não deveria: `curation`/`suggestions` não lançam; `apply` pode) é capturada, impressa em `stderr` como `IA: erro ao aplicar sugestões — {erro}` e o comando segue para as dicas com `reviewed=False`. O import já está no banco.

## Especificação técnica

```
modificar julius/cli/receipts.py     (imports: config, HttpLlmClient, _review)
modificar tests/test_cli_receipts.py
```

## Testes obrigatórios (`tests/test_cli_receipts.py`; stub de `HttpLlmClient` em `julius.cli.receipts`; `_review._is_interactive` → `False` por padrão nestes testes)

1. `test_importar_reviews_new_products_when_ai_is_configured` — `qrcode-2.html` (1 produto) com fake `enrich` → saída tem a tabela da revisão e `Aplicado:`; `produtos listar` mostra nome legível + tag; **não** há `Dica:` com `produtos revisar`.
2. `test_importar_without_ai_prints_pending_review_hint` — sem `JULIUS_AI_*` → `Dica: 1 produto(s) novo(s) sem categoria` … `julius produtos revisar`.
3. `test_importar_reimport_does_not_call_ai` — segundo import do mesmo arquivo → `fake.calls == []`.
4. `test_importar_sim_applies_ambiguous_tag_without_prompt` — fake devolve 2 tags → com `--sim` a primeira é aplicada.
5. `test_importar_multiple_files_reviews_once_at_the_end` — `qrcode.html` + `qrcode-3.html` (20 produtos novos) → uma chamada `enrich` (≤ 25) e no máximo uma `merge`; tabela impressa uma vez.
6. `test_importar_ai_failure_keeps_import_and_exit_0` — fake com `error` → `prices` gravados, saída contém `IA não respondeu`, exit 0, dica `PRODUCTS_PENDING_REVIEW` presente.
7. `test_importar_bad_file_still_exits_1_after_review` — arquivo inexistente + `qrcode-2.html` com IA → revisão roda para o bom, exit 1.
8. `test_importar_package_size_hint_only_without_review` — `qrcode-5.html` sem IA → `definir-conteudo` na dica (existente); com IA e fake → dica ausente.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `julius importar` de um HTML novo real, com IA configurada, mostra a tabela da revisão e as tags aparecem em `produtos listar` (teste manual do usuário).

## Notas para o agente
- A conexão `conn` já está aberta no comando; passe a mesma para a revisão (não abra outra).
- Não mova a revisão para dentro do loop por arquivo: uma passada no fim respeita o máximo de 2 dicas e faz um lote só.
