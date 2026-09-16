# 108: `suggestions` — `enrich_products` (lote) e `match_products`

> As duas chamadas novas de IA: enriquecer produtos em lotes de 25 (nome legível, categorias, conteúdo) e casar um termo de busca com o catálogo quando o rapidfuzz não achou nada.

## Contexto

`docs/design/ai-v2.md` §4.5, §6.1 e §6.3. O gate T3 validou o prompt de enriquecimento com 6 produtos reais (JSON correto em ~2 s com thinking desligado). Substitui `suggest_content`/`suggest_tags` (removidos no 107).

Depende de 107 (`_ask`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/domain/models.py`: `ProductEnrichment`; `ContentSuggestion` perde `confidence` (fica `quantity`, `unit`).
- `julius/services/suggestions.py`: `PROMPT_VERSIONS["enrich"] = "1"`, `["match"] = "1"`; `SYSTEM_PROMPTS` dos dois; `ENRICH_BATCH_SIZE = 25`; `enrich_products`; `match_products`.
- `tests/test_services_suggestions.py` (acrescentar).

### Fora
- Decidir o que aplicar automaticamente (→ 109 `curation`). Qualquer prompt/comando de CLI.

## Requisitos

### Funcionais
- `ProductEnrichment(readable_name: str, tags: tuple[str, ...], content: ContentSuggestion | None)` — frozen. `tags` com 1–3 itens, melhor primeiro; `len > 1` significa "modelo em dúvida".
- `SYSTEM_PROMPTS["enrich"]` = texto exato de §6.1 (SYSTEM, com o exemplo de 4 produtos). `SYSTEM_PROMPTS["match"]` = §6.3.
- `enrich_products(conn, config, client, products: Sequence[Product], known_tags: Sequence[str], month=None) -> dict[int, ProductEnrichment]`:
  - Sem produtos → `{}` sem chamada. Divide em fatias de `ENRICH_BATCH_SIZE`, uma chamada por fatia, mescla os dicts. Fatia que falha (`_ask` → `None`) só some do resultado; as outras seguem.
  - User prompt: `f"categorias: {json.dumps(list(known_tags), ensure_ascii=False)}\nprodutos:\n"` + uma linha `f"{p.id} | {p.canonical_name}"` por produto. `max_tokens = 120 * n + 200`.
  - Resposta `{"products": [{"id", "readable_name", "tags", "content"}]}`. Por item: `id` inteiro e ∈ ids enviados (senão descarta o item); `readable_name` string não vazia após `strip()` (senão descarta); `tags` lista de 1–3 strings → `strip().lower()`, sem vazias, sem duplicatas mantendo ordem, corta em 3 (lista vazia/tipo errado → descarta o item); `content`: `null` → `None`; objeto com `quantity` numérico `> 0` e `unit` em `{L, KG, UN}` após `strip().upper()` → `ContentSuggestion`; **inválido → `content=None` mas o item fica** (nome e tags ainda valem).
  - Ids duplicados na resposta: o primeiro vence.
- `match_products(conn, config, client, term: str, catalog: Sequence[tuple[int, str, tuple[str, ...]]], month=None) -> list[int]`:
  - `catalog` vazio ou `term` em branco → `[]` sem chamada.
  - User prompt: `f"termo: {term}\ncatálogo:\n"` + `f"{id} | {name} | {', '.join(tags)}"` por linha (tags vazias → linha termina em `| `). `max_tokens = 200`.
  - Resposta `{"ids": [...]}`: mantém só inteiros presentes no catálogo, sem duplicatas, na ordem devolvida. Qualquer outro formato → `[]`.
- Ambas nunca lançam; IA indisponível → `{}`/`[]`.

### Validação e erros
- Toda validação acima acontece no serviço; nada de tipo/faixa chega ao chamador sem checagem.

## Especificação técnica

```
modificar julius/domain/models.py
modificar julius/services/suggestions.py
modificar tests/test_services_suggestions.py
```

`grep -rn confidence tests/ julius/` deve sobrar só em `MergeSuggestion`/merge.

## Testes obrigatórios

1. `test_enrich_prompt_lists_categories_and_id_name_lines` — `calls[0][1]` contém `categorias: ["carnes", …]` e `"60 | LING FGO RESF AURORA kg"`.
2. `test_enrich_parses_valid_batch_with_null_and_object_content` — 3 produtos; tags normalizadas (`" Carnes "` → `carnes`, duplicata removida); `content` `null` → `None`; `{"quantity": 1.5, "unit": "l"}` → `ContentSuggestion(1.5, "L")`.
3. `test_enrich_drops_items_with_unknown_id_or_bad_name_or_bad_tags_but_keeps_others` — parametrizado.
4. `test_enrich_invalid_content_keeps_item_with_content_none` — `{"quantity": 500, "unit": "G"}` e `{"quantity": -1, "unit": "L"}`.
5. `test_enrich_splits_into_batches_of_25` — 60 produtos → 3 chamadas com 25/25/10 linhas; resultado tem 60 chaves.
6. `test_enrich_failed_batch_only_loses_that_batch` — 2ª fatia responde erro duas vezes → resultado tem só ids da 1ª e 3ª.
7. `test_enrich_max_tokens_formula` — 6 produtos → 920.
8. `test_enrich_unavailable_returns_empty_dict_without_calls`.
9. `test_match_products_returns_known_ids_in_order_without_duplicates` — resposta `[61, 999, 60, 61]` com catálogo {60, 61} → `[61, 60]`.
10. `test_match_products_prompt_has_term_and_catalog_lines_with_tags`.
11. `test_match_products_empty_catalog_or_blank_term_does_not_call`.
12. `test_match_products_non_object_payload_returns_empty`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `python -c "from julius.services import suggestions as s; print(sorted(s.PROMPT_VERSIONS))"` → `['enrich', 'match', 'merge']`.

## Notas para o agente
- O exemplo few-shot do prompt de enriquecimento mostra `AC MASC F TER ES 1kg` **mantido** como está: é a instrução "na dúvida, não invente" em forma de exemplo. Não "melhore" o exemplo.
- Não peça `confidence` no enriquecimento: dúvida é expressa por 2–3 tags, não por número (decisão Q4 dos requisitos).
