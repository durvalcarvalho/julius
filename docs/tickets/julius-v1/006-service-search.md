# 006: Serviço search

> `search_prices(conn, term, tag, limit)` acha produtos por similaridade de texto e/ou tag e devolve o histórico de preços agrupado por unidade, com menor e maior destacados.

## Contexto

É a resposta à pergunta central do produto ("R$12/kg tá caro?"). Leia no `CLAUDE.md`: "Identidade de produto e busca § 2 e § 3" (rapidfuzz, sem FTS5; tag ≠ texto), "Preço por conteúdo", "Fatos e pegadinhas" (nunca misturar UN com KG), "Design de testes § 3".

Depende de 003 (`product_names`, `product_ids_with_tag`) e 004 (`prices_for_products`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/services/search.py` com `search_prices(conn, term: str | None = None, tag: str | None = None, limit: int = 20) -> list[PriceRecord]`.
- `tests/test_services_search.py`.

### Fora
- Formatação/tabela → 009. Sugestão de fusão → 013. Qualquer chamada de IA (regra dura: `consultar` nunca chama IA). Veredito "caro/barato".

## Requisitos

### Funcionais
- Adicionar `normalize_text(text: str) -> str` em `julius/domain/normalization.py` (maiúsculas + remover acentos via `unicodedata.normalize("NFKD")` descartando combining chars + colapsar espaços), com 2 testes em `tests/test_normalization.py` (acento/caixa; string vazia). Reutilizada por 013.
- Candidatos por `term`: aplicar `normalize_text` ao termo e aos nomes e usar `rapidfuzz.process.extract(term, {id: name}, scorer=fuzz.WRatio, score_cutoff=MATCH_SCORE_CUTOFF, limit=None)`. `MATCH_SCORE_CUTOFF` é constante de módulo (começar em 75).
- Candidatos por `tag`: `products.product_ids_with_tag(conn, tag.strip().lower())`.
- Ambos informados → interseção. Só um → só ele.
- Busca `prices_for_products` e agrupa por `unit`. Dentro de cada grupo: ordena `purchased_at DESC`; mantém as `limit` mais recentes **e sempre inclui** a(s) linha(s) de menor e de maior `unit_price` do grupo inteiro, mesmo fora da janela; marca `highlight="lowest"` em todas as linhas com o menor preço e `"highest"` nas de maior. Grupo com um único preço distinto → sem `highlight`.
- Ordem de saída: grupos por `unit` ascendente (`KG` antes de `UN`), linhas por `purchased_at DESC`.
- Nunca compara/agrupa entre unidades diferentes; `price_per_content` vem pronto do repositório, só é repassado.

### Validação e erros
- `term is None and tag is None` → `ValueError("term or tag is required")`.
- `limit < 1` → `ValueError`.
- Sem candidatos ou sem preços → `[]` (não é erro).

## Especificação técnica

```
criar     julius/services/search.py
criar     tests/test_services_search.py
modificar julius/domain/normalization.py   # + normalize_text
modificar tests/test_normalization.py      # + 2 testes
```

Imports: `sqlite3`, `dataclasses.replace`, `rapidfuzz`, `julius.domain.models`, `julius.repositories.products`, `julius.repositories.prices`. Use `dataclasses.replace(record, highlight=...)` — `PriceRecord` é frozen.

## Testes obrigatórios (cenários via `import_receipt` de 005 com fixtures reais, ou inserts diretos quando indicado)

1. `test_exact_term_returns_all_rows_of_that_product` — após `qrcode.html`: `"picanha"` → 3 linhas, todas `unit == "KG"`, mesmo `product_id`.
2. `test_typo_still_matches` — `"pcanha"` → mesmas 3 linhas.
3. `test_unrelated_term_returns_empty` — `"hortifruti"` → `[]`.
4. `test_never_mixes_units_in_highlight` — inserts diretos: produto A `UN` preços 5 e 10, produto B `KG` preço 7, ambos nomeados "AGUA…"; termo `"agua"` → `highlight` de B é `None` (grupo com um preço), A tem `lowest` no 5 e `highest` no 10; 7 não é marcado como nada relativo a A.
5. `test_products_from_different_stores_are_not_merged` — `qrcode.html` + `qrcode-3.html`, termo `"tomate"` → dois `product_id` distintos.
6. `test_tag_filters_and_text_does_not` — `add_tag` em cebola e tomate com `"hortifruti"`; `search_prices(tag="hortifruti")` traz os dois; `search_prices(term="hortifruti")` → `[]`.
7. `test_term_and_tag_intersect`
8. `test_limit_keeps_newest_but_always_includes_extremes` — inserts diretos de 5 preços com datas crescentes, menor preço na data mais antiga, `limit=2` → 3 linhas (2 mais recentes + a mais antiga marcada `lowest`).
9. `test_requires_term_or_tag` e `test_limit_must_be_positive` → `ValueError`.
10. `test_accent_and_case_insensitive` — insert direto de produto `"PÃO FRANCÊS"`; termo `"pao frances"` acha.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `MATCH_SCORE_CUTOFF` é a única constante ajustada para os testes passarem; nenhum caso especial por string.

## Notas para o agente
- Se `"pcanha"` não passar com 75, ajuste o cutoff **uma vez** e registre o valor final no docstring da constante; não invente pré-processamento além de maiúsculas/acentos.
- Não ordene por `unit_price` na saída — a ordem é temporal; o destaque é o que aponta o extremo.
