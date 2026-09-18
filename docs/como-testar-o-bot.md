# Como testar o bot no Telegram — passo a passo

> **Para quem:** você, no seu computador. ~30 minutos, dos quais 20 são esperar a expiração de uma confirmação no passo 12.
> **Por que existe:** os 908 testes automatizados **nunca falaram com um modelo de verdade** — todos usam um modelo falso. Este documento é a única verificação de que o `deepseek-flash` realmente escolhe as ações e de que o *thinking* fica desligado. Sem ele, o bot está "implementado e não verificado".
> **Onde anotar o resultado:** `docs/design/telegram-bot.md` §9.

> **Atualização de 18/09/2026 — a parte automatizável disto já roda sozinha.** `make test-ia` fala com o DeepSeek de verdade e mede roteamento, custo, latência e as invariantes de segurança, numa **cópia** do banco. A primeira rodada respondeu as duas perguntas em aberto: o *thinking* está desligado (42 tokens de saída, 1,4 s) e o roteamento acertou **5 de 5**. Este guia continua sendo o que você segue para **pôr o bot no ar** e para verificar o que só existe no Telegram — os botões, a edição da mensagem, a expiração de 5 minutos.

---

## Antes de começar — três coisas que valem saber

**1. O bot escreve no seu banco de verdade.** Ele lê `JULIUS_DB`, que por padrão é `~/.local/share/julius/prices.db` — hoje com 105 produtos, 132 preços e 5 mercados. Os passos 10 a 13 renomeiam um produto de verdade. É reversível (a resposta traz o comando de desfazer), mas dá para testar numa cópia e não pensar nisso:

```bash
cp ~/.local/share/julius/prices.db /tmp/julius-teste.db
export JULIUS_DB=/tmp/julius-teste.db
```

Com a cópia, os logs (`ai_calls.jsonl`, `query_log.jsonl`) e a tabela de orçamento também vão para `/tmp/` — trocar todos os caminhos deste guia de `~/.local/share/julius/` para `/tmp/` faz tudo funcionar igual. **Uma ressalva honesta:** o contador de orçamento fica na cópia, então o seu contador real não vê o gasto do teste — mas o DeepSeek cobra do mesmo jeito.

**2. Gasta dinheiro de verdade, pouco.** Cada mensagem é uma chamada ao DeepSeek. Uma passada inteira de curadoria custou US$ 0,01; um smoke de ~12 mensagens fica na mesma ordem de grandeza — **centavos**. Você gastou US$ 0,0213 dos US$ 5,00 deste mês. Como conferir o total, a qualquer momento:

```bash
python3 -c "import sqlite3,os;print(sqlite3.connect(os.path.expanduser('~/.local/share/julius/prices.db')).execute('SELECT month, round(spent_usd,4) FROM ai_usage').fetchall())"
```

**3. Sem IA não existe bot.** Diferente da CLI, aqui não há modo determinístico: toda mensagem passa pelo modelo. Faltando qualquer variável, o `julius-bot` recusa subir e diz qual.

---

## Passo 1 — Instalar

```bash
cd ~/precos-dos-mercados/project-julius
make install-bot
```

Isso instala o comando `julius-bot` (o `julius` da CLI continua funcionando). O bot vem como extra: quem só usa a CLI não carrega `telegram` nem `pydantic-ai`.

**Confira:**

```bash
which julius-bot     # deve imprimir um caminho, ex.: ~/.local/bin/julius-bot
```

---

## Passo 2 — Criar o bot no Telegram

No Telegram, abra uma conversa com **[@BotFather](https://t.me/BotFather)** e mande:

1. `/newbot`
2. Um nome de exibição — qualquer coisa, ex.: `Julius`
3. Um username terminando em `bot` — ex.: `julius_precos_bot` (tem de ser único no Telegram; se der erro, tente outro)

Ele responde com um token no formato `123456789:AAF...`. **Guarde**, é o passo seguinte.

---

## Passo 3 — Exportar as variáveis

Cole no terminal (ou no seu `~/.bashrc`, se quiser que sobrevivam a fechar o terminal):

```bash
# --- o bot ---
export JULIUS_BOT_TOKEN='123456789:AAF...'        # o token do @BotFather
export JULIUS_BOT_ALLOWED_CHAT_ID=0                # 0 = bootstrap; o passo 4 troca pelo seu número

# --- a IA (as mesmas de sempre; obrigatórias para o bot) ---
export JULIUS_AI_API_KEY='sua-chave-deepseek'
export JULIUS_AI_BASE_URL='https://api.deepseek.com/v1'
export JULIUS_AI_MODEL='deepseek-flash'
export JULIUS_AI_INPUT_PRICE_USD_PER_1M=0.30
export JULIUS_AI_OUTPUT_PRICE_USD_PER_1M=1.20
export JULIUS_AI_BUDGET_USD=5.0
export JULIUS_AI_REQUEST_EXTRAS='{"thinking":{"type":"disabled"}}'
```

> **`JULIUS_AI_REQUEST_EXTRAS` não é opcional.** Sem ela o `deepseek-flash` "pensa" até acabar o `max_tokens` e nunca responde. Da sua cadeira isso não parece erro de configuração: parece que o bot ficou mudo ou lentíssimo. É a falha nº 1 prevista, e o passo 9 é onde ela apareceria.

**Confira que a partida recusa o que falta** (ainda sem subir de verdade):

```bash
env -u JULIUS_BOT_TOKEN julius-bot ; echo "código: $?"
```

Esperado: `JULIUS_BOT_TOKEN não definido — crie o bot no @BotFather e exporte o token.` e `código: 2`.

---

## Passo 4 — Descobrir o seu `chat_id`

O bot não sobe aberto, e você ainda não sabe o seu número. O `0` resolve isso sem depender de nenhum outro bot: **nenhum chat do Telegram tem id 0**, então ele sobe configurado e fechado, atendendo ninguém.

```bash
julius-bot
```

Esperado no terminal: `Julius no ar, ouvindo o chat 0`.

Agora, **no Telegram**, abra a conversa com o seu bot e mande `/start`.

- Ele **não responde** — isso é o comportamento correto, não um defeito.
- No terminal aparece:

```
2026-09-18 10:12:03 INFO julius.bot mensagem ignorada de chat_id=987654321 (fora da allowlist)
```

Esse número é o seu. Pare o bot com **Ctrl+C**, exporte-o e suba de novo:

```bash
export JULIUS_BOT_ALLOWED_CHAT_ID=987654321   # o número que apareceu no SEU log
julius-bot
```

Esperado: `Julius no ar, ouvindo o chat 987654321`.

---

## Passo 5 — O primeiro "oi"

No Telegram, mande `/start`.

- **Esperado:** `Julius pronto. Pergunte um preço («quanto paguei de banana?»), compare mercados, ou peça uma correção do catálogo — escritas pedem confirmação.`
- **O que isso prova:** allowlist, transporte e formatação estão de pé. Ainda não passou pela IA — `/start` é resposta fixa.

---

## Passo 6 — Uma conversa fiada (a IA entra aqui)

Mande: **`bom dia`**

- **Esperado:** uma resposta curta em português, sem tabela nenhuma.
- **O que isso prova:** o modelo respondeu **texto** em vez de escolher uma ação — que é o comportamento certo para uma mensagem sem relação com o catálogo. É também a primeira chamada real ao DeepSeek.
- **Se demorar mais de ~10 s ou não vier nada:** vá direto ao passo 9, é a assinatura do *thinking* ligado.

---

## Passo 7 — A pergunta principal (leitura)

Mande: **`quanto paguei de picanha`**

- **Esperado:** em menos de 5 segundos, um bloco assim:

```
Preços por KG
  12/09/2026 · há 6 dias · R$ 89,90 · Picanha bovina · FL 3 Costa — AGUAS CLARAS
```

- **O que isso prova:** o modelo escolheu a ação `search_prices`, e o texto que chegou a você foi **montado do banco**, não escrito pelo modelo. Esta é a propriedade central do desenho.
- Se o seu catálogo não tiver picanha, troque por um produto que tenha (`julius produtos listar` mostra).

---

## Passo 8 — Comparar mercados

Mande: **`qual mercado tá mais barato`**

- **Esperado:** uma tabela por tipo de produto, a contagem "mais barato em N de M grupos", e o rodapé `base: …`.
- **Se vier "Nenhum produto tem tipo ainda"**: normal se o catálogo ainda não foi curado — rode `julius produtos revisar` na CLI antes.
- **O que isso prova:** o modelo distingue "preço de um produto" de "comparar mercados" — duas ações diferentes.

---

## Passo 9 — ⚠️ A verificação que mais importa: o *thinking* está desligado?

Depois das mensagens acima, leia a última linha do log de IA:

```bash
tail -n 1 ~/.local/share/julius/ai_calls.jsonl | jq '{output_tokens, latency_ms, cost_usd, error, raw_response}'
```

Sem `jq`:

```bash
tail -n 1 ~/.local/share/julius/ai_calls.jsonl | python3 -c "import json,sys;d=json.load(sys.stdin);print(f\"saida={d['output_tokens']} tok  latencia={d['latency_ms']} ms  custo=US\$ {d['cost_usd']:.6f}  erro={d['error']}  tipo={d['raw_response']}\")"
```

| O que você vê | Significa |
|---|---|
| `output_tokens` em **dezenas** (10–80), `latency_ms` em **poucos milhares**, `error: null` | ✅ **Funcionou.** O `extra_body` chegou, o *thinking* está desligado. |
| `output_tokens` em **milhares**, ou `error` preenchido | ❌ O *thinking* **não** foi desligado — o `extra_body` não chegou ao request. É a mesma assinatura de 15/09. Confira se `JULIUS_AI_REQUEST_EXTRAS` está exportada **no shell em que o bot subiu** (`echo $JULIUS_AI_REQUEST_EXTRAS`) e reinicie o bot. |
| `error` com `"HTTP 400"` ou nome de modelo | O nome em `JULIUS_AI_MODEL` pode não existir mais na API. Veja o passo 14. |

`raw_response` diz **qual tipo de saída** o modelo produziu: `text` (conversa), `SearchOutcome` (busca), `StoreComparison`, `PendingWrite:rename_product`… É como você confere se ele escolheu a ação certa.

---

## Passo 10 — Uma escrita: o preview

Escolha um produto para renomear. Pegue o id na CLI:

```bash
julius produtos listar | head -20
```

Mande no Telegram, trocando o número: **`renomeia o produto 23 para Tomate italiano`**

- **Esperado:** uma mensagem com dois botões:

```
⚠️ Confirmar?
Renomear o produto 23 «TOMATE ITALIANO UNIAO kg» para «Tomate italiano»

  [ ✅ Confirmar ]  [ ❌ Cancelar ]
```

- **O que isso prova:** o nome antigo veio **do banco**, não do que você escreveu nem do que o modelo imaginou. E **nada foi gravado ainda**.
- **Confira que nada mudou:** `julius produtos listar | grep 23` — ainda o nome velho.

---

## Passo 11 — O toque que grava

Toque em **✅ Confirmar**.

- **Esperado:** a mensagem anterior é editada e ganha `✅ Confirmado` no fim (os botões somem), e vem uma resposta nova:

```
✅ Produto 23 agora é «Tomate italiano» (antes: «TOMATE ITALIANO UNIAO kg»)
Desfazer: julius produtos renomear 23 "TOMATE ITALIANO UNIAO kg"
```

- **Confira na CLI:** `julius produtos listar | grep 23` — agora o nome novo.
- **Para voltar atrás:** cole o comando do `Desfazer:` no terminal.
- **O que isso prova:** só o seu toque grava, e o desfazer é calculado do estado real.

---

## Passo 12 — Os três jeitos de **não** gravar

Repita o passo 10 (mande o pedido de renomear de novo) e, em vez de confirmar:

| # | O que fazer | Esperado |
|---|---|---|
| a | Tocar em **❌ Cancelar** | `❌ Cancelado — nada foi executado.` e a mensagem ganha `❌ Cancelado`. Nada muda no banco. |
| b | Pedir de novo e **mandar outra mensagem** em vez de tocar (ex.: `quanto paguei de arroz`) | A resposta começa com `Ação anterior cancelada.` — um texto novo cancela a confirmação pendente. |
| c | Pedir de novo e **esperar 5 minutos**, então tocar em Confirmar | `Confirmação expirada — nada foi executado.` e a mensagem ganha `⏰ Expirado`. |

- **O que isso prova:** fail-closed em todos os caminhos. Só o caminho (a) do passo 11 grava.

---

## Passo 13 — A pergunta ambígua

Se você tiver dois produtos parecidos (dois tomates, duas águas), mande algo que não distinga: **`renomeia o tomate para Tomate`**

- **Esperado:** o bot **pergunta qual**, listando os ids — e **não** executa nada.
- **Se ele escolher um sozinho:** isso é um achado importante, anote. O sistema foi desenhado para perguntar; a ação devolve a ambiguidade ao modelo justamente para ele perguntar a você.

---

## Passo 14 — O nome do modelo

Se em qualquer passo o log trouxer `error` citando o modelo (`HTTP 400`, "model not found"), o nome mudou do lado do DeepSeek. Troque e reinicie:

```bash
export JULIUS_AI_MODEL='deepseek-chat'    # ou o nome que a API aceitar hoje
julius-bot
```

**Anote o nome que funcionou** — o `CLAUDE.md` afirma `deepseek-flash`, e se mudou, ele precisa mudar junto.

---

## Passo 15 — A conta no fim

```bash
python3 -c "import sqlite3,os;print(sqlite3.connect(os.path.expanduser('~/.local/share/julius/prices.db')).execute('SELECT month, round(spent_usd,4) FROM ai_usage').fetchall())"
```

Compare com os US$ 0,0213 de antes do teste. **Esperado:** a diferença é de centavos. Se subiu na casa de dólares, algo está muito errado — quase certamente o *thinking* ligado (passo 9).

Veja também quantas chamadas foram feitas e quanto cada uma custou:

```bash
jq -s 'map(select(.call_kind=="bot_turn")) | {chamadas: length, custo_total: (map(.cost_usd) | add), tokens_saida: map(.output_tokens)}' ~/.local/share/julius/ai_calls.jsonl
```

---

## Onde anotar o resultado

Abra `docs/design/telegram-bot.md`, seção **§9.1**, e escreva o que aconteceu — principalmente:

1. O `deepseek-flash` escolheu a ação certa em quantas das mensagens? (passos 6, 7, 8, 10, 13)
2. `output_tokens` típico e `latency_ms` típico (passo 9).
3. O nome do modelo que funcionou (passo 14).
4. Custo de ~12 mensagens (passo 15).

Se o prompt precisar de ajuste, ele está em `julius/bot/agent.py` (`SYSTEM_PROMPT`), versionado em `BOT_PROMPT_VERSION` — **suba a versão ao mexer no texto**, é a disciplina que o projeto já aplica aos prompts da curadoria.

---

## Se algo der errado

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `julius-bot` sai imediatamente com código 2 | Falta uma variável | A mensagem diz qual. Passo 3. |
| O bot sobe mas não responde nada a você | Seu `chat_id` não está na allowlist | Olhe o log: `mensagem ignorada de chat_id=…`. Passo 4. |
| Responde `/start` mas silencia nas perguntas | `thinking` ligado, ou chave/modelo errados | Passo 9 — o log diz. |
| `Orçamento de IA do mês esgotado` | Teto batido | Aumente `JULIUS_AI_BUDGET_USD` ou espere o mês virar. A CLI continua funcionando. |
| `Não consegui falar com a IA agora` | Rede ou API fora | O log traz `agent raised …`. Tente de novo. |
| `Essa confirmação não está mais ativa` ao tocar um botão | Você tocou num botão de uma mensagem antiga | Normal — só a confirmação mais recente vale. Peça de novo. |
| Mensagens mandadas com o PC desligado não são respondidas | É o comportamento escolhido (`drop_pending_updates`) | Nada a fazer; mande de novo. |

**O token nunca aparece no log** — `httpx` é capado em `WARNING` antes do polling começar, porque em `INFO` ele imprimiria a URL do `getUpdates` com o token dentro. Se você aumentar o nível de log para depurar, lembre-se disso antes de colar o log em algum lugar.

---

## Limitações que não são defeito

- **Uma ação por mensagem.** "Renomeia X e marca como Y" faz a primeira e avisa que a segunda vem na próxima.
- **PC desligado = silêncio.** É long polling num computador doméstico, não um servidor.
- **Só texto.** Sem foto de cupom, sem QR code, sem áudio.
- **Memória de 3 turnos.** Ele não lembra da conversa de ontem.
- **A confirmação expira em 5 minutos.**
