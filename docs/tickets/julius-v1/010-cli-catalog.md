# 010: CLI — mercados e produtos

> Subcomandos `julius mercados …` e `julius produtos …` para a manutenção manual do catálogo.

## Contexto

Expõe o serviço `catalog` (007). Segue o padrão de registro de 009: módulos de comando não importam `app`; cada um expõe um `typer.Typer()` próprio que `julius/cli/__init__.py` anexa com `add_typer`. Leia no `CLAUDE.md`: "CLI — comando `julius`", "Decisões § 2".

Depende de 007 e de `julius/cli/_common.py` (009). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/cli/stores.py`: sub-app com `listar`, `renomear CNPJ APELIDO`.
- `julius/cli/products.py`: sub-app com `listar`, `renomear ID NOME`, `fundir ORIGEM DESTINO [--sim/-y]`, `tag ID TAG`, `definir-conteudo ID QTD UNIDADE`.
- Registro em `julius/cli/__init__.py`: `app.add_typer(stores.app, name="mercados", help=…)` e `add_typer(products.app, name="produtos", help=…)`.
- `tests/test_cli_catalog.py`.

### Fora
- `produtos comparar` → 013. `produtos pendentes` (questão em aberto, não incluir). Edição de linha de preço (é `sqlite3` direto, por decisão).

## Requisitos

### Funcionais
- `mercados listar` — tabela `CNPJ | Razão social | Apelido`; vazio → `"Nenhum mercado importado ainda."`.
- `mercados renomear CNPJ APELIDO` — `catalog.rename_store`; confirma `"Mercado {cnpj} agora é '{apelido}'."`. `CNPJ` aceita formatado ou só dígitos: aplique `digits_only` antes de chamar o serviço.
- `produtos listar` — tabela `ID | Nome | Conteúdo | Tags`; `Conteúdo` mostra `"500 g"`… não: mostra o valor gravado (`0.5 KG`) formatado como `"0,5 KG"`; vazio quando `None`.
- `produtos renomear ID NOME`, `produtos tag ID TAG`, `produtos definir-conteudo ID QTD UNIDADE` — chamam o serviço e confirmam em uma linha. `UNIDADE` é livre (`L/ML/KG/G/UN`, qualquer caixa); a validação é do serviço.
- `produtos fundir ORIGEM DESTINO` — irreversível: mostra os dois nomes e pede `typer.confirm("Fundir …? ")`, a menos que `--sim/-y`. Cancelado → `"Cancelado."`, exit 0.

### Validação e erros
- `ValueError`/`LookupError` dos serviços → `fail(mensagem)` (stderr, exit 1). Tipos errados (`ID` não inteiro, `QTD` não número) → o próprio Typer responde com exit 2.

## Especificação técnica

```
criar     julius/cli/stores.py
criar     julius/cli/products.py
modificar julius/cli/__init__.py
criar     tests/test_cli_catalog.py
```

## Testes obrigatórios (`CliRunner` + `JULIUS_DB` em `tmp_path`; cenários via `importar` da CLI)

1. `test_mercados_listar_empty_and_after_import`
2. `test_mercados_renomear_accepts_formatted_cnpj_and_shows_in_listar` — `"27.289.076/0013-79"` → apelido aparece em `listar`.
3. `test_mercados_renomear_unknown_exits_1_with_message`
4. `test_produtos_listar_shows_tags_and_content`
5. `test_produtos_renomear_and_tag`
6. `test_produtos_definir_conteudo_normalizes` — `500 g` → `listar` mostra `0,5 KG`.
7. `test_produtos_definir_conteudo_bad_unit_exits_1`
8. `test_produtos_fundir_asks_confirmation_and_cancels_on_no` — `input="n\n"` → `"Cancelado."`, produtos inalterados.
9. `test_produtos_fundir_with_yes_merges` — `--sim` → `listar` tem um produto a menos.
10. `test_produtos_fundir_same_id_exits_1`
11. `test_help_shows_subcommands` — `julius mercados --help` e `julius produtos --help`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `test_cli.py::test_importing_the_cli_has_no_side_effects_on_disk` continua verde.

## Notas para o agente
- Nome de comando com hífen (`definir-conteudo`) é dado em `@app.command("definir-conteudo")`; a função é `set_content`.
- Não duplique validação que já está no serviço; a CLI só traduz exceção em mensagem.
