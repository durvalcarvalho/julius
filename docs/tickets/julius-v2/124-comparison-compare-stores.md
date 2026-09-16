# 124: `services/comparison.py` — comparação de preço entre mercados por grupo

> Responde "esse mercado é mais caro?" a partir dos grupos (`kind` + `unit`), sempre dizendo em quantos grupos a resposta se baseia e de que período — nunca um índice único.

## Contexto

`docs/design/comparability-v2.2.md` §4.8 (contratos), §1 (base de comparação). Requisitos RF5 e a decisão do usuário registrada em `comparability-closure.md` §5 ("mostrar já, com `n` e período explícitos").

Medido no banco real: 12 grupos abrangem mais de uma loja, e os 3 limpos (cebola, tomate, banana — todos por KG) apontam FL 3 Costa mais barato nos três. Também medido: as notas do Assaí são todas de 04/09 e as do FL 3 Costa de 12–16/09, então parte de qualquer diferença pode ser variação de preço no mês, não a loja — é por isso que o intervalo de datas é parte obrigatória da resposta, não enfeite.

Depende de **117** (`kind` em `Product`/`PriceRecord`) e **119** (`comparison_basis`).

## Escopo

### Dentro
- `julius/domain/models.py`: `StorePrice`, `KindComparison`, `StoreComparison`.
- `julius/services/comparison.py` (novo): `compare_stores`.
- Testes: `tests/test_services_comparison.py` (novo).

### Fora
- CLI e qualquer renderização (→ 125). Este serviço **não imprime**.
- `new_extremes` e o sinal do `importar` (→ 126, 127) — mesmo arquivo, outro ticket.
- Contagem "mais barato em X de Y" por loja: é **derivada** na CLI (→ 125), não campo de dataclass (mesma decisão do 115 sobre `retried_without_tag`).
- Janela temporal (`--desde`), média de razões, índice único por mercado — todos decididos contra no design §9.

## Requisitos

### Funcionais

- Dataclasses (`domain/models.py`, todas `frozen=True`):
  ```python
  class StorePrice:
      store_nickname: str
      price: float            # on the comparison basis
      purchased_at: str

  class KindComparison:
      kind: str
      unit: SaleUnit
      basis: Basis                       # from domain.comparison_basis
      content_unit: ContentUnit | None   # set only when basis == "price_per_content"
      entries: tuple[StorePrice, ...]    # cheapest first

  class StoreComparison:
      comparisons: tuple[KindComparison, ...]
      first_purchase: str
      last_purchase: str
  ```

- `compare_stores(conn) -> StoreComparison`:
  1. lê os produtos via `repositories.products.list_products` e fica com os que têm `kind is not None`; sem nenhum, devolve `StoreComparison((), "", "")`.
  2. chama `repositories.prices.prices_for_products` com esses ids — **nenhuma query nova**; os `PriceRecord` já trazem `kind`, `store_nickname` e `price_per_content`.
  3. agrupa por `(kind, unit)`.
  4. para cada grupo, chama `comparison_basis` (119) e mantém só os registros **participantes**.
  5. por loja, o representante é o **menor** valor na base, com a data daquela observação. Empate de valor na mesma loja → a observação mais recente.
  6. grupo cujos participantes cobrem **menos de 2 lojas** é descartado (não há comparação a fazer).
  7. `entries` ordenado por preço crescente; empate entre lojas → nome da loja em ordem alfabética, para a saída ser determinística.
  8. `comparisons` ordenado por `kind`, e dentro do mesmo `kind` por `unit`.
  9. `first_purchase`/`last_purchase` = menor e maior `purchased_at` **entre as observações efetivamente usadas** (os representantes), não entre todas as linhas do banco — o período tem que descrever a resposta dada.

### Validação e erros
- Banco vazio, nenhum produto com tipo, ou nenhum grupo com 2 lojas → `StoreComparison` com `comparisons` vazio e as datas em `""`. Não lançar, não inventar mensagem (a mensagem é da CLI).
- `content_unit` só é preenchido quando a base é `price_per_content`; nesse caso todos os participantes têm a mesma unidade de conteúdo (garantido pela regra do 119).

## Especificação técnica

```
modificar julius/domain/models.py               — StorePrice, KindComparison, StoreComparison
criar    julius/services/comparison.py
criar    tests/test_services_comparison.py
```

### Padrão a seguir
- Serviço = função que recebe `conn` e devolve dado; nunca imprime, nunca formata moeda. Mesmo contrato de `search.search_prices`.
- Importa `comparison_basis`/`basis_value` de `julius.domain.comparison_basis` — **não** de `services.search` (`tests/test_architecture.py` proíbe `services → services`; é a razão de a regra morar em `domain`).
- Agrupar em Python em cima de `prices_for_products` é o padrão existente (`search.records_for_products` faz igual). Não escreva SQL de agregação.

> `ponytail:` varre todas as linhas de `prices` dos produtos com tipo (132 linhas hoje). Virar agregação em SQL só se o banco crescer ordens de magnitude.

## Testes obrigatórios

1. `test_compare_stores_kg_group_two_stores` — mesmo `kind` por KG em duas lojas → um `KindComparison`, `basis == "unit_price"`, `entries` do mais barato para o mais caro.
2. `test_compare_stores_skips_single_store_group` — tipo presente em uma loja só não aparece no resultado.
3. `test_compare_stores_uses_cheapest_per_store` — loja com duas observações no grupo (R$ 6,99 e R$ 14,99) entra com 6,99 e com a data daquela observação.
4. `test_compare_stores_un_group_uses_per_content` — dois produtos UN com conteúdo uniforme em lojas diferentes → `basis == "price_per_content"`, `content_unit` preenchido, e a ordem reflete o preço por conteúdo (não o de embalagem).
5. `test_compare_stores_skips_un_group_without_content` — grupo UN multi-produto sem conteúdo → participantes insuficientes → grupo ausente do resultado.
6. `test_compare_stores_date_range_covers_used_observations` — `first_purchase`/`last_purchase` batem com as datas dos representantes, e **não** com a data de uma linha que ficou de fora.
7. `test_compare_stores_empty_when_no_kinds` — nenhum produto com tipo → `comparisons == ()` e datas `""`.
8. `test_compare_stores_deterministic_order` — dois grupos e duas lojas empatadas em preço: ordem de `comparisons` por `kind`/`unit` e de `entries` por preço e depois nome.
9. `test_compare_stores_ignores_untyped_products` — produto sem `kind` com preços em duas lojas não gera comparação.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `tests/test_architecture.py` verde sem edição.
- [ ] `grep -n "console\|print\|rich" julius/services/comparison.py` vazio.
- [ ] Rodar contra uma cópia do banco real depois de atribuir alguns tipos à mão e conferir que cebola/tomate/banana aparecem com FL 3 Costa em primeiro.

## Notas para o agente
- "Menor preço da loja" como representante é decisão de desenho, não detalhe: a pergunta do usuário é "o que eu pagaria lá", e num price-shopping o representante justo é o mais barato disponível. Não troque por média nem por "mais recente".
- Descartar grupo com menos de 2 lojas é o que impede a saída de virar uma lista de grupos sem comparação nenhuma.
- Não some, não faça média entre grupos, não produza um número por loja neste serviço — a contagem é da CLI e é contagem, não índice.
