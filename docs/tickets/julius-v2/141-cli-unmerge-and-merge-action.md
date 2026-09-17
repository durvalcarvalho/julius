# 141: CLI — `desfundir`, `fundir` sem o aviso de irreversível, e a ação `merge` no log

> O comando de desfazer existe e está testado **antes** de qualquer fusão automática ser ligada.

## Contexto

`docs/design/merge-and-unit-price-v2.4.md` §4.5, §7.4, §7.8. Requisitos RF1h/RF6/RF7 e a questão Q11.

Depende de **140** (`unmerge_product`, a guarda de ciclo).

**Restrição de ordem que é de princípio:** este ticket vem antes do 143. A automação só pode gravar o que já tem comando de desfazer — a mesma regra que pôs o 118 antes do 122 na v2.2.

## Escopo

### Dentro
- `julius/domain/models.py`: `AppliedAction.field` ganha `"merge"`; `Product.merged_into`.
- `julius/cli/products.py`: comando `desfundir`; `fundir` sem o aviso de irreversível e sem confirmação.
- `julius/cli/_review.py`: `_undo_command` para `"merge"`; `_FIELD_LABELS` ganha a fusão.
- `tests/test_cli_catalog.py`, `tests/test_cli_review.py`.

### Fora
- Fundir automaticamente (→ 143). Depois deste ticket, nada funde sozinho.
- O guarda de conteúdo divergente (→ 142).
- A coluna de conteúdo/ordem de `consultar` (→ 144/145).

## Requisitos

### Funcionais

- **`julius produtos desfundir ID`** — `catalog.unmerge_product`. `ID` é o do produto **absorvido** (simétrico com `fundir ORIGEM DESTINO`). Sucesso: imprime que o produto voltou a ser separado, citando os dois nomes. `ValueError`/`LookupError` → `fail` com a mensagem do serviço.
- **`julius produtos fundir ORIGEM DESTINO`** — mesma chamada de hoje, com três mudanças de texto/comportamento:
  - o docstring deixa de dizer "Irreversível" e passa a dizer que dá para desfazer com `produtos desfundir`;
  - a confirmação (`typer.confirm`) e a flag `--sim` **saem**: a operação é reversível, então pedir confirmação é atrito sem justificativa (RF1h);
  - a mensagem de sucesso termina com o comando de desfazer pronto: `desfazer: julius produtos desfundir <origem>`.
- **`AppliedAction.field`** aceita `"merge"`, com `before=None` e `after=str(absorvido)`.
- **`_undo_command`** para `"merge"` devolve `julius produtos desfundir <after>`. Cuidado: o `product_id` da ação é o **sobrevivente** (é o produto que mudou de estado do ponto de vista do grupo), e o id a desfundir está em `after` — por isso o campo não pode reaproveitar a forma dos outros.
- **`_FIELD_LABELS`** ganha `("merge", "fusão(ões)")`, para o resumo agregado contar fusões.
- **`Product.merged_into: int | None`** no domínio, preenchido por `_to_product`, para a CLI poder dizer "esse produto não está fundido".

### Validação e erros
- `desfundir` de produto inexistente ou não fundido → mensagem clara, código de saída 1, nada gravado.
- Nenhum comando novo abre conexão em tempo de import.

## Especificação técnica

```
modificar julius/domain/models.py      — AppliedAction.field, Product.merged_into
modificar julius/cli/products.py       — desfundir; fundir sem confirmação nem aviso
modificar julius/cli/_review.py        — _undo_command("merge"), _FIELD_LABELS
modificar tests/test_cli_catalog.py
modificar tests/test_cli_review.py
```

### Padrão a seguir
- `@app.command("desfundir")` sobre `def unmerge_product(...)` — comando em português, função em inglês.
- `test_undo_command_per_field` em `tests/test_cli_review.py` é parametrizado por campo; acrescente o caso de `"merge"` lá.
- O teste que garante que **todo** `HintKind` tem texto é o precedente para "todo campo de `AppliedAction` tem rótulo e comando de desfazer" — se não existir um assim, crie.

## Testes obrigatórios

1. `test_desfundir_separates_the_products` — funde pela CLI, desfunde, e `produtos listar` volta a mostrar os dois.
2. `test_desfundir_unknown_or_not_merged_fails_cleanly` — código 1 e mensagem, nos dois casos.
3. `test_fundir_prints_the_undo_command` — a saída traz `julius produtos desfundir <origem>`.
4. `test_fundir_does_not_ask_for_confirmation` — rodar **sem `input=`** termina com código 0 (prova que a confirmação saiu e nada bloqueia em stdin).
5. `test_fundir_help_does_not_say_irreversible` — `--help` não contém "Irreversível" nem "não dá para desfazer".
6. `test_undo_command_for_merge_field` — `_undo_command(AppliedAction(33, "merge", None, "80"))` → `julius produtos desfundir 80`.
7. `test_every_applied_action_field_has_label_and_undo` — varre os valores do `Literal` e falha se algum não tiver rótulo em `_FIELD_LABELS` e comando em `_undo_command`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -rn "Irreversível\|não dá para desfazer" julius` **vazio**.
- [ ] `grep -n "confirm" julius/cli/products.py` não mostra mais a confirmação do `fundir`.
- [ ] `julius produtos desfundir --help` funciona e o texto está em português.
- [ ] `tests/test_architecture.py` verde sem edição.

## Notas para o agente

- Não remova a confirmação de nenhum **outro** comando; a do `fundir` cai porque a operação deixou de ser destrutiva, e essa razão não se aplica a mais nada.
- O `README.md` e o `CLAUDE.md` também afirmam que fundir é irreversível — a correção deles é o ticket 146, não aqui. Não edite documentação neste ticket.
