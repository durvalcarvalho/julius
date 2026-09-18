# 160: `bot/turn.py` — o tap: confirmar, cancelar, expirar

> A segunda passada da escrita: um nonce, um relógio, e nada executa a menos que tudo bata.

## Contexto

`docs/design/telegram-bot.md` §4.3 (fail-closed em todos os caminhos; 5 minutos; nonce no botão) e §4.4 (uma pendência por chat, em memória). O tap chega como um update novo do Telegram; o app (161) traduz o `callback_data` em `(nonce, aprovar)` e chama `handle_tap`. Aqui não há modelo: aprovado → `execute` (156/157) em código; qualquer outra coisa → nada gravado.

Depende de **159**.

## Escopo

### Dentro
- `julius/bot/turn.py`: `PENDING_TTL_SECONDS`, `handle_tap`, `_expired`; ajuste em `handle_text` para tratar pendência **expirada** como ausente (sem o aviso "cancelada").
- `tests/test_bot_turn.py` (acrescenta).

### Fora
- Botões, edição da mensagem no Telegram (→ 161).
- Persistir a pendência entre reinícios (decisão do design: em memória; reiniciar perde, e o tap encontra "não está mais ativa").

## Requisitos

### Funcionais

```python
PENDING_TTL_SECONDS = 300.0

def handle_tap(state: ChatState, deps: Deps, nonce: str, approve: bool, *, now: float | None = None) -> Reply
def _expired(pending: PendingWrite, now: float) -> bool   # now - pending.created_at > PENDING_TTL_SECONDS
```

`now` é injetável (`time.monotonic()` quando `None`) pelo mesmo motivo de `relative_age(today=)`: o teste de expiração não pode depender de dormir.

Ramos de `handle_tap`, nesta ordem, **sempre** limpando `state.pending` num `finally` a partir do ramo 2:

1. `state.pending is None` **ou** `state.pending.nonce != nonce` → `Reply("Essa confirmação não está mais ativa.")` — **não** mexe em `state.pending` (um tap antigo não pode derrubar uma pendência nova).
2. `_expired(pending, now)` → `Reply("Confirmação expirada — nada foi executado.")`.
3. `not approve` → `Reply("❌ Cancelado — nada foi executado.")`.
4. `approve`:
   - `result = execute(deps, pending)` → `Reply(render_result(result))`;
   - `WriteFailed as error` → `Reply(render_failure(str(error)))`;
   - qualquer outra exceção → `Reply(render_failure("erro inesperado; nada foi executado"))` — os serviços escrevem dentro de `with conn:`, então uma exceção no meio já desfez a transação.

`handle_text` (ajuste): se `state.pending` existe **e** está expirada, limpa em silêncio (sem o prefixo "Ação anterior cancelada."); se está viva, comportamento do 159.

### Validação e erros
- Nenhum ramo além do 4 toca o banco — teste lê o estado antes e depois em cada um.
- `state.pending` é `None` depois de qualquer ramo de 2 a 4, **inclusive** quando `execute` lança.
- `handle_tap` é síncrona (não há `await` no caminho) — o app a chama direto do handler assíncrono.

## Especificação técnica

```
modificar julius/bot/turn.py
modificar tests/test_bot_turn.py
```

### Padrão a seguir
- O `finally` que limpa o marcador é a lição registrada em §4.3/§8 do design (uma pendência que não é limpa deixa o chat "travado" para sempre); escreva-o antes dos ramos, não depois.
- Para simular falha inesperada: `monkeypatch.setattr(turn, "execute", lambda deps, pending: 1/0)` (ou o nome pelo qual `turn` importa `execute`).

## Testes obrigatórios

1. `test_tap_with_no_pending_is_inert` — `Reply` "não está mais ativa"; nada no banco.
2. `test_tap_with_wrong_nonce_keeps_the_pending` — pendência viva, nonce errado → mesma mensagem, `state.pending` **continua**.
3. `test_tap_expired_clears_without_executing` — `now = created_at + 301` → "expirada", `state.pending is None`, banco igual.
4. `test_tap_deny_clears_without_executing` — "Cancelado", pendência limpa, banco igual.
5. `test_tap_approve_executes_and_returns_undo` — renomeia de verdade; texto começa com "✅" e contém `<code>julius produtos renomear`; pendência limpa.
6. `test_tap_approve_write_failed_is_reported` — pendência de `merge_products` que forma ciclo → "❌ Não executado:" com a mensagem do serviço; pendência limpa; nada gravado.
7. `test_tap_approve_unexpected_error_clears_pending` — `execute` monkeypatched para lançar → "erro inesperado"; `state.pending is None`.
8. `test_text_after_expired_pending_has_no_cancel_notice` — pendência com `created_at` antiga, `handle_text` (com o `FunctionModel` devolvendo prosa) → resposta **sem** "Ação anterior cancelada." e `state.pending` é a nova (ou `None`).
9. `test_tap_at_exactly_the_ttl_is_still_valid` — `now = created_at + 300.0` → executa (`>`, não `>=`).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "time.sleep" tests/test_bot_turn.py` **vazio** — expiração testada por `now`, nunca dormindo.
- [ ] `handle_tap` não importa nem chama nada de `pydantic_ai`.

## Notas para o agente

- O nonce compara com `==` simples: é um segredo de 8 bytes vivo por 5 minutos, num chat de uma pessoa — `hmac.compare_digest` seria cerimônia.
- Não adicione um `Reply` de "confirmado, executando…" intermediário: a execução é local e sub-milissegundo; a resposta é o resultado.
- `PENDING_TTL_SECONDS` é 300 porque o `majordomo` mediu 120 s derrubando um tap real aos 121 s — se alguém quiser 120, precisa de um dado novo.
