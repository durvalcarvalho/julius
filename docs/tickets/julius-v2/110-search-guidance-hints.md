# 110: `search`, `guidance` e `_hints` — três dicas novas, fallback e `reviewed`

> Extrai `records_for_products` de `search_prices` (reuso pelo fallback de IA), expõe o catálogo para `match_products`, e ensina o módulo de dicas a falar de filiais, produtos pendentes de revisão e "encontrado pela IA".

## Contexto

`docs/design/ai-v2.md` §4.7 (assinaturas, ordem das dicas, textos) e `CLAUDE.md` § "Dicas de uso" (princípios: máx. 2, só em vazio/erro/primeira vez, dado × texto). Fato que motiva `SAME_CHAIN_BRANCHES`: filiais compartilham `cnpj[:8]` (Dona de Casa `11832478…`), e agora têm endereço (102).

Depende de 103 (`PriceRecord.store_address`; `Store.address` de 102). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/domain/models.py`: `HintKind` += `"SAME_CHAIN_BRANCHES"`, `"PRODUCTS_PENDING_REVIEW"`, `"FOUND_VIA_AI"`.
- `julius/services/search.py`: `records_for_products(conn, product_ids, limit)` (público; `search_prices` passa a delegar) e `catalog_for_matching(conn)`.
- `julius/services/guidance.py`: `after_import(conn, result, *, reviewed: bool = False)` com as regras/ordem novas; `after_ai_fallback(records)`.
- `julius/cli/_hints.py`: 3 textos novos; separador de `{details}` passa a `" · "`.
- Testes: `tests/test_services_search.py`, `tests/test_services_guidance.py`, `tests/test_cli_hints.py` (+ ajustes em testes de CLI que assertem `", "` entre details).

### Fora
- Chamar IA (o fallback em si é → 111). Novos comandos. Mudar os textos existentes além do separador.

## Requisitos

### Funcionais
- `search.records_for_products(conn, product_ids: Sequence[int], limit: int) -> list[PriceRecord]`: exatamente o que `search_prices` faz depois de resolver ids (busca preços, agrupa por `unit`, `_highlight_and_trim`, ordem por unidade). `search_prices` vira `records_for_products(conn, sorted(_candidate_ids(...)), limit)`. `limit < 1` → `ValueError` nas duas.
- `search.catalog_for_matching(conn) -> list[tuple[int, str, tuple[str, ...]]]`: `(id, canonical_name, tags)` de `products.list_products`, ordenado por `id`.
- `guidance.after_import(conn, result, *, reviewed=False)` produz, **nesta ordem**, cortando em `MAX_HINTS`:
  1. `PRODUCTS_PENDING_REVIEW` — só se `not reviewed` e `n = |{id ∈ result.new_product_ids : produto existe e tags == ()}| > 0`; `details = (str(n),)`.
  2. `SAME_CHAIN_BRANCHES` — agrupe `stores.list_stores(conn)` por `cnpj[:8]`; pegue o primeiro grupo (ordem por radical) com `len >= 2` **e** alguma loja com `nickname == legal_name`; `details = (f"{cnpj} — {address or legal_name}", …)` para até 3 lojas do grupo, ordem por CNPJ.
  3. `FIRST_IMPORT_NAME_STORES` — como hoje.
  4. `PACKAGE_SIZE_IN_DESCRIPTION` — como hoje, mas só se `not reviewed` (a revisão já tratou conteúdo).
- `guidance.after_ai_fallback(records) -> list[Hint]`: vazio → `[]`; senão `[Hint("FOUND_VIA_AI", details)]` com `details` = `f"{product_id} · {canonical_name}"` dos produtos distintos na ordem em que aparecem, no máximo 3, mais `"+N"` se sobrar (mesma convenção de `PACKAGE_SIZE_IN_DESCRIPTION`).
- `_hints.print_hints`: `", ".join(details)` → `" · ".join(details)` (endereços têm vírgula). Textos novos:

  | kind | texto |
  |---|---|
  | `SAME_CHAIN_BRANCHES` | `Filiais da mesma rede: {details}. Dê apelidos que digam onde fica: julius mercados renomear CNPJ "Rede — Bairro"` |
  | `PRODUCTS_PENDING_REVIEW` | `{details} produto(s) novo(s) sem categoria. Nome legível, categoria e conteúdo com ajuda da IA: julius produtos revisar` |
  | `FOUND_VIA_AI` | `Encontrado pela IA, não pelo nome: {details}. Pra achar direto na próxima, renomeie ou marque: julius produtos renomear ID "Nome" / julius produtos tag ID TAG` |

### Validação e erros
- `guidance` continua sob `_hint_producer`: nunca lança, nunca passa de 2.

## Especificação técnica

```
modificar julius/domain/models.py
modificar julius/services/search.py
modificar julius/services/guidance.py
modificar julius/cli/_hints.py
modificar tests/test_services_search.py
modificar tests/test_services_guidance.py
modificar tests/test_cli_hints.py             (separador)
modificar tests/test_cli_receipts.py          (só se algum teste fixar ", " entre details)
```

## Testes obrigatórios

1. `test_services_search.py::test_records_for_products_highlights_per_unit_and_trims_like_search_prices` — mesmo resultado que `search_prices("picanha")` para os ids equivalentes.
2. `test_records_for_products_rejects_limit_below_one`.
3. `test_catalog_for_matching_returns_id_name_tags_sorted_by_id` — com uma tag criada.
4. `test_services_guidance.py::test_after_import_pending_review_when_not_reviewed_and_untagged` — `qrcode-2.html` (1 produto) → `("1",)`; com `reviewed=True` → ausente; após `tag_product` → ausente.
5. `test_after_import_same_chain_branches_lists_both_dona_de_casa_with_addresses` — importar `qrcode-3.html` e `qrcode-4.html`; details com os dois CNPJs e `GUARA II`/`CANDANGOLANDIA`.
6. `test_same_chain_hint_stops_after_both_branches_are_renamed`.
7. `test_after_import_order_and_cap_at_two` — cenário com pendentes + filiais + lojas sem apelido → só os dois primeiros kinds, nessa ordem.
8. `test_package_size_hint_suppressed_when_reviewed` — `qrcode-5.html`, `reviewed=True`, lojas já apelidadas → sem `PACKAGE_SIZE_IN_DESCRIPTION`.
9. `test_after_ai_fallback_lists_unique_products_max_three_plus_n` e `test_after_ai_fallback_empty_records_gives_no_hint`.
10. `test_cli_hints.py::test_every_hint_kind_has_a_text` — já existe; passa a cobrir os 13 kinds automaticamente.
11. `test_print_hints_formats_details_and_prefix` — ajustar para `"PICANHA · FRALDINHA"`.
12. `test_new_hint_texts_contain_their_commands` — `mercados renomear`, `produtos revisar`, `produtos renomear`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n '", ".join' julius/cli/_hints.py` vazio.

## Notas para o agente
- Não coloque a lógica do fallback (chamar IA) em `guidance`: princípio 5 do módulo é "sem IA". `after_ai_fallback` só recebe registros já encontrados.
- `search_prices` não pode mudar de comportamento: os testes existentes de cutoff/highlight são a rede de segurança da extração.
