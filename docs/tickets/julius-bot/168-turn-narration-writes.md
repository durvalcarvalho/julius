# 168: `bot/turn.py` — comentário do Julius nas confirmações de escrita

> `PendingWrite`/`WriteResult`/`WriteFailed` ganham um comentário curto por cima, nunca uma reescrita — o preview, o resumo e o `<code>` de desfazer continuam byte a byte iguais a hoje.

## Contexto

Fecha o design v2.7 para a escrita (RF3). Depende de **163** (`narrate`) e **166** (`Deps.client`); não depende de 164/165/167 (usa fatos diferentes, já prontos).

**Decisão do design**: a IA nunca reescreve o preview/resumo/undo. Ela só acrescenta um comentário — porque `pending.preview` e `result.summary` **já são** o material da narração (texto pronto, montado por `bot/actions.py`), sem precisar de nenhuma função `_facts` nova.

## Escopo

### Dentro
- Helper `_narrate` do ticket 167 é reaproveitado (mesmo módulo, sem duplicar).
- `_render_output`, ramo `PendingWrite`: tenta `_narrate(deps, "confirmação de uma alteração no catálogo", output.preview)`; se vier comentário, `Reply(escape(comentário) + "\n\n" + render_pending(output), pending=output)`; senão, `Reply(render_pending(output), pending=output)` (comportamento de hoje, sem regressão).
- `handle_tap`, depois de `execute`/`WriteFailed`: mesmo padrão — comentário (se vier) prependado a `render_result(...)`/`render_failure(...)`, texto de hoje se não vier ou sem client.
- `handle_tap` precisa de acesso à IA de forma síncrona (não é `async def`, ao contrário de `handle_text`) — chama `suggestions.narrate(...)` **direto** (sem `asyncio.to_thread`, que só existe para não bloquear uma corrotina; `handle_tap` já é síncrona hoje e é chamada assim por `app.py::on_tap`).
- `julius/bot/app.py::on_tap`: passa `client=context.bot_data.get("client")` ao construir `Deps` (o campo já existe desde o 166; só faltava usá-lo aqui).

### Fora
- Qualquer mudança no formato de `pending.preview`/`result.summary`/`WriteFailed` em `bot/actions.py` — o texto que entra como fato continua exatamente o que já existe.
- O `<code>` do undo nunca passa pela IA, nem inteiro nem em parte — ele é concatenado depois da guarda, nunca incluído nos "fatos".
- Guarda de dinheiro para este caso: nenhum dos textos de escrita tem `R$` (renomear, tag, tipo, conteúdo, fusão não mexem em preço) — `narrate` (163) já lida com isso sem código novo aqui.

## Requisitos

### Funcionais
- O botão (✅/❌ do teclado inline) não muda — ele é montado em `app.py::_keyboard`, fora do texto, e continua vindo do `reply.pending`, que este ticket não toca.
- `render_pending`/`render_result`/`render_failure` não mudam — o comentário é sempre concatenado por fora, nunca passado para dentro deles.
- Sem client (`deps.client is None`): nenhuma chamada nova, texto idêntico a antes do ticket.

### Validação e erros
- `handle_tap` continua "nunca lança": se `narrate` falhar (já não lança, mas por precaução de composição), o `finally` que limpa `state.pending` continua no mesmo lugar, antes de qualquer chamada de narração.
- A ordem importa: o comentário só é buscado **depois** de `execute`/`WriteFailed` resolver o resultado real — nunca antes, para não narrar um resultado que ainda pode falhar.

## Especificação técnica

```
modificar julius/bot/turn.py — ramos PendingWrite/WriteResult/WriteFailed em _render_output e handle_tap
modificar julius/bot/app.py  — on_tap passa client ao Deps
modificar tests/test_bot_turn.py — testes de comentário nas 3 saídas de escrita
```

### Padrão a seguir
- O `_narrate` assíncrono do ticket 167, para o ramo `PendingWrite` (dentro de `_render_output`, que já é `async def`).
- Para `handle_tap` (síncrona), chamar `suggestions.narrate(...)` sem `asyncio.to_thread` — não introduza `asyncio` em uma função que hoje não é corrotina só para isso; se o bloqueio incomodar no smoke real, é ajuste do 169, não deste ticket.

## Testes obrigatórios

1. `test_pending_write_gets_a_comment_when_a_client_is_configured` — `reply.text` contém o comentário **e** o `⚠️ Confirmar?` de sempre; `reply.pending` inalterado.
2. `test_pending_write_without_a_client_is_unchanged`.
3. `test_tap_approve_result_gets_a_comment_but_undo_stays_verbatim` — `<code>julius produtos renomear ...</code>` presente e idêntico ao que `render_result` produziria sozinho.
4. `test_tap_write_failed_gets_a_comment_but_reason_stays_verbatim`.
5. `test_tap_deny_and_expired_and_stale_never_call_narrate` — `client.calls == []` nesses três caminhos (não são resultado de escrita real).
6. Suíte inteira de `test_bot_turn.py`/`test_bot_app.py` já existente, verde sem edição fora dos arquivos listados.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "asyncio" julius/bot/turn.py` mostra o mesmo número de ocorrências que o ticket 167 deixou, mais nenhuma dentro de `handle_tap`.
- [ ] Um teste comprova, com uma string de comando de undo real (ex.: `julius produtos renomear 12 "X"`), que ela aparece inteira e sem escape estranho mesmo com um comentário de IA na frente.

## Notas para o agente

- Não deixe a IA "confirmar" nada em palavras (ex.: "prontinho, renomeei") no comentário do `PendingWrite` — nada foi executado ainda nesse ponto; se o prompt do ticket 163 permitir essa ambiguidade em teste manual, é achado para anotar no smoke (169), não conserto silencioso aqui.
- `DENIED_TAP`/`EXPIRED_TAP`/`STALE_TAP` (as três respostas que `handle_tap` devolve sem executar nada) **não** passam por `narrate` — são texto fixo, como já são hoje.
