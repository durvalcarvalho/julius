# 009: CLI — importar, consultar, exportar

> Os três comandos do fluxo principal, registrados no `app` Typer existente, com conexão aberta só dentro do handler.

## Contexto

Primeira vez que o produto vira usável de ponta a ponta. `julius/cli/__init__.py` já tem o `app` (com callback raiz) e `tests/test_cli.py` já garante que importar a CLI não toca em disco — isso tem que continuar verdadeiro. Leia no `CLAUDE.md`: "CLI — comando `julius`", "Convenções de código" (comando em português, função em inglês), "Estrutura de pacote" (o que `cli` pode importar).

Depende de 005, 006, 008. Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/cli/_common.py`: `open_db() -> sqlite3.Connection` (`config.load()` + `infra.db.connect`), `console = rich.console.Console()`, `fail(message: str) -> NoReturn` (imprime em `stderr` e `raise typer.Exit(code=1)`).
- `julius/cli/receipts.py`: funções `import_receipts(files: list[Path])`, `search(term, tag, limit)`, `export(output)`.
- Registro em `julius/cli/__init__.py`: `app.command("importar")(receipts.import_receipts)`, `app.command("consultar")(receipts.search)`, `app.command("exportar")(receipts.export)` — os módulos de comando **não** importam `app` (evita import circular).
- `tests/test_cli_receipts.py`.

### Fora
- `mercados`/`produtos` → 010. `comparar` → 013. Cores/temas configuráveis. Qualquer lógica de negócio (tudo vem dos serviços).

## Requisitos

### Funcionais
- `julius importar ARQUIVO...` — para cada arquivo, em ordem: chama `importing.import_receipt`; imprime `"{nome}: {new} itens novos, {existing} já existiam"`. Se um arquivo falhar (`FileNotFoundError`, `ReceiptParseError`, `UnknownUnitError`), imprime `"{nome}: erro — {mensagem}"` em stderr e **continua** os demais; ao final, exit code 1 se houve alguma falha, 0 senão.
- `julius consultar [TERMO] [--tag TAG] [--limite/-n INT=20]` — sem `TERMO` e sem `--tag` → `typer.BadParameter` (exit 2) com mensagem em português. Resultado vazio → imprime `"Nenhum resultado."` e exit 0. Senão, uma `rich.table.Table` por unidade (título `"Preços por KG"`/`"Preços por UN"`), colunas: Data (`YYYY-MM-DD`), Produto, Mercado (nickname), Preço (`R$ 6,99` — vírgula na exibição), e coluna `Por L`/`Por KG`/`Por UN` só se alguma linha do grupo tiver `price_per_content`. Linha `lowest` em verde, `highest` em vermelho.
- `julius exportar [--saida/-o PATH=julius-export.csv]` — chama `export.export_csv`; imprime `"{n} linhas exportadas para {path}"`.
- Conexão: `open_db()` chamada **dentro** de cada handler; fechada ao final (`try/finally` ou context manager).

### Validação e erros
- Exceções de domínio viram mensagem legível + exit 1 via `fail`; nunca traceback para erro esperado. Erros inesperados podem propagar (traceback é informação útil aqui).

## Especificação técnica

```
criar     julius/cli/_common.py
criar     julius/cli/receipts.py
modificar julius/cli/__init__.py       # registra os 3 comandos, nada mais
criar     tests/test_cli_receipts.py
```

Parser: instanciar `DFReceiptParser()` dentro do handler de `importar` (é a única implementação; sem registry).

## Testes obrigatórios (`typer.testing.CliRunner`, `monkeypatch.setenv("JULIUS_DB", tmp_path/"prices.db")`)

1. `test_importar_prints_per_file_summary` — `qrcode.html` → saída contém `"20 itens novos, 0 já existiam"`, exit 0.
2. `test_importar_twice_reports_existing` — segunda vez `"0 itens novos, 20 já existiam"`.
3. `test_importar_continues_after_bad_file_and_exits_1` — `[inexistente.html, qrcode-2.html]` → exit 1, stderr cita o inexistente, `qrcode-2` importado (1 novo).
4. `test_consultar_requires_term_or_tag` — exit 2.
5. `test_consultar_shows_table_per_unit` — após importar `qrcode.html`, `consultar picanha` → saída contém `"PICANHA"` e `"Preços por KG"`, não contém `"Preços por UN"`.
6. `test_consultar_no_results_message` — `consultar xyzabc` → `"Nenhum resultado."`, exit 0.
7. `test_exportar_writes_file_and_reports_count` — arquivo existe, saída contém `"20 linhas"`.
8. `test_help_lists_the_three_commands` — `--help` contém `importar`, `consultar`, `exportar`.
9. Já existente e deve continuar verde: `tests/test_cli.py::test_importing_the_cli_has_no_side_effects_on_disk`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde, inclusive `test_architecture.py` (cli só importa `domain`, `config`, `infra`, `services`).
- [ ] `.venv/bin/julius importar tests/fixtures/qrcode.html` funciona com `JULIUS_DB` apontando para um arquivo temporário.

## Notas para o agente
- `cli` pode importar `julius.parsers` (é o composition root; já permitido em `tests/test_architecture.py`). Não altere aquele arquivo.
- Formatação `R$ 6,99` é só exibição: `f"R$ {value:.2f}".replace(".", ",")`. Não toque nos dados.
