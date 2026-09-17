# 144: `search` — colapso de linhas idênticas e ordem pela base de comparação

> A tabela de `consultar` para de repetir a mesma informação e passa a estar na ordem que responde à pergunta.

## Contexto

`docs/design/merge-and-unit-price-v2.4.md` §6.1, §6.2. Requisitos RF9/RF10 e as questões Q4/Q5.

Medido (F8): 20% das linhas de `consultar` são repetições exatas — 9 de 45 em 7 buscas, sendo **5 de 9 em `agua`**, que é justamente o grupo onde a comparação por conteúdo importa. E a tabela ordena por data, então "qual embalagem compensa" exige ler a coluna e ordenar de cabeça.

Independente da frente de fusão: não depende de 137–143 e pode ser feito antes.

## Escopo

### Dentro
- `julius/services/search.py`: colapso em `records_for_products`; ordem em `_highlight_and_trim`.
- `tests/test_services_search.py`; os testes de `consultar` em `tests/test_cli_receipts.py` que contam linhas.

### Fora
- A linha de resposta impressa (→ 145).
- Qualquer mudança em `domain/comparison_basis.py`: ele já decide a base e está correto.
- Mostrar contagem ("2×") nas linhas colapsadas (Q4: `consultar` é sobre preço, não sobre quantidade comprada).
- Mudar `MATCH_SCORE_CUTOFF` ou qualquer corte de busca.

## Requisitos

### Funcionais

- **Colapso** (RF9): em `records_for_products`, **antes** de `_highlight_and_trim`, registros com a mesma chave `(product_id, purchased_at, store_nickname, unit_price)` viram um só. Tem de ser antes, senão o destaque e o `--limite` contam linhas que são a mesma informação.
  - A ordem relativa dos registros que sobram é preservada.
  - O `access_key` do registro que sobra é o do primeiro — quem usa `access_key` (o sinal de extremos do `importar`) continua funcionando.
- **Ordem** (RF10): `_highlight_and_trim` já computa `basis, participants = comparison_basis(group)`. A ordenação do grupo passa a depender da base:
  - `basis == "price_per_content"` → `price_per_content` crescente (registro sem valor vai para o fim, mantendo a ordem por data entre eles);
  - caso contrário → `purchased_at` decrescente, exatamente como hoje.
- Nada mais muda: o cálculo de `lowest`/`highest`, a regra de manter empates fora do `--limite` e o agrupamento por unidade continuam idênticos.

### Validação e erros
- `limit < 1` continua levantando `ValueError`.
- Grupo com um registro só: colapso e ordem são no-ops.

## Especificação técnica

```
modificar julius/services/search.py
modificar tests/test_services_search.py
```

### Padrão a seguir
- O colapso é um laço com `dict` por chave, preservando ordem de inserção — sem `set`, que perderia a ordem.
- `comparison_basis` é importada e já usada na função; não duplique a decisão.

## Testes obrigatórios

1. `test_collapses_identical_rows` — duas linhas do mesmo item na mesma nota (mesmo produto/data/mercado/preço) → uma linha.
2. `test_does_not_collapse_different_price_or_store` — mesmo produto e data, preço diferente → duas linhas; mercado diferente → duas linhas.
3. `test_collapse_happens_before_the_limit` — 5 linhas sendo 3 repetições exatas, `limit=3` → as 3 distintas aparecem (antes, o limite era gasto com repetição).
4. `test_orders_by_price_per_content_when_that_is_the_basis` — grupo UN com 3 produtos de conteúdos diferentes → a primeira linha é a de menor preço por conteúdo, e ela é a marcada como `lowest`.
5. `test_orders_by_date_for_a_time_series` — grupo UN com um `product_id` só → ordem por data decrescente, como hoje.
6. `test_orders_by_date_for_kg` — grupo KG → ordem por data decrescente.
7. `test_rows_without_content_go_last_in_content_order` — grupo heterogêneo com um produto sem conteúdo → ele aparece depois dos comparáveis, sem destaque.
8. Os testes existentes de destaque continuam passando **sem edição**.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `git diff julius/domain/comparison_basis.py` **vazio**.
- [ ] Rodar contra uma cópia do banco real: `julius consultar agua` mostra **4 linhas** (contra 9 hoje), com a Indaiá 1,5L em primeiro e marcada como a mais barata.

## Notas para o agente
- A chave do colapso **não** inclui `access_key` de propósito: o mesmo preço do mesmo produto no mesmo dia e mercado é a mesma informação de preço, tenha vindo de uma nota ou de duas.
- Não introduza flag nenhuma para escolher a ordem: a distinção já existe em `comparison_basis` e é ela que decide (Q5).
