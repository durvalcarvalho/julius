# 127: Sinal de extremos no `importar` e coluna de dia da semana no `consultar`

> As duas saídas que o usuário pediu: "pagou caro nessa, barato naquela" no fim do import, e o dia da semana ao lado da data — sem nenhuma afirmação sobre padrão semanal.

## Contexto

`docs/design/comparability-v2.2.md` §4.10 e §3 (a ordem obrigatória dentro de `importar`). Requisitos RF6 de `comparability-closure.md` e o escopo de `import-price-signal.md` (Q1: linha por item que bateu extremo, limitada; Q2: saída própria, fora de `guidance.py`).

Sobre o dia da semana: as 6 notas reais caem em 6 dias da semana diferentes, com zero repetição — não há como afirmar padrão nenhum. A decisão do usuário foi mostrar o dado e calar, deixando o olho dele achar o padrão quando existir.

Depende de **126** (`new_extremes`) e de **122** (a revisão é que atribui o tipo; sem ela rodando antes, o sinal cai sempre no escopo degradado).

## Escopo

### Dentro
- `julius/cli/receipts.py`: impressão dos extremos no fim de `import_receipts`; coluna "Dia" nas tabelas de `search`.
- `julius/domain/models.py`: `ImportResult.access_key` — **só se** o 128 ainda não tiver entrado; coordene (ver Notas).
- Testes: `tests/test_cli_receipts.py`, `tests/test_e2e.py`.

### Fora
- `services/comparison.py` (fechado no 124/126).
- Qualquer estatística ou afirmação por dia da semana: sem agrupar por dia, sem média por dia, sem dica (RF6).
- Novo `HintKind` para o sinal de preço: é **resultado**, não dica — `guidance.py` não muda (decisão de `comparability-closure.md` §5, Q2).
- Arquivamento e `importar` sem argumento (→ 129).

## Requisitos

### Funcionais

- **Ordem dentro de `import_receipts`** (o design §3 a trata como obrigatória):
  1. importar cada arquivo;
  2. revisão dos produtos novos (já existe desde o 113) — é aqui que o `kind` é atribuído;
  3. **sinal de extremos**;
  4. dicas (`guidance`), inalteradas.
  Invertida a 2 com a 3, todo produto novo ainda tem `kind IS NULL` e o sinal perde justamente a comparação entre lojas.

- Depois da revisão, chamar `comparison.new_extremes(conn, access_keys)` com as chaves das notas importadas com sucesso nesta execução, e imprimir no máximo **5** linhas, com `+N mais` quando houver mais:
  ```
  Nesta compra:
    ↓ Tomate Italiano União  R$ 11,89/KG  menor preço já pago (era R$ 14,99 na Dona de Casa, 07/09)
    ↑ Mel Silves Bisnaga     R$ 33,99/UN  maior preço já pago (era R$ 29,99 no Assaí, 04/09)
    +3 mais
  ```
  - `↓` em verde para `lowest`, `↑` em vermelho para `highest` (reaproveitar `_HIGHLIGHT_STYLE`).
  - Quando a base é `price_per_content`, o preço sai por conteúdo e o sufixo diz qual: `R$ 2,46/L (por conteúdo)`.
  - Nenhum extremo → **nada é impresso** (nem cabeçalho, nem "nenhum"): silêncio é a resposta certa quando não há notícia.

- **Coluna "Dia"** em cada tabela de `search` (`consultar`), imediatamente depois de "Data": dia da semana abreviado em português minúsculo — `seg`, `ter`, `qua`, `qui`, `sex`, `sab`, `dom` — derivado de `PriceRecord.purchased_at`.
  - Derivação na renderização, com `datetime.fromisoformat(...).weekday()` e uma tupla constante de 7 strings no módulo da CLI. **Nada** no domínio, nada no serviço, nenhum campo novo em `PriceRecord`.
  - `purchased_at` inválido/inesperado → célula vazia, sem quebrar a tabela.

### Validação e erros
- `new_extremes` nunca lança (126); ainda assim, uma falha ali não pode impedir o import de reportar sucesso — o import já gravou.
- Sem nenhum arquivo importado com sucesso, não chamar `new_extremes`.
- A coluna "Dia" não muda largura/ordem das outras colunas nem o comportamento de `--limite`.

## Especificação técnica

```
modificar julius/cli/receipts.py     — sinal após a revisão; coluna "Dia" nas tabelas de search
modificar tests/test_cli_receipts.py
modificar tests/test_e2e.py
```

### Padrão a seguir
- `_HIGHLIGHT_STYLE` já existe em `cli/receipts.py:21` com `lowest`/`highest` → verde/vermelho; use o mesmo mapa para as setas.
- A formatação de moeda e a montagem de `Table` seguem o que `search` já faz no mesmo arquivo.
- `datetime` já está importado em `cli/receipts.py`.

## Testes obrigatórios

1. `test_import_prints_new_low_signal` — nota nova com preço abaixo do histórico → saída contém o nome do produto, o preço novo, o anterior e a loja anterior.
2. `test_import_prints_nothing_without_extremes` — nota cujos itens não batem recorde → a saída **não** contém `Nesta compra:`.
3. `test_import_limits_signal_to_five_lines` — 7 extremos → 5 linhas mais `+2 mais`.
4. `test_import_signal_runs_after_review` — com IA falsa atribuindo `kind`, o sinal do mesmo import já usa o escopo do grupo (prova a ordem do design §3).
5. `test_import_signal_shows_per_content_suffix` — grupo UN com conteúdo → linha com `(por conteúdo)` e a unidade certa.
6. `test_import_no_signal_when_all_files_fail` — todos os arquivos inválidos → `new_extremes` não é chamado e o código de saída continua o de hoje.
7. `test_search_shows_weekday_column` — `consultar` de um produto com data conhecida mostra `qua` na linha correspondente.
8. `test_search_weekday_for_all_days` — sete registros em sete dias → as sete abreviações aparecem (protege a ordem da tupla: 0 = `seg`).
9. `test_search_tolerates_bad_purchased_at` — registro com `purchased_at` fora do padrão → célula vazia, tabela renderiza, saída 0.
10. `test_e2e_import_twice_reports_lower_price` — importa `qrcode-3.html`, dá tipo ao tomate, importa `qrcode.html`: a saída do segundo import reporta o tomate como menor preço.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `git diff julius/services/guidance.py` vazio — o sinal não é dica.
- [ ] `git diff julius/domain/models.py` sem campo de dia da semana.
- [ ] Rodar de verdade: `JULIUS_DB=/tmp/x.db julius importar tests/fixtures/qrcode-3.html tests/fixtures/qrcode.html` e conferir o bloco `Nesta compra:`.

## Notas para o agente
- **Coordenação com o 128:** os dois tickets precisam da chave de acesso da nota importada. Se o 128 já entrou, `ImportResult.access_key` existe — use. Se este entrar primeiro, acrescente o campo aqui e o 128 só o consome. Não crie dois caminhos para obter a chave.
- Não adicione `HintKind` nem toque em `guidance.py`: dica é para vazio, erro e primeira vez; um novo mínimo é resultado bom, e o princípio 2 de "Dicas de uso" proíbe dica em cima de saída boa.
- A coluna "Dia" é só dado. Não agrupe por dia da semana, não calcule nada, não escreva "quarta costuma ser mais barato" em nenhuma circunstância — não há dado que sustente isso.
