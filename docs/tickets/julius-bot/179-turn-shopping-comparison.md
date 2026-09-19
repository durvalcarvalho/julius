# 179: `bot/turn.py` — `_render_output` para `ShoppingComparison`

<!-- status:done implemented:2026-09-19 commit:cdc5f0e -->

> O quinto branch de `_render_output`, no mesmo molde exato do de `StoreComparison` — narra quando dá, cai na frase-molde quando não dá.

## Contexto

`docs/design/shopping-list-conversation-context.md`, fechando as Decisões 1–2 em produção. Depende de **175, 176, 177, 178** — é o ticket de integração, precisa de todas as peças novas já existindo (`ShoppingComparison`, `shopping_verdict`, `shopping_comparison_facts`/`shopping_verdict_line`, e `compare_stores` aceitando `items` no roteamento da IA).

## Escopo

### Dentro
- `julius/bot/turn.py::_render_output`: novo branch `isinstance(output, ShoppingComparison)`.
- `tests/test_bot_turn.py`: casos novos.

### Fora
- `ChatState`/`awaiting_topic` — não entra (Decisão 4, condicionado ao smoke).
- Mudar o branch `StoreComparison` existente (linhas 174–186 hoje) — continua exatamente como está; nenhum caminho do bot chama `compare_stores` sem `items` depois do ticket 178, mas o branch antigo não é removido (é o mesmo tipo de dado que a CLI usa por fora do bot).

## Requisitos

### Funcionais

Novo branch em `_render_output`, mesma sequência de decisões do branch `StoreComparison` (`turn.py:174-186` hoje), adaptado:

```python
if isinstance(output, ShoppingComparison):
    base = shopping_verdict_line(output)
    groups = output.comparison.comparisons
    if (not groups and not output.unmatched_terms) or deps.client is None:
        return Reply(base)
    if len(groups) > NARRATE_MAX_GROUPS:
        return Reply(base)
    remark = await _narrate(deps, "veredito de lista de compras", shopping_comparison_facts(output))
    if remark:
        return Reply(escape(remark))
    return Reply(base)
```

- Reaproveita `NARRATE_MAX_GROUPS` (constante já existente, `turn.py:60`) como teto de sanidade — mesmo tipo de dado (contagem de grupos comparáveis), não precisa de constante nova.
- **Sem** o corte extra de `FALLBACK_LINE_MAX_GROUPS` que o branch de `StoreComparison` tem: `shopping_verdict_line` já é curta por natureza (uma frase de veredito, não uma tabela por grupo), diferente de `compare_fallback_line`, que assume poucos grupos porque lista um por um.
- `deps.client is None` cai direto em `base`, exatamente como os outros branches — nunca tenta `_narrate` sem cliente.

### Validação e erros
- Nenhuma exceção nova — `_narrate` já engole erro e devolve `None` (comportamento existente, ticket 163).

## Especificação técnica

```
modificar julius/bot/turn.py — _render_output, imports (ShoppingComparison, shopping_comparison_facts, shopping_verdict_line)
modificar tests/test_bot_turn.py
```

### Padrão a seguir
- O branch `StoreComparison` (`turn.py`, hoje linhas 174–186) é o gabarito exato da estrutura — mesma sequência (`base` → checar cliente/vazio → teto de sanidade → `_narrate` → fallback), só trocando as funções de fato/frase-molde e removendo o corte de `FALLBACK_LINE_MAX_GROUPS` pelo motivo acima.

## Testes obrigatórios

1. `test_render_shopping_comparison_no_client_uses_fallback_line` — `deps.client is None` → `Reply(shopping_verdict_line(output))`.
2. `test_render_shopping_comparison_narrates_when_client_available` — `ScriptedLlmClient` devolve texto → `Reply` é esse texto, escapado.
3. `test_render_shopping_comparison_narration_fails_falls_back` — cliente que devolve vazio/erro → `Reply(shopping_verdict_line(output))`.
4. `test_render_shopping_comparison_above_sanity_cap_skips_ai` — mais grupos que `NARRATE_MAX_GROUPS` → `_narrate` não é chamado (contar chamadas via mock/spy), resposta é `base` direto.
5. `test_render_shopping_comparison_empty_and_no_unmatched_skips_ai` — `comparison.comparisons == ()` e `unmatched_terms == ()` → `Reply(base)` sem tentar `_narrate`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `tests/test_real_ai.py` continua coletando normalmente (o teste real do caminho novo é do ticket 180, não deste).

## Notas para o agente

- Não duplique a guarda de dinheiro dentro deste branch — ela já vive em `_narrate`/`suggestions.narrate` (ticket 163), aplicada a qualquer `context`/`facts` que passem por ali.
- Não remova nem altere o branch `StoreComparison` existente — ele continua correto para quem (fora do bot) comparar sem escopo.
