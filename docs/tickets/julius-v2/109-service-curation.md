# 109: Serviço `curation` — propostas, aplicação e duplicatas

> Traduz o que a IA disse sobre cada produto em decisões determinísticas ("aplica sozinho" × "pergunta"), grava o que for confirmado numa transação, e encontra pares candidatos a duplicata para a IA julgar. Sem imprimir nada, sem perguntar nada.

## Contexto

`docs/design/ai-v2.md` §4.6 (contratos e a medição do corte 75 no catálogo real de 70 produtos), §4.1 (`ProductProposal`, `DuplicateCandidate`), §0 (decisões: nome legível automático só para nome cru; conteúdo sempre confirmado; fusão nunca automática).

Depende de 104 (`untagged_product_ids`, `has_raw_name`) e 108 (`enrich_products`, `suggest_merges`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/domain/models.py`: `ProductProposal` (com property `auto_tag`), `DuplicateCandidate`.
- `julius/services/curation.py` (novo): `DUPLICATE_CANDIDATE_CUTOFF = 75`, `MAX_DUPLICATE_PAIRS = 20`, `pending_product_ids`, `propose`, `apply`, `duplicate_candidates`, `judge_duplicates`.
- `tests/test_services_curation.py` (novo).

### Fora
- Qualquer interação/impressão (→ 112). Fundir produtos (nunca). Cache de propostas.

## Requisitos

### Funcionais
- `ProductProposal(product_id: int, current_name: str, readable_name: str | None, tags: tuple[str, ...], tag_is_known: bool, content: ContentSuggestion | None)`; `auto_tag -> str | None` devolve `tags[0]` **somente** se `len(tags) == 1 and tag_is_known`.
- `DuplicateCandidate(product_a: Product, product_b: Product, text_similarity: float, ai: MergeSuggestion | None)`.
- `pending_product_ids(conn) -> list[int]` = `products.untagged_product_ids(conn)`.
- `propose(conn, config, client, product_ids) -> list[ProductProposal]`:
  - Carrega cada id com `products.get_product` (ids inexistentes são ignorados); `known = products.all_tag_names(conn)`; `enrichment = suggestions.enrich_products(conn, config, client, produtos, known)`.
  - Uma proposta por produto **que tem** enriquecimento, na ordem de `product_ids`; produto sem enriquecimento (fatia falhou, item descartado) não gera proposta.
  - `readable_name = None` quando: `not products.has_raw_name(conn, id)` (usuário já renomeou à mão) **ou** `enrichment.readable_name.strip().casefold() == product.canonical_name.strip().casefold()`. Senão o nome do modelo, `strip()`ado.
  - `tags = enrichment.tags`; `tag_is_known = tags[0] in known`.
  - `content = None` se `product.content_quantity is not None`; senão `enrichment.content`.
- `apply(conn, proposal, *, tag: str | None, content: bool) -> None` — **uma** transação (`with conn:` chamando repositórios direto, não `catalog.*`, que abrem transações próprias): `products.rename_product` se `readable_name`; `products.add_tag(conn, id, tag.strip().lower())` se `tag` (em branco → `ValueError` antes de tocar o banco); `products.set_content(conn, id, q, u)` se `content and proposal.content`. Nada mais.
- `duplicate_candidates(conn, product_ids: Sequence[int] | None = None) -> list[tuple[Product, Product, float]]`:
  - Universo = `products.list_products(conn)`. Escopo = os `product_ids` dados (ou todos). Para cada produto do escopo × cada outro produto do universo (`id` diferente): `fuzz.token_set_ratio(normalize_text(a), normalize_text(b))`; mantém `>= DUPLICATE_CANDIDATE_CUTOFF`.
  - Pares únicos (mesmo par nas duas ordens conta uma vez; menor id primeiro), ordenados por score desc e depois `(id_a, id_b)`, cortados em `MAX_DUPLICATE_PAIRS`. `text_similarity = score / 100`.
- `judge_duplicates(conn, config, client, candidates, month=None) -> list[DuplicateCandidate]`:
  - Vazio → `[]`. Chama `suggestions.suggest_merges` com `(a.canonical_name, b.canonical_name)` de cada par (uma chamada). Devolve **só** os pares cuja sugestão existe e tem `same_product=True`, com `ai` preenchido. IA indisponível → `[]` (nenhuma sugestão só por texto: decisão v1 mantida).
- Nenhuma função lança por falha de IA; `apply` pode lançar `LookupError`/`ValueError` (é escrita, o chamador trata).

### Validação e erros
- `apply` com `tag` em branco → `ValueError("tag must not be blank")`; produto inexistente → `LookupError` dos repositórios.

## Especificação técnica

```
modificar julius/domain/models.py
criar     julius/services/curation.py
criar     tests/test_services_curation.py
```

Imports de `curation.py`: `sqlite3`, `itertools`, `rapidfuzz.fuzz`, `julius.config`, `julius.domain.models`, `julius.domain.normalization.normalize_text`, `julius.infra.llm_client.LlmClient`, `julius.repositories.products`, `julius.services.suggestions`.

Medição de referência (banco real, 70 produtos): pares verdadeiros `TOMATE ITALIANO kg` × `TOMATE ITALIANO UNIAO kg`, `CEBOLA kg` × `CEBOLA UNIAO kg`, `SACOLA REUTILIZAVEL UND` × idem pontuam 100; em 75 entram também `AG CRYSTAL C/G` × `S/G` (95), `TEMP CORAL … TRAD/CHICKEN/BEEF` (89,8), `AVEIA QUAK 450G FINO` × `REGU` (85,7), `PICANHA BOV FAT kg PROMO` × `FRALDINHA BOV PROMO kg` (82,6), `MANGA ROSA` × `MANGA PALMER` (76,2) — 15 pares no total, que é o que a IA julga.

## Testes obrigatórios (`tests/test_services_curation.py`; banco via `import_receipt` dos fixtures reais; `ScriptedLlmClient` de `tests/_fakes.py`)

1. `test_pending_product_ids_lists_untagged_in_id_order`.
2. `test_propose_single_known_tag_is_auto` — `auto_tag == "carnes"`.
3. `test_propose_two_tags_or_unknown_tag_is_not_auto` — parametrizado: `["mercearia", "bebidas"]` → `auto_tag is None`; `["ovos"]` (não semeada) → `tag_is_known False`, `auto_tag None`.
4. `test_propose_keeps_readable_name_none_for_manually_renamed_product` — `catalog.rename_product` antes; modelo devolve outro nome → `readable_name is None`.
5. `test_propose_readable_name_none_when_model_returns_same_name_ignoring_case`.
6. `test_propose_content_none_when_already_defined` — `set_product_content` antes.
7. `test_propose_omits_products_without_enrichment_and_ignores_unknown_ids`.
8. `test_apply_renames_tags_and_sets_content_in_one_transaction` — verifique os três efeitos e que `has_raw_name` vira `False`.
9. `test_apply_with_tag_none_and_content_false_only_renames`.
10. `test_apply_blank_tag_raises_and_changes_nothing`.
11. `test_duplicate_candidates_on_five_receipts_include_the_three_true_pairs_and_nothing_below_cutoff` — importar os 5 fixtures; resolver ids pelos nomes; asserir os 3 pares presentes, todos os scores `>= 0.75`, `len <= 20`, ordenação desc.
12. `test_duplicate_candidates_scoped_to_ids_only_pairs_them_with_others` — escopo `[id_tomate_uniao]` → pares contêm sempre esse id.
13. `test_judge_duplicates_keeps_only_same_product_true_with_ai_attached`.
14. `test_judge_duplicates_without_ai_returns_empty` — `config` sem chave.
15. `test_judge_duplicates_empty_candidates_does_not_call`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; `tests/test_architecture.py` verde.
- [ ] `grep -n "print\|typer\|rich" julius/services/curation.py` vazio.

## Notas para o agente
- `token_set_ratio` dá 100 para nome contido no outro ("TOMATE ITALIANO kg" ⊂ "TOMATE ITALIANO UNIAO kg") — é intencional: o texto só pré-filtra, quem decide é a IA.
- Não use `confidence` da IA para filtrar duplicatas: `same_product` basta; a confiança vai para a impressão (→ 112).
