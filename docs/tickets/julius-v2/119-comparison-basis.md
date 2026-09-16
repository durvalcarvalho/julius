# 119: `domain/comparison_basis.py` — a base de comparação, e `_highlight_and_trim` obedecendo-a

> Corrige um erro medido: hoje o mínimo/máximo compara preço de embalagem entre tamanhos diferentes, e marca a garrafa de 500ml como "a mais barata" quando por litro ela é a mais cara.

## Contexto

`docs/design/comparability-v2.2.md` §1 (a regra, com o caso real de cada ramo). Requisito RF7 de `docs/requirements/comparability-closure.md`.

O `CLAUDE.md` tem como princípio fundador "nunca comparar ou fazer média entre preços de bases diferentes". `_highlight_and_trim` (`services/search.py:152`) compara sempre `unit_price` dentro do grupo de mesma `unit` — o que **viola o princípio** para itens vendidos por UN, onde `unit_price` é o preço da embalagem. Medido no banco real: no grupo de água, 500ml a R$ 1,49 é marcada como a mais barata, embora custe R$ 2,98/L contra R$ 2,46/L da de 1,5L.

Independente de 117/118: a regra olha `unit`, `product_id`, `price_per_content` e `content_unit` — **não** olha `kind`. Pode rodar em paralelo com qualquer ticket.

## Escopo

### Dentro
- `julius/domain/comparison_basis.py` (novo): `Basis`, `comparison_basis`, `basis_value`.
- `julius/services/search.py`: `_highlight_and_trim` passa a usar as duas funções.
- Testes: `tests/test_domain_comparison_basis.py` (novo), `tests/test_services_search.py`.

### Fora
- `kind` e qualquer agrupamento por tipo (→ 124, 126 consomem esta regra depois).
- `search_prices`, `_candidate_ids`, `records_for_products` — o agrupamento por `unit` e o trim por `limit` continuam exatamente como estão; só muda **em cima de qual número** o mínimo/máximo é calculado.
- Qualquer mudança em `guidance.py` ou na renderização da CLI.
- Tolerância epsilon em comparação de float (decisão do design §1: manter o padrão atual de igualdade exata).

## Requisitos

### Funcionais

- `julius/domain/comparison_basis.py` — função pura, zero I/O, importa só de `julius.domain.models`:

  ```python
  Basis = Literal["unit_price", "price_per_content"]

  def comparison_basis(records: Sequence[PriceRecord]) -> tuple[Basis, tuple[int, ...]]:
      """Given records that already share the same sale unit, returns the basis to compare on
      and the indices (into `records`) that may take part in the comparison."""

  def basis_value(record: PriceRecord, basis: Basis) -> float | None:
      """The record's price on that basis; None when the record has no value for it."""
  ```

- Regra de `comparison_basis`, na ordem (cada ramo tem um caso real no design §1):
  1. `records` vazio → `("unit_price", ())`.
  2. `records[0].unit == "KG"` → `("unit_price", todos os índices)`. R$/kg **já é** preço por conteúdo.
  3. `unit == "UN"` e todas as linhas com o **mesmo `product_id`** → `("unit_price", todos os índices)`. Mesma embalagem em datas diferentes: série temporal legítima. É o ramo que preserva `test_never_mixes_units_in_highlight`.
  4. `unit == "UN"` com mais de um `product_id`:
     - `with_content` = índices cujo `price_per_content is not None`; `units` = conjunto dos `content_unit` desses.
     - `len(with_content) >= 2` **e** `len(units) == 1` → `("price_per_content", tuple(with_content))`. Quem não tem conteúdo **não participa**.
     - caso contrário → `("unit_price", ())` — ninguém participa, ninguém recebe destaque.

- `basis_value(record, "unit_price")` → `record.unit_price`; `basis_value(record, "price_per_content")` → `record.price_per_content`.

- `_highlight_and_trim(group, limit)` passa a:
  1. ordenar por `purchased_at` desc (inalterado);
  2. chamar `comparison_basis(group)`;
  3. montar `{índice: basis_value}` só para os índices participantes, descartando `None`;
  4. se sobrarem menos de 2 valores → devolver `group[:limit]` **sem nenhum `highlight`** (nem `None` explícito: devolver os registros como vieram);
  5. senão, `lowest`/`highest` sobre esses valores; o trim continua `group[:limit]` mais as linhas de fora do limite **que participam e cujo valor é extremo**;
  6. `lowest == highest` → devolve o `kept` sem marcar (inalterado);
  7. marcar `highlight` **apenas** nos registros participantes cujo valor bate o extremo; participante intermediário e não-participante ficam com `highlight=None`.

### Validação e erros
- `comparison_basis` nunca lança: entrada vazia, `content_unit` ausente e `price_per_content` `None` são casos tratados, não erros.
- Assume-se que o chamador já agrupou por `unit`; a função **não** valida isso (é invariante de `records_for_products`, garantido por teste existente).

## Especificação técnica

```
criar    julius/domain/comparison_basis.py
modificar julius/services/search.py         — _highlight_and_trim
criar    tests/test_domain_comparison_basis.py
modificar tests/test_services_search.py
```

### Padrão a seguir
- Módulo novo em `domain/`, não em `services/`: a regra é consumida por `services/search.py` **e** por `services/comparison.py` (124/126), e `tests/test_architecture.py` proíbe `services → services`. Colocar em `domain` é o que mantém a DAG válida — ver design §4.8.
- `dataclasses.replace` para marcar `highlight` já é o padrão no arquivo; mantenha.

## Testes obrigatórios

Em `tests/test_domain_comparison_basis.py` (unitário, sem banco, construindo `PriceRecord` na mão):
1. `test_kg_group_always_uses_unit_price` — 3 registros KG de produtos diferentes, sem conteúdo → `("unit_price", (0,1,2))`.
2. `test_un_single_product_uses_unit_price` — 2 registros UN do mesmo `product_id`, sem conteúdo → `("unit_price", (0,1))`.
3. `test_un_multi_product_all_with_uniform_content_uses_per_content` — 2 produtos UN, conteúdo em L nos dois → `("price_per_content", (0,1))`.
4. `test_un_multi_product_partial_content_participates_only_with_content` — 4 registros, 2 com conteúdo (mesma unidade) → `("price_per_content", (índices dos 2))`.
5. `test_un_multi_product_mixed_content_units_no_participants` — um em L, outro em KG → `("unit_price", ())`.
6. `test_un_multi_product_single_content_row_no_participants` — só 1 registro com conteúdo → `("unit_price", ())`.
7. `test_empty_group` — `([])` → `("unit_price", ())`.
8. `test_basis_value` — devolve `unit_price` e `price_per_content` conforme a base; `None` quando o registro não tem conteúdo.

Em `tests/test_services_search.py`:
9. `test_highlight_flips_to_cheapest_per_content` — caso da água: dois produtos UN, 500ml a R$ 1,49 (conteúdo 0.5 L) e 1,5L a R$ 3,69 (conteúdo 1.5 L); o **de 1,5L** recebe `"lowest"` e o de 500ml `"highest"`, ao contrário do que o preço de embalagem sugeriria.
10. `test_highlight_absent_when_content_missing_in_mixed_group` — dois produtos UN de tamanhos diferentes sem conteúdo definido → nenhum registro com `highlight`.
11. `test_highlight_ignores_non_participating_rows` — grupo UN com 2 linhas com conteúdo uniforme e 1 sem: a sem conteúdo tem `highlight is None` mesmo tendo o menor `unit_price` de todos.
12. Os testes existentes `test_never_mixes_units_in_highlight` e `test_limit_keeps_newest_but_always_includes_extremes` **continuam passando sem edição** — se algum precisar mudar, o desenho está errado, não o teste.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `tests/test_architecture.py` verde sem edição (prova que `domain/comparison_basis.py` não importa nada que não deva).
- [ ] `git diff julius/services/search.py` mostra mudança **apenas** dentro de `_highlight_and_trim` e o import novo.
- [ ] `test_eggs_bigger_pack_is_cheaper_per_unit` (e2e) continua verde; conferir na saída que a embalagem de 30 ovos agora recebe o destaque de mais barata.

## Notas para o agente
- O ramo 3 (mesmo `product_id` → `unit_price`) não é conveniência: sem ele, comparar o mesmo produto ao longo do tempo pararia de funcionar e dois testes existentes quebrariam. Implemente-o antes dos outros e rode a suíte.
- "Menos de 2 participantes → sem destaque" é resposta correta, não caso degenerado: é o que impede o sistema de afirmar qual embalagem é mais barata quando não sabe o tamanho dela.
- Não tente adivinhar conteúdo a partir da descrição em nenhuma circunstância — decisão antiga e mantida (`CLAUDE.md`, "Preço por conteúdo").
