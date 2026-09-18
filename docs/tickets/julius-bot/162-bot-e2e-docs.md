# 162: e2e do bot, documentação e a lista do smoke test real

> O fluxo inteiro num teste só, o `README`/`CLAUDE.md` contando o que existe, e a lista do que **só** a rodada real contra o DeepSeek pode confirmar.

## Contexto

`docs/design/telegram-bot.md` §7 (teste de fiação), §9 (a verificar na implementação) e §10. Fecha a trilha 150–161. O smoke test real continua sendo do usuário, com a chave no shell dele — o ticket entrega a lista do que observar e onde anotar.

Depende de **161** (tudo).

## Escopo

### Dentro
- `tests/test_e2e.py`: cenário do bot (texto → leitura; texto → pendência; tap → gravação; leitura mostra o novo estado; contadores).
- `README.md`: seção **"Bot no Telegram"** (depois de "IA opcional (orçamento mensal)"), e o `julius-bot` na tabela/lista de comandos onde a CLI é apresentada.
- `CLAUDE.md`: parágrafo de status **v2.6 (bot no Telegram)**; entradas na lista "Adições"; linha `bot` na tabela da DAG; variáveis `JULIUS_BOT_*` em "Configuração"; a decisão *output functions* × *Deferred Tools* e os demais "de propósito não" em "Fora do escopo".
- `docs/design/telegram-bot.md`: linha de cabeçalho "Implementado em <data> (tickets 150–162)"; §9 ganha o espaço para o resultado do smoke.
- `docs/tickets/julius-bot/index.md`: estados `feito`.

### Fora
- Rodar o smoke test real (é do usuário; o ticket só o descreve).
- Qualquer código novo em `julius/` além de correção de bug que o e2e revelar (se revelar, anote no `index.md` antes de corrigir).

## Requisitos

### Funcionais

**e2e** (`FunctionModel` com roteiro por chamada, `asyncio.run` para `handle_text`, banco em `tmp_path` com os três fixtures importados):
1. `"quanto paguei de picanha?"` → roteiro chama `search_prices(words="picanha")` → resposta contém `Preços por KG` e o preço da fixture; `query_log.jsonl` tem 1 linha `channel == "bot"`.
2. `"renomeia a picanha para Picanha bovina"` → roteiro chama `rename_product(product="<id>", name="Picanha bovina")` → `reply.pending`; `canonical_name` inalterado.
3. `handle_tap(state, deps, reply.pending.nonce, True)` → texto com `✅` e `<code>julius produtos renomear`; `canonical_name == "Picanha bovina"`.
4. `"quanto paguei de picanha bovina?"` → resposta mostra o nome novo.
5. Contadores: `ai_usage.spent_in_month > 0`; `ai_calls.jsonl` com 3 linhas `bot_turn` (o tap não chama modelo); modelo chamado exatamente 3 vezes.
6. Um caminho triste: `"apaga tudo"` → roteiro devolve prosa (não há ação de apagar) → resposta é texto, banco intacto.

**README — "Bot no Telegram"** deve conter, nesta ordem: o que é (as mesmas perguntas da CLI, por mensagem; escritas pedem confirmação); instalação (`make install-bot`); criar o bot no `@BotFather` (`/newbot`, token); as duas variáveis novas com exemplo; **bootstrap** em três passos, como o 161 define: subir com `JULIUS_BOT_ALLOWED_CHAT_ID=0` (ninguém autorizado), mandar `/start`, ler `mensagem ignorada de chat_id=…` no log, exportar o número e reiniciar. Limitações declaradas: uma ação por mensagem; PC desligado = silêncio; mensagens enviadas enquanto desligado não são respondidas na volta; sem fotos/QR ainda. Segurança em uma frase: só o `chat_id` da variável é atendido; a IA nunca executa nada, só propõe; toda escrita pede um toque.

**CLAUDE.md** — no estilo dos parágrafos de versão existentes: o que nasceu (bot, `domain/formatting`, `record_usage`, `Config.bot_*`, `julius-bot`), as decisões medidas/lidas (output functions e o porquê; `drop_pending_updates`; TTL 300 s; `HISTORY_TURNS = 3`), a regra de teste nova (`ALLOW_MODEL_REQUESTS = False` autouse; `FunctionModel` roteia; nunca `time.sleep` para expiração), e o que o smoke real ainda precisa confirmar.

### Validação e erros
- Nenhuma afirmação no `README`/`CLAUDE.md` sobre o comportamento do `deepseek-flash` com `tools` até o smoke rodar — escreva "a confirmar no smoke" onde couber.

## Especificação técnica

```
modificar tests/test_e2e.py
modificar README.md
modificar CLAUDE.md
modificar docs/design/telegram-bot.md
modificar docs/tickets/julius-bot/index.md
```

### Padrão a seguir
- `tests/test_e2e.py` já encadeia importar → curar → consultar com `ScriptedLlmClient`; o cenário do bot vai ao lado, com `FunctionModel` no lugar do client.
- Ticket 146 (`e2e-docs-v24`) é o precedente de "fechar a fase": teste de fiação + docs, sem feature nova.

## Testes obrigatórios

1. `test_bot_end_to_end_read_write_confirm_read` — os passos 1–5 acima num teste só, com asserções em cada passo.
2. `test_bot_unrelated_message_is_plain_text_and_touches_nothing` — passo 6.
3. Suíte inteira verde.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "Bot no Telegram" README.md` e `grep -n "v2.6" CLAUDE.md` existem.
- [ ] `grep -rn NotImplementedError julius` **vazio**.
- [ ] `index.md` com 150–162 em `feito` e o campo "Estado do código" atualizado.

## Lista do smoke test real (dono: o usuário; anotar o resultado em `docs/design/telegram-bot.md` §9)

Ambiente: máquina de deploy (ou a de dev, com um banco de teste), shell com `JULIUS_AI_*` (incluindo `JULIUS_AI_REQUEST_EXTRAS='{"thinking":{"type":"disabled"}}'`) e `JULIUS_BOT_*` exportados.

1. `make install-bot` → `julius-bot` sobe; sem uma das variáveis, termina com código 2 e a mensagem certa.
2. Subir com `JULIUS_BOT_ALLOWED_CHAT_ID=0`, mandar `/start` → nada respondido; log mostra `mensagem ignorada de chat_id=…`. Exportar o número, reiniciar.
3. `"quanto paguei de banana"` → resposta em **< 5 s** com o bloco `Preços por …`. Confira em `~/.local/share/julius/ai_calls.jsonl`: linha `bot_turn` com `output_tokens` **pequeno** (dezenas) e `latency_ms` na casa dos segundos. `output_tokens` na casa dos milhares ou `error` = `thinking` **não** foi desligado no request — o `extra_body` não chegou; é o item 1 de §9 do design.
4. `"renomeia o produto 23 para Tomate"` → mensagem `⚠️ Confirmar?` com os nomes **do banco**; tocar Confirmar → `✅` com o `Desfazer:`; `julius produtos listar` na CLI mostra o novo nome.
5. Repetir 4 e tocar Cancelar → `❌`, nada mudou. Repetir e esperar 5 min → `⏰`.
6. Uma frase ambígua (`"renomeia o tomate"` com dois tomates) → o bot **pergunta** qual, listando ids — não executa.
7. Frase sem relação (`"bom dia"`) → texto curto, sem ação.
8. `SELECT * FROM ai_usage` — o mês subiu em centavos, não em dólares; anote o custo de ~10 mensagens.
9. Nome do modelo: se a API recusar `deepseek-flash`, trocar `JULIUS_AI_MODEL` para o nome que o `chat/completions` aceita hoje e registrar no `CLAUDE.md`.

## Notas para o agente

- Não "melhore" o prompt do bot com base no e2e — o `FunctionModel` não exercita prompt nenhum. O prompt é medido no smoke, pelo usuário.
- Se o e2e mostrar um bug de fiação (ex.: `SearchOutcome` não renderiza vazio), corrija no módulo dono e **anote no `index.md`** qual ticket tinha o buraco.
