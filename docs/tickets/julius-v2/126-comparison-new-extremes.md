# 126: `comparison.new_extremes` — quais itens da nota bateram mínimo ou máximo

> O cálculo por trás de "paguei caro?": para os itens recém-importados, quais bateram um novo extremo dentro do próprio grupo — comparando entre lojas quando o produto tem tipo.

## Contexto

`docs/design/comparability-v2.2.md` §4.8. `docs/requirements/import-price-signal.md` (RF1–RF4, com o escopo corrigido para o **grupo**, não só o `product_id`).

Medido no import de 16/09: de 46 itens, só 2 tinham qualquer preço anterior — e os dois eram comparações **entre lojas** (cebola e tomate, cujos `product_id` já abrangem duas lojas por fusão manual). Com `kind`, esse número cresce sem depender de fusão.

Depende de **117** (`kind`), **119** (`comparison_basis`) e **124** (o módulo `services/comparison.py` já existe).

## Escopo

### Dentro
- `julius/domain/models.py`: `PriceExtreme`.
- `julius/services/comparison.py`: `new_extremes`.
- Testes: `tests/test_services_comparison.py`.

### Fora
- CLI, impressão, limite de 5 linhas (→ 127).
- Coluna de dia da semana (→ 127).
- Qualquer estatística além de mínimo/máximo: sem média, sem faixa, sem percentual (RF N1 do fechamento).
- Item sem histórico: **não** gera saída nenhuma — nem "sem dado" (RF3 de `import-price-signal.md`).

## Requisitos

### Funcionais

- `PriceExtreme` (`domain/models.py`, `frozen=True`):
  ```python
  product_name: str
  store_nickname: str
  unit: SaleUnit
  price: float              # on the comparison basis
  highlight: Highlight      # "lowest" | "highest"
  basis: Basis
  content_unit: ContentUnit | None
  previous_price: float
  previous_store: str
  previous_at: str
  scope: str                # the kind, or the product's name when it has no kind
  ```

- `new_extremes(conn, access_keys: Sequence[str]) -> list[PriceExtreme]`:
  1. carrega as linhas das notas de `access_keys` (`prices`, join com `products`/`stores` — reaproveitar `prices_for_products` restringindo depois pelas chaves é aceitável e mais barato em código do que query nova).
  2. para cada item dessas notas, define o **escopo de comparação**:
     - produto com `kind` → todas as linhas de produtos com o mesmo `kind` **e** a mesma `unit`;
     - produto sem `kind` → todas as linhas do mesmo `product_id` e mesma `unit`.
  3. a base vem de `comparison_basis` aplicada ao escopo **inteiro** (linhas novas incluídas), e o item só é avaliado se ele mesmo for participante; não sendo, é ignorado silenciosamente (é o caso do item UN sem conteúdo em grupo heterogêneo — RF7).
  4. "anterior" = linhas do escopo que **não** pertencem a nenhuma das `access_keys`. Sem nenhuma linha anterior → item ignorado (sem histórico, sem sinal).
  5. compara o valor do item na base contra o mínimo e o máximo dos anteriores:
     - estritamente menor que o mínimo anterior → `highlight="lowest"`, `previous_*` da observação que era o mínimo;
     - estritamente maior que o máximo anterior → `highlight="highest"`, `previous_*` do máximo;
     - entre os dois (ou igual a um deles) → nenhum `PriceExtreme` (empatar o próprio recorde não é notícia).
  6. ordena o resultado: `lowest` antes de `highest` e, dentro de cada um, pela maior diferença relativa ao anterior (a notícia mais forte primeiro).
  7. um item por linha de nota; duas linhas da mesma nota do mesmo produto podem gerar dois extremos só se as duas realmente batem o recorde — na prática a segunda empata e cai fora pela regra 5.

### Validação e erros
- `access_keys` vazio → `[]`, sem consultar nada.
- Chave inexistente → `[]` (não é erro).
- Nunca lança; nunca chama IA.

## Especificação técnica

```
modificar julius/domain/models.py            — PriceExtreme
modificar julius/services/comparison.py      — new_extremes
modificar tests/test_services_comparison.py
```

### Padrão a seguir
- Mesmo estilo do 124: ler via repositórios, agrupar em Python, devolver dado.
- "Excluir a própria nota" é a regra que impede a comparação circular — foi o que a análise manual de 16/09 usou e é o que faz o sinal significar algo.

## Testes obrigatórios

1. `test_new_extremes_reports_new_low_across_stores` — produto tipado `cebola`: R$ 9,99 numa loja antes, R$ 7,89 na nota nova em outra → um `PriceExtreme` com `highlight="lowest"`, `previous_price == 9.99`, `previous_store` da primeira loja, `scope == "cebola"`.
2. `test_new_extremes_reports_new_high` — preço novo acima de todos os anteriores → `highlight="highest"`.
3. `test_new_extremes_silent_without_history` — produto visto pela primeira vez → `[]`.
4. `test_new_extremes_silent_when_price_in_between` — preço entre mínimo e máximo anteriores → `[]`.
5. `test_new_extremes_silent_when_tying_record` — preço exatamente igual ao mínimo anterior → `[]`.
6. `test_new_extremes_excludes_own_receipt_from_history` — nota nova com duas linhas do mesmo produto: a segunda não é tratada como "anterior" da primeira.
7. `test_new_extremes_falls_back_to_product_scope_without_kind` — produto sem `kind` compara só com o próprio histórico; `scope` é o nome do produto.
8. `test_new_extremes_uses_per_content_basis` — grupo UN com conteúdo uniforme: o extremo é decidido por preço por conteúdo, e `basis`/`content_unit` vêm preenchidos.
9. `test_new_extremes_skips_non_participating_item` — item UN sem conteúdo em grupo heterogêneo não gera extremo, mesmo tendo o menor preço de embalagem.
10. `test_new_extremes_orders_lowest_first_then_by_magnitude` — dois `lowest` e um `highest` → os dois mínimos primeiro, o de maior queda relativa antes.
11. `test_new_extremes_empty_access_keys` — `[]` de entrada → `[]` de saída.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -n "console\|print" julius/services/comparison.py` vazio.
- [ ] Reproduzir o caso real: importar `qrcode.html` e `qrcode-3.html` num banco temporário, dar o tipo `tomate` aos dois tomates, reimportar a nota mais nova e conferir que o tomate aparece como `lowest` contra a outra loja.

## Notas para o agente
- Empate com o próprio recorde **não** é extremo: a nota de 16/09 repetiu preços de 12/09 em vários itens, e marcar isso como notícia treinaria o usuário a ignorar o sinal.
- O escopo degradado (sem `kind` → só o próprio produto) não é fallback preguiçoso: é o que faz o sinal funcionar antes de a curadoria de tipos alcançar o catálogo inteiro.
- Não introduza percentual na saída do serviço; a diferença relativa é só critério de ordenação.
