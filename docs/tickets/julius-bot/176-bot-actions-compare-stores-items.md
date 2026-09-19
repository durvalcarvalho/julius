# 176: `bot/actions.py` — `compare_stores` exige itens, casados com `kind` via `match_kind`

<!-- status:done implemented:2026-09-19 commit:150fa8f -->

> A ação para de aceitar zero argumentos: agora recebe a lista de itens que a pessoa quer comprar, casa cada um com um `kind` conhecido, e nunca esconde em silêncio um item que não achou.

## Contexto

`docs/design/shopping-list-conversation-context.md`, Decisão 1. Depende de **175** (`compare_stores(conn, kinds=...)`, `shopping_verdict`). A ação de hoje (`bot/actions.py:136`) chama `comparison_service.compare_stores(ctx.deps.conn)` sem argumento nenhum — é isso que faz o bot comparar o catálogo inteiro sempre que "qual mercado é mais barato" aciona a ação. Este ticket fecha a metade "casar item↔kind + montar o resultado"; a regra "não chamar a ação sem saber os itens" é texto de prompt e fica no ticket 178.

## Escopo

### Dentro
- `julius/services/search.py`: nova função `match_kind(conn, term: str) -> str | None` e constante `KIND_MATCH_CUTOFF` (valor provisório nesta rodada — medição real fica pro smoke, ticket 180).
- `julius/bot/actions.py`: `compare_stores(ctx, items: tuple[str, ...]) -> ShoppingComparison` (assinatura muda; hoje é `compare_stores(ctx) -> StoreComparison`). Novo dataclass `ShoppingComparison`.
- `tests/test_services_search.py`, `tests/test_bot_actions_read.py`: casos novos.

### Fora
- `SYSTEM_PROMPT`/`agent.py` (→ 178) — este ticket não decide **quando** a IA deve chamar a ação, só o que a ação faz quando é chamada.
- `render.py`/`turn.py` (→ 177, 179).
- Casar item sem `kind` correspondente contra `canonical_name` como plano B — fora de escopo: a ação existe pra comparar entre lojas, que só existe por `kind`; sem `kind` batendo, o item entra em `unmatched_terms`, ponto.

## Requisitos

### Funcionais

`match_kind(conn, term)` (`services/search.py`, ao lado de `detect_tag`):
- Vocabulário: `products.all_kinds(conn)`.
- Sem `kind` nenhum cadastrado → `None` sempre, sem chamar `rapidfuzz`.
- `process.extractOne(normalize_text(term), [normalize_text(k) for k in kinds], scorer=fuzz.ratio, score_cutoff=KIND_MATCH_CUTOFF)`; casamento → devolve o `kind` **original** (não normalizado); sem casamento → `None`.

`compare_stores(ctx, items)` (`bot/actions.py`):
- `items` vazio (`len(items) == 0`) → `ModelRetry("Informe pelo menos um item para comparar.")`.
- Cada item passa por `.strip()`; itens vazios após strip são descartados; se todos ficarem vazios → mesmo `ModelRetry` de cima.
- Para cada item não vazio, `search_service.match_kind(conn, item)`:
  - casou → entra em `matched` (lista de `kind`, sem repetir o mesmo `kind` duas vezes mesmo que dois itens casem com ele);
  - não casou → o termo **original** (como a pessoa/IA escreveu) entra em `unmatched`.
- `matched` não vazio → `comparison = comparison_service.compare_stores(ctx.deps.conn, kinds=matched)`; `matched` vazio → `comparison = StoreComparison((), "", "")` (não chama o serviço à toa).
- `verdict = comparison_service.shopping_verdict(comparison) if comparison.comparisons else None`.
- Devolve `ShoppingComparison(comparison=comparison, verdict=verdict, unmatched_terms=tuple(unmatched))`.

Novo dataclass, `bot/actions.py`, ao lado de `ProductListing`/`StoreListing`:
```python
@dataclass(frozen=True)
class ShoppingComparison:
    comparison: StoreComparison
    verdict: ShoppingVerdict | None
    unmatched_terms: tuple[str, ...]
```

### Validação e erros
- Nenhuma exceção de `services` escapa: mesma regra do ticket 155 (`ValueError` vira `ModelRetry`), embora nesta ação nenhuma chamada de serviço deva lançar `ValueError` no caminho normal.

## Especificação técnica

```
modificar julius/services/search.py — match_kind, KIND_MATCH_CUTOFF
modificar julius/bot/actions.py     — compare_stores(items), ShoppingComparison
modificar tests/test_services_search.py
modificar tests/test_bot_actions_read.py
```

Import novo em `actions.py`: `ShoppingVerdict` de `julius.domain.models` (junto de `StoreComparison`, já importado).

### Padrão a seguir
- `detect_tag` (`services/search.py`, mesmo arquivo) é o modelo do mecanismo — copiar a técnica (`process.extractOne`, `normalize_text`, `score_cutoff`), não a assinatura: aqui é **um termo por vez**, não uma lista de palavras concorrendo por uma única tag.
- `ModelRetry` como única forma de recusa é a mesma regra do ticket 155 (`resolve_product`/`resolve_store`).

## Testes obrigatórios

1. `test_match_kind_exact_and_typo` — termo exato bate com o `kind` certo; erro de digitação de uma letra ainda bate; termo sem relação nenhuma não bate.
2. `test_match_kind_no_kinds_registered_is_none` — catálogo sem nenhum `kind` definido → `None`, sem levantar.
3. `test_compare_stores_action_requires_items` — `{"items": ()}` → `RetryPromptPart` com "Informe pelo menos um item".
4. `test_compare_stores_action_blank_items_are_ignored` — `{"items": ("  ", "tomate")}` → funciona só com "tomate"; `{"items": ("  ",)}` → mesmo retry do caso vazio.
5. `test_compare_stores_action_matches_and_compares` — `{"items": ("tomate",)}` sobre catálogo com o grupo tomate comparável → `ShoppingComparison.comparison.comparisons` tem só esse grupo, `verdict` preenchido, `unmatched_terms == ()`.
6. `test_compare_stores_action_reports_unmatched` — um item que não bate com nenhum `kind` → aparece em `unmatched_terms` com o texto original, os que bateram continuam funcionando.
7. `test_compare_stores_action_all_unmatched_returns_empty_comparison` — nenhum item reconhecido → `comparison.comparisons == ()`, `verdict is None`, `comparison_service.compare_stores` não é chamado (checar via monkeypatch/contador).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `tests/test_architecture.py` verde (`actions.py` continua só importando `domain`, `config`, `services`; `pydantic_ai`).
- [ ] Docstring de `compare_stores` em português, estilo Google, com `Args: items` descrevendo o formato esperado — é o schema que a IA lê.
- [ ] `grep -n "chat_id" julius/bot/actions.py` continua vazio.

## Notas para o agente

- `ModelRetry` é a única forma de recusa (mesma regra do ticket 155) — nunca devolva silêncio nem lista vazia pra "items veio vazio".
- Não tente casar item sem `kind` contra `canonical_name`/`matching_product_ids` como plano B "pra não decepcionar" — um item sem comparação possível é uma resposta honesta ("não sei comparar isso ainda"), não um bug a disfarçar.
- `KIND_MATCH_CUTOFF` desta rodada é provisório — não gaste tempo medindo contra o catálogo real agora, isso é o ticket 180. Escolha um valor razoável (ex.: mesmo ponto de partida de `TAG_MATCH_CUTOFF = 75`) e documente no docstring que é chute a confirmar.
