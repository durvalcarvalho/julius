# 151: `Config` — o token do bot e a allowlist de um único chat

<!-- status:done implemented:2026-09-17 commit:120f4aa -->
<!-- adjustments: none -->

> Duas variáveis de ambiente novas, lidas no único lugar que lê ambiente.

## Contexto

`docs/design/telegram-bot.md` §2.1 e §2.2; requisitos RF2, RF4, RF9 e F8/F11 de `docs/requirements/messaging-bot-integration.md`. O bot só sobe com token **e** allowlist; a allowlist é um único `chat_id` inteiro, comparado com o que o transporte (Telegram) informa — nunca com nada que a IA leia.

Não depende de nenhum ticket. 161 (partida do bot) consome os dois campos.

## Escopo

### Dentro
- `julius/config.py`: campos `bot_token: str | None = None` e `bot_allowed_chat_id: int | None = None` em `Config`; propriedade `bot_configured`; `load` lê `JULIUS_BOT_TOKEN` e `JULIUS_BOT_ALLOWED_CHAT_ID`; helper `_optional_int` ao lado de `_optional_float`.
- `tests/conftest.py`: o autouse `_clean_ai_env` passa a limpar também as duas variáveis do bot (renomeie a tupla para `ISOLATED_ENV_VARS` e a fixture para `_clean_env` se quiser; o comportamento é o que importa).
- `tests/test_config.py`.

### Fora
- Ler essas variáveis em qualquer outro lugar (→ 161).
- Validar o **formato** do token — é do Telegram, não nosso; um token errado falha na primeira chamada, com a mensagem deles.
- Qualquer arquivo em `julius/bot/`.

## Requisitos

### Funcionais
- `Config.bot_token` — `env.get("JULIUS_BOT_TOKEN") or None` (vazio vira `None`, como `ai_api_key`).
- `Config.bot_allowed_chat_id` — `_optional_int(env, "JULIUS_BOT_ALLOWED_CHAT_ID")`; vazio/ausente → `None`.
- `Config.bot_configured` → `bool(self.bot_token) and self.bot_allowed_chat_id is not None`.
- Os dois campos entram **depois** de `ai_request_extras` (o dataclass é `frozen` e campos com default têm de vir depois dos sem default).
- Inteiro negativo é aceito: grupos do Telegram têm `chat_id` negativo, e o requisito é "um chat", não "um usuário".
- `0` é aceito e conta como configurado: é o modo de **bootstrap** do 161 (nenhum chat real tem id 0, então ninguém é autorizado e o bot só registra quem escreveu).

### Validação e erros
- `JULIUS_BOT_ALLOWED_CHAT_ID="abc"` → `ValueError("JULIUS_BOT_ALLOWED_CHAT_ID must be an integer, got 'abc'")` — mesma forma da mensagem de `_optional_float`.
- `"12.5"` também é erro (inteiro, não float).

## Especificação técnica

```
modificar julius/config.py      — dois campos, bot_configured, _optional_int, duas linhas em load
modificar tests/conftest.py     — isolar JULIUS_BOT_TOKEN e JULIUS_BOT_ALLOWED_CHAT_ID no autouse
modificar tests/test_config.py
```

### Padrão a seguir
- `_optional_float` e a mensagem `f"{name} must be a number, got {raw!r}"` — copie a forma, troque `float` por `int` e "a number" por "an integer".
- `ai_configured` é o precedente da propriedade booleana derivada.

## Testes obrigatórios

1. `test_bot_settings_default_to_none_and_not_configured` — sem as variáveis: `bot_token is None`, `bot_allowed_chat_id is None`, `bot_configured is False`.
2. `test_bot_settings_are_read_from_env` — as duas definidas → `bot_configured is True`, `bot_allowed_chat_id == 123456789` (int, não str).
3. `test_bot_token_alone_is_not_configured` — só o token → `False`.
4. `test_bot_allowed_chat_id_must_be_an_integer` — `"abc"` e `"12.5"` → `ValueError` com o nome da variável na mensagem.
5. `test_negative_and_zero_chat_ids_are_accepted` — `"-1001234567890"` → `-1001234567890`; `"0"` → `0` e `bot_configured is True` (com token).
6. `test_conftest_isolates_bot_env` — dentro da suíte, `config.load()` não vê um `JULIUS_BOT_TOKEN` exportado no shell (`monkeypatch.setenv` num teste e `config.load(env={})` para provar que `load` aceita `env` explícito continua valendo).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "JULIUS_BOT_" julius/` mostra **só** `julius/config.py`.
- [ ] `tests/test_architecture.py` verde sem edição (`config` continua sem importar nada de `julius`).

## Notas para o agente

- Identificadores em inglês (`bot_allowed_chat_id`), variáveis de ambiente em inglês com prefixo `JULIUS_` — regra dura do `CLAUDE.md`.
- Não adicione `bot_configured` à mensagem de nenhuma dica (`guidance`); o bot não passa pelas dicas.
