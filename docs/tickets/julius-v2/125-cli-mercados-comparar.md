# 125: `julius mercados comparar` — a resposta a "esse mercado é mais caro?"

> Renderiza a comparação por grupo, deriva a contagem por loja e sempre imprime em quantos grupos e em que período a resposta se baseia.

## Contexto

`docs/design/comparability-v2.2.md` §4.10. Requisito RF5 de `comparability-closure.md`; o formato foi escolhido pelo usuário no fechamento (§5) — contagem por grupo com `n` e período, nunca um índice único.

Depende de **124** (`compare_stores`).

## Escopo

### Dentro
- `julius/cli/stores.py`: comando `comparar`.
- Testes: `tests/test_cli_stores.py`, e um caso em `tests/test_e2e.py`.

### Fora
- `services/comparison.py` (fechado no 124).
- Qualquer filtro (`--tag`, `--tipo`, `--desde`), ordenação alternativa ou exportação.
- Tocar em `mercados listar`/`renomear`.
- Dica nova em `guidance.py`: resultado cheio não é gatilho de dica (`CLAUDE.md`, "Dicas de uso", princípio 2).

## Requisitos

### Funcionais

- **`julius mercados comparar`** — sem argumentos nem opções. `--help`: "Compara o preço dos mesmos tipos de produto entre os mercados."

- Para cada `KindComparison`, uma tabela intitulada com o tipo e a base:
  ```
                    tomate · por KG
  ┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┓
  ┃ Mercado               ┃ Preço    ┃ Data       ┃
  ┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━┩
  │ FL 3 Costa            │ R$ 11,89 │ 2026-09-16 │
  │ Dona de Casa          │ R$ 14,99 │ 2026-09-07 │
  └───────────────────────┴──────────┴────────────┘
  ```
  Título da base: `por KG` / `por UN` quando `basis == "unit_price"` (a unidade de venda); `por L` / `por KG` / `por UN` conforme `content_unit` quando `basis == "price_per_content"` — e nesse caso acrescentar `(por conteúdo)` para o usuário saber que não é o preço da embalagem.
  A linha mais barata em verde e a mais cara em vermelho, reaproveitando `_HIGHLIGHT_STYLE` de `cli/receipts.py` (mover a constante para `cli/_common.py` se precisar importar dos dois lados).

- Depois das tabelas, a **contagem derivada** (calculada aqui, com `collections.Counter`, não vinda do serviço):
  ```
  FL 3 Costa      mais barato em 3 de 3 grupos
  Dona de Casa    mais barato em 0 de 2 grupos
  Assaí           mais barato em 0 de 1 grupo
  ```
  `de N grupos` = número de grupos em que aquela loja aparece, não o total de grupos — uma loja que aparece em 1 grupo não pode parecer que venceu todos. Ordenar por proporção decrescente e, em empate, por nome.

- Rodapé obrigatório, sempre:
  ```
  base: 3 grupos · 07/09 a 16/09
  Período largo: parte da diferença pode ser variação de preço no mês, não o mercado.
  ```
  A segunda linha em estilo `dim`.

- Sem grupos comparáveis (`comparisons` vazio), nada de tabela vazia — mensagem explícita conforme a causa:
  - nenhum produto com tipo → `Nenhum produto tem tipo ainda. Rode: julius produtos revisar`
  - há tipos, mas nenhum em duas lojas → `Nenhum tipo de produto foi comprado em dois mercados ainda — sem base para comparar.`

### Validação e erros
- Código de saída 0 em todos os casos, inclusive nos dois de "sem base": não é erro, é ausência de dado.
- Conexão aberta dentro do handler (`open_db()`), como todos os comandos.

## Especificação técnica

```
modificar julius/cli/stores.py        — comando `comparar`
modificar tests/test_cli_stores.py
modificar tests/test_e2e.py
```

### Padrão a seguir
- `cli/receipts.py::search` é o modelo de "uma tabela por grupo, com destaque colorido"; copie a forma de montar `Table` e de aplicar `rich.text.Text` com estilo.
- Formatação de moeda: a mesma função/formato já usado em `consultar` (`R$ 11,89`, vírgula decimal) — não escreva uma segunda formatação.
- `@app.command("comparar")` sobre `def compare_stores(...)`: comando em português, função em inglês.

## Testes obrigatórios

1. `test_comparar_prints_one_table_per_kind` — dois tipos em duas lojas → dois títulos de tabela na saída.
2. `test_comparar_orders_cheapest_first` — a primeira linha de dados da tabela é a loja mais barata.
3. `test_comparar_marks_cheapest_and_most_expensive` — a saída aplica os estilos de destaque (verificar via marcação/cor no `Result.output` como os testes de `consultar` já fazem).
4. `test_comparar_title_shows_per_content_basis` — grupo UN com conteúdo → título contém `por L` e `(por conteúdo)`.
5. `test_comparar_tally_counts_only_groups_where_store_appears` — loja presente em 1 de 3 grupos aparece como `de 1 grupo`, não `de 3`.
6. `test_comparar_footer_shows_group_count_and_period` — rodapé com `base: N grupos` e as duas datas.
7. `test_comparar_message_when_no_kinds` — banco com produtos sem tipo → mensagem apontando `julius produtos revisar`, saída 0.
8. `test_comparar_message_when_no_shared_kind` — tipos existem mas nenhum em duas lojas → a outra mensagem, saída 0.
9. `test_e2e_comparar_after_import_and_kinds` — importa dois fixtures reais, atribui o mesmo tipo aos dois tomates via `julius produtos tipo`, e `mercados comparar` mostra as duas lojas com os preços certos.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `julius mercados comparar` num banco sem tipo nenhum sai 0 com a mensagem certa.
- [ ] O rodapé aparece **em toda** execução que produz tabela — nunca uma comparação sem `n` e período.

## Notas para o agente
- O aviso do rodapé sobre período não é disclaimer defensivo: foi medido que as notas de lojas diferentes estão a 12 dias de distância, então parte da diferença pode não ser a loja. Mantenha o texto.
- Não transforme a contagem num percentual nem num "índice de carestia": a decisão foi contagem por grupo (design §9).
- Não adicione dica (`HintKind`) nenhuma aqui.
