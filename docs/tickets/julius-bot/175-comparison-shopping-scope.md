# 175: `services/comparison.py` — escopo por itens e veredito agregado

> `compare_stores` aprende a comparar só o que foi pedido, e uma função nova conta vitórias por loja em vez de deixar a IA somar.

## Contexto

`docs/design/shopping-list-conversation-context.md`, Decisões 1–3. `compare_stores(conn)` hoje (`julius/services/comparison.py:18`) sempre itera **todo** produto com `kind` definido — 16 grupos no catálogo real, o que causou o textão medido em `ai_calls.jsonl` (2026-09-19T17:42:52, narração truncando duas vezes por excesso de grupos). Este ticket não muda o algoritmo de agrupamento nem a base de comparação (`comparison_basis`) — só dá a ele um filtro de entrada e uma segunda função que resume o resultado.

Não depende de nenhum ticket anterior a este; é a base da trilha (176–179 dependem deste).

## Escopo

### Dentro
- `compare_stores` ganha parâmetro opcional `kinds: Sequence[str] | None = None`.
- Nova função `shopping_verdict(comparison: StoreComparison) -> ShoppingVerdict | None`.
- `domain/models.py`: novo dataclass `ShoppingVerdict`.
- `tests/test_services_comparison.py`: casos novos.

### Fora
- `bot/actions.py`, `bot/render.py`, `bot/agent.py`, `bot/turn.py` (→ 176, 177, 178, 179).
- Casar texto livre ("leite") com `kind` — fica no ticket 176; aqui `kinds` já chega como lista de valores de `kind` corretos.
- `cli/stores.py`/`julius mercados comparar` — continuam chamando `compare_stores(conn)` sem `kinds`; comportamento idêntico ao de hoje, sem mudança de arquivo.

## Requisitos

### Funcionais

- `compare_stores(conn, kinds=None)`: quando `kinds` é uma sequência não vazia, a lista `typed` (hoje `services/comparison.py:22`) filtra por `product.kind in set(kinds)`, além do filtro `product.kind is not None` que já existe. `kinds=None` e `kinds=()` são equivalentes ao comportamento de hoje — nenhuma outra linha da função muda (agrupamento, `comparison_basis`, ordenação por preço continuam iguais).

- Novo dataclass, `domain/models.py`, ao lado de `StoreComparison`:
  ```python
  @dataclass(frozen=True)
  class ShoppingVerdict:
      total_items: int
      winner_stores: tuple[str, ...]    # mais de um só em empate exato no topo
      won_kinds: tuple[str, ...]        # kinds vencidos por qualquer loja de winner_stores
      runner_up_store: str | None       # loja mais barata ENTRE OS ITENS QUE SOBRARAM; None se nada sobrou
      runner_up_kinds: tuple[str, ...]
  ```

- `shopping_verdict(comparison)`:
  1. `comparison.comparisons` vazio → devolve `None`.
  2. Para cada `KindComparison` do grupo, o vencedor é `group.entries[0]` (já vem ordenado, mais barato primeiro — `services/comparison.py:53`). Contar vitórias por `store_cnpj` (nunca por `store_nickname` — duas filiais da mesma rede podem compartilhar apelido; mesmo cuidado que `render_comparison` já toma em `bot/render.py:249`).
  3. `total_items = len(comparison.comparisons)`.
  4. `winner_stores`: a(s) loja(s) com o maior número de vitórias — mais de uma só quando há empate exato no topo. Resolver `store_cnpj` → nome com `domain.formatting.store_labels(comparison)` (a mesma função que `render.py` já usa, nunca duplicar dois apelidos de filiais).
  5. `won_kinds`: os `kind` cujo vencedor está em `winner_stores`, na ordem de `comparison.comparisons`.
  6. Grupos restantes = os cujo vencedor não está em `winner_stores`. Vazio → `runner_up_store = None`, `runner_up_kinds = ()`.
  7. Havendo restantes: `runner_up_store` é a loja com mais vitórias **só entre os restantes** (nome único — ponytail: empate no 2º lugar não é desempatado à parte, fica com o primeiro por `sorted()`; ajustar se algum dia isso incomodar de verdade, não é caso medido). `runner_up_kinds` são os `kind` que essa loja venceu dentro do subconjunto restante.

### Validação e erros
- `shopping_verdict` é função pura sobre dado já validado; nunca lança, nunca faz I/O.

## Especificação técnica

```
modificar julius/services/comparison.py — compare_stores(conn, kinds=None); nova shopping_verdict(comparison)
modificar julius/domain/models.py       — novo ShoppingVerdict
modificar tests/test_services_comparison.py
```

### Padrão a seguir
- A contagem de vitórias por loja **já existe** em `bot/render.py::render_comparison` (linhas 246–256, a tabela crua de hoje: "mais barato em N de M grupos"). Reaproveitar a mesma ideia (`dict[str, int]` chaveado por `store_cnpj`), aqui virando uma recomendação (vencedor + segundo colocado), não uma tabela com todo mundo.
- `store_labels(comparison)` (`domain/formatting.py`) é a mesma função que resolve CNPJ→nome hoje em `render.py`; não reescreva essa resolução.

## Testes obrigatórios

1. `test_compare_stores_kinds_filters_groups` — catálogo de teste com ≥2 `kind` comparáveis; `compare_stores(conn, kinds=["tomate"])` devolve só o grupo tomate; `compare_stores(conn)` continua com todos.
2. `test_compare_stores_kinds_none_and_omitted_are_same_as_today` — chamar com `kinds=None` e sem o argumento dão o mesmo resultado (regressão do comportamento atual — protege `julius mercados comparar`).
3. `test_shopping_verdict_empty_comparison_is_none` — `StoreComparison((), "", "")` → `None`.
4. `test_shopping_verdict_single_winner` — 3 grupos, uma loja vence 2 e outra 1 → `winner_stores` com 1 nome, `won_kinds` com 2 nomes, `runner_up_store` é a outra loja, `runner_up_kinds` com 1 nome.
5. `test_shopping_verdict_tie_at_top_names_both` — 2 grupos, uma vitória cada → `winner_stores` com as duas lojas, `runner_up_store is None`.
6. `test_shopping_verdict_winner_sweeps_everything` — uma loja vence todos os grupos → `runner_up_store is None`, `runner_up_kinds == ()`.
7. `test_shopping_verdict_uses_cnpj_not_nickname_for_tally` — duas filiais com o mesmo `nickname` e CNPJs diferentes, cada uma vencendo grupos distintos → contadas separadamente (não somadas por engano).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `tests/test_architecture.py` verde.
- [ ] Nenhum teste de CLI (`test_cli_stores.py` ou equivalente) precisou mudar — `julius mercados comparar` continua byte-a-byte igual.

## Notas para o agente

- Não filtre por `unit` nem toque em `comparison_basis`/`basis_value` — `kinds` só restringe **quais produtos entram** antes do agrupamento; o resto é o código de hoje, sem mudança.
- `winner_stores`/`runner_up_store` guardam **nomes** (via `store_labels`), não CNPJ — quem consumir isto depois (ticket 177) escreve texto pronto pra humano, sem precisar de outro lookup.
- Não invente desempate "inteligente" pro segundo colocado (item 7 dos requisitos) — a simplificação é deliberada e está anotada; não é bug.
