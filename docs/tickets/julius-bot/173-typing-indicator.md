# 173: "digitando..." antes de responder

<!-- status:done -->
<!-- adjustments: (1) a chamada virou um helper só, `_show_typing(update, context)`, reaproveitado
por on_text e on_tap, em vez de duplicar a chamada + try/except nos dois -- mesmo espírito de
`_send`/`_keyboard`, que já são helpers compartilhados neste arquivo. (2) Os testes obrigatórios
foram escritos contra `_show_typing` isoladamente (com um "context" fake e `update.effective_chat`
via o `_update()` que `test_bot_app.py` já tinha para `_authorized`), não contra `on_text`/`on_tap`
inteiros -- nenhum teste deste arquivo hoje monta um `Update`/`context` completo o bastante pra
exercitar um handler de ponta a ponta (é deliberado: só bot/app.py sabe o que é um Update, e a
lógica de verdade já é coberta via handle_text/handle_tap em test_bot_turn.py/test_e2e.py). Testar
o helper cobre exatamente o comportamento que este ticket pede, sem inventar um padrão de mock
novo para o arquivo inteiro. -->

> Uma chamada nativa do Telegram (`send_chat_action`), sem `asyncio.sleep` — a pesquisa trazida pelo usuário aponta o indicador como o ganho documentado; um atraso artificial em cima da latência real da IA (já ~1–2s) arriscaria passar dos ~3s onde a responsividade percebida cai.

## Contexto

Segue o design v2.7.1, achado extra do relatório `claudedocs/research_chatbot_humanizacao_20260918.md` (seção 2, "Latência de resposta / digitando..."). Independente de 170–172 — não toca em `render.py`/`suggestions.py`.

**Nota de estado**: `julius/bot/app.py` tem uma mudança não commitada de fora desta trilha (`on_error`, handler de falha de rede no polling) — não reverter, este ticket soma em cima dela.

## Escopo

### Dentro
- `on_text`: `await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)` logo após a checagem de allowlist e de `update.message`/`update.message.text`, antes de `handle_text`.
- `on_tap`: mesma chamada, logo após a checagem de allowlist e do parse do `nonce`/`verdict`, antes de `handle_tap`.
- Import novo: `ChatAction` de `telegram.constants` (junto do `ParseMode` que já vem de lá).

### Fora
- Qualquer `asyncio.sleep`/atraso artificial — decisão deliberada, ver a nota acima e o design.
- `start` (comando `/start`) — resposta fixa, instantânea por natureza, não precisa do indicador.
- Mexer em `on_error` — é do usuário, fora desta trilha.

## Requisitos

### Funcionais
- A chamada de `send_chat_action` acontece **depois** da checagem de allowlist (nunca revela "estou digitando" pra quem está fora dela — mesma disciplina de silêncio do resto do bot).
- Falha de rede na chamada de `send_chat_action` (ex.: timeout) não pode derrubar o turno — a resposta de verdade (`_send`) continua sendo tentada mesmo se o indicador falhar.

### Validação e erros
- Nenhum teste deve depender de latência real — `send_chat_action` é mockável/observável como qualquer chamada do `python-telegram-bot` (ver padrão de teste abaixo).

## Especificação técnica

```
modificar julius/bot/app.py       — import ChatAction; send_chat_action em on_text e on_tap
modificar tests/test_bot_app.py   — testes do indicador
```

### Padrão a seguir
- `_send`/`_keyboard` (mesmo arquivo) são os únicos lugares que hoje chamam a API do Telegram fora dos handlers — `send_chat_action` é mais uma chamada direta em `context.bot`, sem precisar de wrapper novo.
- Para testar sem subir um bot de verdade: um "context" fake com `context.bot` como `unittest.mock.AsyncMock()` (ou equivalente já usado em outro teste deste arquivo, se houver) — confirme a chamada com `context.bot.send_chat_action.assert_awaited_with(...)`, não com uma chamada de rede real.
- Envolver a chamada num `try/except Exception: pass` (ou logar em `DEBUG`, como `_send` já faz pro `BadRequest` do HTML) se `send_chat_action` puder lançar em cenário de rede ruim — confirme contra a biblioteca (`python-telegram-bot`) qual exceção ela levanta antes de decidir o tipo exato a capturar.

## Testes obrigatórios

1. `test_show_typing_sends_the_action_for_the_right_chat` — `_show_typing` chama `context.bot.send_chat_action` com `action=ChatAction.TYPING` e o `chat_id` certo.
2. `test_show_typing_without_a_chat_sends_nothing` — `update.effective_chat is None` → nenhuma chamada.
3. `test_show_typing_failure_is_swallowed` — `send_chat_action` lança → `_show_typing` não propaga.
4. `test_no_module_level_sleep_is_used_for_the_typing_delay` — `"asyncio.sleep"` não aparece no arquivo.
5. A checagem de que `on_text`/`on_tap` chamam `_show_typing` **depois** da allowlist é por leitura de código (ver Requisitos) — a allowlist já teria feito `_authorized`/`_refuse` retornar antes de qualquer chamada de rede, mesmo padrão do resto do arquivo.

## Critérios de aceite
- [x] `.venv/bin/pytest -q` verde.
- [x] `grep -n "ChatAction" julius/bot/app.py` mostra o import e as duas chamadas (`on_text`, `on_tap`, via `_show_typing`).
- [x] `grep -n "asyncio.sleep(" julius/bot/app.py` **vazio** — nenhum atraso artificial, por desenho (a string "asyncio.sleep" sem parênteses aparece só na prosa do docstring de `_show_typing`, explicando a decisão).

## Notas para o agente

- Não adicione `asyncio.sleep` "só um pouquinho" — é exatamente a escolha que o design descartou, com o motivo escrito. Se o smoke (174) mostrar que o indicador pisca rápido demais no caminho sem IA (client=None, resposta em <50ms), isso é dado novo pra decidir depois, não licença pra adicionar o sleep aqui sem medir.
- `update.effective_chat.id` pode ser `None` em teoria (mesmo padrão que `_authorized` já trata) — mas nesse ponto do fluxo `_authorized` já passou, então `effective_chat` não é `None`; não adicione checagem redundante.
