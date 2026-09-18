# 161: `bot/app.py` e `julius-bot` — partida, handlers, allowlist, polling

> O único módulo que sabe o que é um `Update`. Tudo o que ele faz é: recusar subir aberto, checar quem fala, abrir a conexão do turno e entregar a resposta.

## Contexto

`docs/design/telegram-bot.md` §2 (módulo `app`), §2.1 (partida fail-fast, teto do logger), §2.2 (allowlist é o primeiro `if`, e é o bootstrap do próprio usuário), §4.3 (botões com nonce, mensagem editada com o desfecho) e §8 (adaptações do `majordomo`). Long polling, sem webhook (F3/F4). Processamento **sequencial** de updates (default do PTB): o turno de texto termina ao mandar a pergunta, e o tap é um update novo — não há espera bloqueante nem lock por chat.

Depende de **151** (`Config.bot_*`), **153** (dependências), **160** (`handle_text`/`handle_tap`).

## Escopo

### Dentro
- `julius/bot/app.py`: `main`, `check_startup`, `configure_logging`, `build_application`, `_authorized`, `_keyboard`, os três handlers, `_send`.
- `julius/bot/__init__.py`: `from julius.bot.app import main` (o que o script chama).
- `pyproject.toml`: `[project.scripts] julius-bot = "julius.bot:main"`.
- `Makefile`: alvo `install-bot` (`pipx install --force --editable '.[bot]'`) e `.PHONY`.
- `tests/test_bot_app.py`.

### Fora
- `systemd`/autostart (decisão dos requisitos §5: `julius-bot` na mão até incomodar).
- Fotos, voz, documentos, grupos com mais de um humano, comandos além de `/start`.
- Responder a quem não está na allowlist (silêncio + log, por decisão).

## Requisitos

### Funcionais

**`main() -> None`**
1. `settings = config.load()`.
2. `check_startup(settings)` — imprime em `stderr` e `raise SystemExit(2)` na primeira falha, nesta ordem:
   - `not settings.bot_token` → `JULIUS_BOT_TOKEN não definido — crie o bot no @BotFather e exporte o token.`
   - `settings.bot_allowed_chat_id is None` → `JULIUS_BOT_ALLOWED_CHAT_ID não definido — o bot não sobe aberto. Para descobrir seu chat_id: exporte JULIUS_BOT_ALLOWED_CHAT_ID=0 (ninguém autorizado), suba o bot, mande /start e leia "mensagem ignorada de chat_id=…" no log; depois exporte o número e reinicie.`
     `0` é o modo de **bootstrap**: nenhum chat do Telegram tem id 0, então `_authorized` nunca é verdadeiro e o bot só registra quem escreveu — continua fechado, sem terceiro (`@userinfobot`) na volta.
   - IA não configurada com preços (`ai_configured` e os dois preços não `None`) → `IA não configurada (JULIUS_AI_API_KEY, JULIUS_AI_BASE_URL, JULIUS_AI_MODEL e os dois preços por token) — o bot roteia toda mensagem pela IA; não existe modo sem ela.`
3. `db.connect(settings.db_path).close()` — abre e fecha uma vez: roda migrações pendentes agora, não no primeiro turno.
4. `configure_logging()` — `logging.basicConfig(level=INFO)` e `logging.getLogger(n).setLevel(WARNING)` para `n in ("httpx", "httpcore")`: em `INFO` a URL do `getUpdates` sai no log **com o token dentro**.
5. `agent = build_agent(settings)`; `application = build_application(settings, agent)`; `application.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)`. `drop_pending_updates=True`: mensagens mandadas enquanto o PC estava desligado não são respondidas na volta (RNF3 — indisponível é indisponível; ver questão aberta no `index.md`).

**`build_application(settings, agent) -> Application`** — `Application.builder().token(settings.bot_token).build()` e três handlers, nesta ordem: `CommandHandler("start", …)`, `MessageHandler(filters.TEXT & ~filters.COMMAND, …)`, `CallbackQueryHandler(…, pattern=r"^confirm\|")`. `settings` e `agent` ficam em `application.bot_data` (`"settings"`, `"agent"`), não em globais.

**`_authorized(update, settings) -> bool`** — `update.effective_chat is not None and update.effective_chat.id == settings.bot_allowed_chat_id`. Falso → o handler faz `log.info("mensagem ignorada de chat_id=%s (fora da allowlist)", chat_id)` e **retorna sem responder**. Essa linha de log é o bootstrap: na primeira vez, o usuário sobe com `JULIUS_BOT_ALLOWED_CHAT_ID=0`, manda `/start`, lê o próprio `chat_id`, exporta o número e reinicia.

**Handlers** (todos começam por `_authorized`):
- `/start` → `_send(update, "Julius pronto. Pergunte um preço («quanto paguei de banana?»), compare mercados, ou peça uma correção do catálogo — escritas pedem confirmação.")`.
- Texto → `state = context.chat_data.setdefault("state", ChatState())`; `conn = db.connect(settings.db_path)`; `try: reply = await handle_text(agent, state, Deps(conn, settings), update.message.text) finally: conn.close()`; `_send(update, reply.text, keyboard=_keyboard(reply.pending.nonce) if reply.pending else None)`.
- Callback → `await query.answer()`; `_, nonce, verdict = query.data.split("|", 2)` (`ValueError` → `answer` e retorna); `conn` como acima; `reply = handle_tap(state, deps, nonce, verdict == "y")`; edita a mensagem original acrescentando `\n\n{desfecho}` (`✅ Confirmado` / `❌ Cancelado` / `⏰ Expirado` / `⚠️ Não executado`, conforme o texto da `Reply`) e `reply_markup=None`; depois envia `reply.text`. Falha ao editar (mensagem antiga demais) → log em `debug`, segue.

**`_keyboard(nonce) -> InlineKeyboardMarkup`** — uma linha: `("✅ Confirmar", f"confirm|{nonce}|y")`, `("❌ Cancelar", f"confirm|{nonce}|n")`.

**`_send(update, text, keyboard=None)`** — `reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)`; se o Telegram recusar o HTML (`BadRequest` com "parse"), reenvia **sem** `parse_mode` — um nome de produto exótico não pode calar o bot.

### Validação e erros
- Nenhuma variável de ambiente é lida fora de `config.load()`; o token nunca aparece em log nem em mensagem.
- `import julius.bot.app` não abre banco nem rede (mesma regra do `import julius.cli`).

## Especificação técnica

```
criar     julius/bot/app.py
modificar julius/bot/__init__.py     — from julius.bot.app import main
modificar pyproject.toml             — [project.scripts] julius-bot
modificar Makefile                   — install-bot
criar     tests/test_bot_app.py
```

### Padrão a seguir
- `cli/_common.py::open_db` / `fail`: abrir conexão **dentro** do handler e fechar em `finally`; erro de partida em `stderr` com código de saída ≠ 0.
- `majordomo/src/adapters/chat/telegram.py::request_approval` (referência, não dependência): nonce no `callback_data`, edição da mensagem com o desfecho, botões removidos depois.

## Testes obrigatórios

1. `test_check_startup_without_token_exits_2` — `SystemExit(2)` e a mensagem com `JULIUS_BOT_TOKEN` em `capsys.readouterr().err`.
2. `test_check_startup_without_allowlist_exits_2` — idem, mensagem cita `chat_id` e `/start`.
3. `test_check_startup_without_ai_exits_2` — token e chat definidos, IA não → mensagem cita `JULIUS_AI_API_KEY`.
4. `test_check_startup_passes_when_everything_is_set` — não lança.
5. `test_authorized_compares_effective_chat_id` — `SimpleNamespace(effective_chat=SimpleNamespace(id=1))` contra `bot_allowed_chat_id=1` → `True`; `2` → `False`; `effective_chat=None` → `False`; `bot_allowed_chat_id=0` contra **qualquer** id real → `False` (o modo bootstrap nunca autoriza).
6. `test_keyboard_callback_data_carries_the_nonce` — dois botões; `callback_data` `confirm|abc|y` e `confirm|abc|n`.
7. `test_configure_logging_caps_httpx_and_httpcore` — níveis `WARNING` depois da chamada.
8. `test_build_application_registers_three_handlers` — token `"123:abc"` (offline; construir não conecta); `application.handlers[0]` tem 3 handlers; `bot_data["agent"]` é o agente passado (use `build_agent(config, model=FunctionModel(...))`).
9. `test_importing_the_app_has_no_side_effects_on_disk` — mesmo subprocess de `tests/test_cli.py`, com `import julius.bot.app`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; `tests/test_architecture.py` verde (`app.py` importa `config`, `infra`, `bot`).
- [ ] `grep -n "os.environ\|getenv" julius/bot/` **vazio**.
- [ ] `grep -n "julius-bot" pyproject.toml Makefile` mostra o script e o alvo.
- [ ] `make install-bot` deixa `julius-bot --help`? Não há `--help`: `julius-bot` sem variáveis termina com código 2 e a primeira mensagem de partida.

## Notas para o agente

- Não ative `concurrent_updates(True)`: com um usuário e o turno terminando ao enviar a pergunta, o processamento sequencial é o que **garante** que texto e tap não corram entre si.
- Não responda a chat fora da allowlist nem com "acesso negado": silêncio não confirma que há alguém do outro lado.
- `chat_data` por chat é o lugar do estado; não crie dicionário global.
- Não capture `KeyboardInterrupt`: `run_polling` já encerra limpo em Ctrl+C.
