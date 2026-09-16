# 118: Comandos de desfazer — `produtos tipo` e `definir-conteudo --remover`

> Cria o caminho manual (e o desfazer) de tipo e de conteúdo **antes** de qualquer automação aplicá-los, que é a condição que autoriza a IA a gravar sozinha.

## Contexto

`docs/design/comparability-v2.2.md` §4.5 (catalog), §4.10 (CLI). `docs/requirements/comparability-closure.md` §4 — uma ação só pode ser aplicada automaticamente se **for reversível por um comando que já existe** e se o erro for visível na saída normal. Hoje não existe como desfazer um conteúdo (`definir-conteudo` só define) nem como atribuir/limpar tipo. Este ticket fecha essa lacuna; o 122 é que passa a aplicar automaticamente, e depende deste.

Depende de **117** (`products.set_kind`, `clear_content`, `Product.kind`).

## Escopo

### Dentro
- `julius/services/catalog.py`: `set_product_kind`, `clear_product_kind`, `clear_product_content`.
- `julius/cli/products.py`: comando `tipo`; flag `--remover` em `definir-conteudo`; coluna "Tipo" em `produtos listar`.
- Testes: `tests/test_services_catalog.py`, `tests/test_cli_products.py` (ou os arquivos equivalentes já existentes para essas camadas).

### Fora
- Qualquer aplicação automática de tipo/conteúdo (→ 122).
- IA, prompt, `curation` (→ 120, 121).
- Log de ações e `--ultimas-acoes` (→ 122, 123).
- Consumir `kind` para comparar preço (→ 124, 126).
- Mudar `set_product_content` (a assinatura de definir continua a mesma; só ganha o caminho de limpar).

## Requisitos

### Funcionais

- `catalog.set_product_kind(conn, product_id: int, kind: str) -> None` — valida com `_non_blank(kind, "tipo")` (mensagem em português, como as irmãs do arquivo) e **delega** para `products.set_kind`. A regra de grafia é do repositório (117); não reimplementar aqui.
- `catalog.clear_product_kind(conn, product_id: int) -> None` — `products.set_kind(conn, product_id, None)`, dentro de `with conn:` como as irmãs.
- `catalog.clear_product_content(conn, product_id: int) -> None` — `products.clear_content`, dentro de `with conn:`.

- **`julius produtos tipo ID TIPO`** e **`julius produtos tipo ID --remover`**:
  ```
  julius produtos tipo 63 tomate       → define
  julius produtos tipo 63 --remover    → limpa
  ```
  `TIPO` é argumento opcional; com `--remover` ele deve ser omitido. `--help`: "Define o tipo do produto — o grupo usado para comparar preço entre mercados."
  Confirmação impressa: `63 · Tomate Italiano União → tipo "tomate"` (ou `→ tipo removido`).

- **`julius produtos definir-conteudo ID --remover`** — mesma forma: `QTD` e `UNIDADE` viram opcionais, e com `--remover` devem ser omitidos. Mensagem: `71 · Uva ... → conteúdo removido`.

- **`julius produtos listar`** ganha a coluna "Tipo" entre "Nome" e "Tags", preenchida com `Product.kind` (vazio quando `None`). É o que torna um tipo errado visível sem auditar nada — a condição (2) de `comparability-closure.md` §4.

### Validação e erros
- `tipo ID TIPO --remover` (os dois juntos) → erro claro, nada gravado: "Use `--remover` sem informar o TIPO."
- `tipo ID` sem `TIPO` e sem `--remover` → erro claro: "Informe o TIPO ou use `--remover`."
- Mesma dupla de erros para `definir-conteudo`.
- Produto inexistente → a mesma mensagem que `renomear`/`tag` já produzem hoje (reaproveitar `fail`/`_require_product`, não criar formato novo).

## Especificação técnica

```
modificar julius/services/catalog.py   — set_product_kind, clear_product_kind, clear_product_content
modificar julius/cli/products.py       — comando `tipo`, --remover em definir-conteudo, coluna Tipo em listar
modificar tests/test_services_catalog.py
modificar tests/test_cli_products.py
```

### Padrão a seguir
- O par "comando + flag de desfazer" já existe neste arquivo: `julius produtos tag ID TAG --remover` (`cli/products.py:79-85`). Copie a forma — `Annotated[bool, typer.Option("--remover", help=...)]` — e o estilo da mensagem.
- Argumento posicional opcional no Typer: `Annotated[Optional[str], typer.Argument()] = None`. Para `definir-conteudo`, `QTD` e `UNIDADE` viram `Optional[float]`/`Optional[str]`.
- Conexão aberta **dentro** do handler via `open_db()`, como todos os comandos (nunca em import — `tests/test_cli.py` garante).
- Nomes em inglês nas funções (`set_kind`/`clear_kind`), comando e textos em português: `@app.command("tipo")` sobre `def set_kind(...)`.

## Testes obrigatórios

1. `test_set_product_kind_delegates_and_normalizes` — `catalog.set_product_kind(id, "Tomate")` grava `"tomate"`; com um tipo `"açaí"` já existente, `"ACAI"` grava `"açaí"` (prova que a delegação preserva a regra do 117).
2. `test_set_product_kind_blank_raises` — `""` levanta erro com mensagem em português contendo "tipo".
3. `test_clear_product_kind` — depois de limpar, `Product.kind is None`.
4. `test_clear_product_content_clears_both` — os dois campos de conteúdo ficam `None`.
5. `test_cli_tipo_sets_and_prints_confirmation` — `produtos tipo ID tomate` sai com código 0 e imprime o nome do produto e o tipo.
6. `test_cli_tipo_remover_clears` — `produtos tipo ID --remover` limpa e confirma.
7. `test_cli_tipo_both_arg_and_remover_fails` — código de saída ≠ 0, nada gravado.
8. `test_cli_tipo_neither_arg_nor_remover_fails` — código ≠ 0, nada gravado.
9. `test_cli_definir_conteudo_remover_clears` — define conteúdo, depois `--remover`, e `consultar` volta a não mostrar coluna de preço por conteúdo.
10. `test_cli_listar_shows_kind_column` — saída de `produtos listar` contém o cabeçalho "Tipo" e o tipo de um produto que tem; produto sem tipo não imprime lixo na célula.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `julius produtos tipo --help` e `julius produtos definir-conteudo --help` legíveis, textos em português.
- [ ] Nenhuma aplicação automática foi introduzida: `grep -n "set_product_kind\|clear_product_content" julius/services/curation.py julius/cli/_review.py` vazio.

## Notas para o agente
- Este ticket existe por um princípio, não por conveniência: sem ele, o 122 aplicaria automaticamente algo que o usuário não consegue desfazer. Não reordene.
- Não adicione `--tipo` ao `consultar` — decidido contra no design §9 (`rapidfuzz` já acha o grupo quando o termo é o próprio tipo).
- A coluna "Tipo" em `produtos listar` não é enfeite: é a condição de visibilidade que autoriza a automação do 122.
