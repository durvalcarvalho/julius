# 015: Serviço guidance

> Diagnóstico determinístico de "por que deu vazio/erro" e "o que fazer agora", devolvido como dado (`Hint`) para a CLI escrever.

## Contexto

Caso real: `julius consultar banana` num banco recém-criado respondia `Nenhum resultado.`. Leia no `CLAUDE.md`: **"Dicas de uso (`guidance`) — v1.1"** inteira (princípios, catálogo de `HintKind`, contratos). Este ticket é a metade "dado"; a metade "texto" é o 016.

Depende de 005 (`importing`) e 006 (`search`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/domain/models.py`: `HintKind` (Literal com os 10 kinds do catálogo), `Hint(kind, details: tuple[str, ...] = ())`, e `ImportResult.new_product_ids: tuple[int, ...] = ()`.
- `julius/services/importing.py`: preencher `new_product_ids` (ids criados naquele import — `products.resolve_product_id` precisa dizer se criou; ver detalhes).
- `julius/repositories/products.py`: `resolve_product_id` passa a devolver `tuple[int, bool]` (`product_id, created`) **ou** ganha uma função irmã `sku_exists(conn, store_cnpj, product_code) -> bool` — escolha a menor mudança que mantenha os testes de 003 verdes (ajustar chamadas/testes existentes está dentro do escopo).
- `julius/services/search.py`: `NEAR_MISS_CUTOFF = 45` e `closest_names(conn, term, limit=3) -> list[tuple[str, int]]`.
- `julius/services/guidance.py`: `MAX_HINTS = 2`, `after_search`, `after_import`, `for_import_error`, `for_compare`.
- `tests/test_services_guidance.py`; ajustes em `tests/test_services_search.py` e `tests/test_services_importing.py` para as funções novas.

### Fora
- Qualquer texto em português ou nome de comando (→ 016). Tocar em `cli/`. Persistir "dica já mostrada". Chamar IA.

## Requisitos

### Funcionais
- `after_search(conn, term, tag, records)`:
  - `records` não vazio → `[]` (nunca dica em resultado cheio).
  - sem nenhuma loja no banco → `[Hint("NO_RECEIPTS_IMPORTED")]` e para.
  - `tag` informada e inexistente (`products.all_tag_names`) → `Hint("UNKNOWN_TAG", tags_existentes)`.
  - `term` informado, sem match, com `closest_names` não vazio → `Hint("NO_MATCH_DID_YOU_MEAN", nomes)`; senão `Hint("NO_MATCH_TRY_TAGS", até 5 tags)`.
- `after_import(conn, result)`:
  - alguma loja com `nickname == legal_name` → `Hint("FIRST_IMPORT_NAME_STORES", (str(quantidade),))`.
  - entre `result.new_product_ids`, os que casam `C/\d+` ou `\d+(,\d+)?\s?(ML|L|G|KG)\b` (regex sobre `canonical_name`, case-insensitive, com `\b`) e ainda **sem** `content_quantity` → `Hint("PACKAGE_SIZE_IN_DESCRIPTION", até 3 `"{id} · {nome}"` + `"+N"` se sobrar)`.
- `for_import_error(error, path)`: `FileNotFoundError` → `IMPORT_FILE_NOT_FOUND` com `str(path)`; `ReceiptParseError` → `IMPORT_NOT_A_RECEIPT` com `path.name`; `UnknownUnitError` → `IMPORT_UNKNOWN_UNIT` com `error.raw_unit`; outros → `[]`.
- `for_compare(config)`: `not config.ai_configured` → `[Hint("AI_NOT_CONFIGURED")]`, senão `[]`.
- `closest_names`: mesma normalização e scorer de `search_prices`; devolve `(canonical_name, score_int)` com `NEAR_MISS_CUTOFF <= score < MATCH_SCORE_CUTOFF`, ordem desc, no máximo `limit`.
- Todas as funções de `guidance` cortam a lista em `MAX_HINTS`.

### Validação e erros
- **`guidance` nunca lança**: qualquer exceção interna (banco fechado, etc.) → `[]`. Dica que falha é dica que não aparece.

## Especificação técnica

```
modificar julius/domain/models.py
modificar julius/services/importing.py
modificar julius/repositories/products.py     (+ tests/test_repositories_products.py se a assinatura mudar)
modificar julius/services/search.py           (+ tests/test_services_search.py)
criar     julius/services/guidance.py
criar     tests/test_services_guidance.py
modificar tests/test_services_importing.py    (+1 teste: new_product_ids)
```

Imports em `guidance.py`: `re`, `sqlite3`, `pathlib`, `julius.config`, `julius.domain.*`, `julius.parsers` (só as exceções), `julius.repositories.{stores,products}`, `julius.services.search`.

## Testes obrigatórios (`tests/test_services_guidance.py`, cenários via `import_receipt` + fixtures reais)

1. `test_after_search_returns_nothing_when_there_are_results`
2. `test_after_search_empty_db_says_no_receipts` — e **só** isso, mesmo com `tag` inexistente.
3. `test_after_search_did_you_mean_lists_near_misses` — banco com `qrcode.html`, termo `"picanh"`? não: esse casa. Use `"pikanha"` ou outro que fique entre 45 e 70 — meça e fixe o termo que cai na faixa; a asserção é que o nome de picanha aparece em `details`.
4. `test_after_search_suggests_tags_when_nothing_is_close` — termo `"carne"` → `NO_MATCH_TRY_TAGS`; `details` contém as tags existentes (crie uma antes).
5. `test_after_search_unknown_tag_lists_existing_tags`
6. `test_after_import_flags_stores_without_nickname_then_stops_after_rename`
7. `test_after_import_flags_package_size_only_for_new_products_without_content` — `qrcode-5.html` (tem `1,5L`, `500G`, `C/30`): dica presente, no máximo 3 nomes + `"+N"`; reimportar → `new_product_ids` vazio → sem essa dica; definir conteúdo em um deles e importar outro arquivo novo → ele não reaparece.
8. `test_for_import_error_maps_each_exception_type` (parametrizado nos 3 tipos + um `RuntimeError` → `[]`).
9. `test_for_compare_only_when_ai_not_configured`
10. `test_hints_are_capped_at_two`
11. `test_guidance_never_raises_on_closed_connection`
12. Em `test_services_search.py`: `test_closest_names_returns_scores_in_near_miss_band_only` e `test_closest_names_empty_when_nothing_close`.
13. Em `test_services_importing.py`: `test_new_product_ids_lists_only_products_created_in_this_call` — primeiro import: 15 ids para `qrcode.html`; reimport: `()`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira, inclusive os testes de 003/005/006 ajustados).
- [ ] `grep -n "julius " julius/services/guidance.py` vazio — nenhum nome de comando no serviço.

## Notas para o agente
- Não reaproveite `rapidfuzz` direto em `guidance`; use `search.closest_names` (mesma normalização, um lugar só).
- `HintKind` como `Literal` de strings, não `Enum`: é o padrão já usado (`SaleUnit`, `Highlight`) e serializa trivialmente.
