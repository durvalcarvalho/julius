# Julius v2.6 — bot no Telegram: tickets de implementação

> Gerado a partir de: `docs/design/telegram-bot.md` (design), `docs/requirements/messaging-bot-integration.md` (requisitos), `claudedocs/research_messaging_bot_integration_20260917.md` e `claudedocs/research_bot_stack_libraries_20260917.md` (pesquisas), `../majordomo` (referência externa, estudada com desconfiança).
> Gerado em: 2026-09-17 · Estado do código **na geração**: commit `0b2b12d`, docs desta frente ainda não versionados, suíte verde (754 testes).
> **Trilha concluída em 2026-09-17**: 150–162 feitos, um commit por ticket, **906 testes verdes**, nenhum `NotImplementedError`. O §4.3 **não** foi vetado — as ações são *output functions*, e a implementação confirmou a premissa. O que a implementação descobriu contra o que os tickets diziam está em cada bloco `<!-- adjustments: … -->` e, consolidado, em `docs/design/telegram-bot.md` §9.1 e §9.2. Falta só o **smoke real**, que é do usuário (lista no ticket 162).
> **Premissa deste índice**: o §4.3 do design (*output functions* em vez de *Deferred Tools*) foi marcado para veto do usuário e **ainda não foi vetado**. Os tickets seguem o design como está. Se o veto vier, mudam 156–160 (a pendência passaria a ser `DeferredToolRequests`, o tap a `agent.run(deferred_tool_results=…)`, e a resposta a ser lida do `ToolReturnPart`); 150–155, 158 e 161 ficam.

## Visão geral

O Julius ganha uma **segunda interface** sobre a mesma camada `services/*`: um bot no Telegram, para um usuário só, rodando num PC doméstico que liga e desliga. Cada mensagem passa pela IA (DeepSeek, as mesmas três variáveis de sempre) que **escolhe uma ação** de um menu fechado de catorze funções Python — quatro de leitura, dez de escrita reversível — e o **código** executa e responde. A IA nunca vê `conn`, `chat_id` nem shell; nunca narra um efeito; quando uma escrita é escolhida, ela vira uma pendência com preview lido do banco, e só um toque no botão executa.

Abordagem: `python-telegram-bot` assíncrono com long polling (sem webhook, sem porta); PydanticAI com *output functions* (`output_type=[str, *ações]` — a chamada encerra o run, o resultado não volta ao modelo, uma chamada de modelo por mensagem); um dicionário por chat para histórico curto e pendência; orçamento e log **os que já existem** (`ai_usage`, `ai_calls.jsonl`, `query_log.jsonl`) por uma função pública extraída de `suggestions._ask`. O `infra/llm_client.py` da curadoria não muda.

Trilha única (o projeto não tem frontend). A numeração continua a global do projeto (a v2.5.1 parou em 149) e a ordem já respeita as dependências.

## Decisões aplicadas (vêm do design; não rediscutir dentro de ticket)

- **Telegram, long polling, `python-telegram-bot>=21`**; nenhum servidor HTTP em lugar nenhum. Processamento **sequencial** de updates (default): o turno termina ao enviar a pergunta e o tap é um update novo — sem lock, sem `concurrent_updates`.
- **`julius/bot/` é L4, irmão de `cli/`**: importa `domain`, `config`, `infra`, `services`; nada importa `bot`; `cli` e `bot` não se conhecem. Executável próprio `julius-bot`; dependências como extra `bot` (o extra `dev` as inclui para a suíte).
- **Formatadores puros vão para `domain/formatting.py`** (`money`, `br_date`, `relative_age`, `content_text`, `store_labels`, `coverage_text`, `plural_groups`); `cli` passa a importá-los de lá. Único toque em código existente além de `config.py`, `suggestions.py`, `search.py` (uma renomeação) e `pyproject.toml`.
- **Modelo roteia, código executa e responde**: ações são *output functions*; a resposta é renderizada do retorno real; prosa do modelo só chega ao usuário quando nenhuma ação foi escolhida. Custo aceito: **uma ação por mensagem**; por isso as escritas aceitam produto/mercado por **nome ou id** e resolvem em código (`ModelRetry` com candidatos quando ambíguo).
- **Escrita = duas passadas**: a ação devolve `PendingWrite` (ids resolvidos, preview com nomes do banco, nonce, `created_at`); o tap chama `execute` em código; `undo` é calculado do estado **imediatamente antes** de gravar. TTL de **300 s** (medição do `majordomo`: 120 s derrubou um tap real). Fail-closed em todo ramo; pendência limpa em `finally`; texto novo cancela a viva e ignora a expirada em silêncio.
- **Allowlist é o primeiro `if`** de cada handler, sobre `update.effective_chat.id`; fora dela: silêncio + uma linha de log com o `chat_id` (é o bootstrap). `JULIUS_BOT_ALLOWED_CHAT_ID=0` = modo bootstrap (ninguém autorizado). Sem a variável, o bot **não sobe**.
- **IA obrigatória para o bot**: sem `JULIUS_AI_*` completo (com preços) o bot recusa subir — não existe modo determinístico.
- **Orçamento partilhado**: `suggestions.record_usage` (novo, público) cobra e loga; `call_kind="bot_turn"`, `prompt_version` do bot passado explicitamente (**não** entra em `PROMPT_VERSIONS`). Orçamento estourado → resposta determinística sem tocar o modelo. `actions.jsonl` **não** recebe escritas do bot (são pedido + confirmação do usuário, como a CLI).
- **Modelo pelas mesmas variáveis**: `OpenAIChatModel(JULIUS_AI_MODEL, provider=OpenAIProvider(base_url=JULIUS_AI_BASE_URL, api_key=JULIUS_AI_API_KEY))`; `JULIUS_AI_REQUEST_EXTRAS` vai em `ModelSettings.extra_body` (confirmado na doc). Sem `DeepSeekProvider`, sem fallback de provedor.
- **`drop_pending_updates=True`** na partida: o que chegou com o PC desligado não é respondido na volta (RNF3). Questão aberta abaixo.
- **Testes**: `FunctionModel` roteia (`run_sync`/`asyncio.run`, sem `pytest-asyncio`); `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` autouse; expiração por `now` injetado, nunca `time.sleep`; o turno é testado sem PTB; o smoke real é do usuário.
- Identificadores, nomes de ação e variáveis de ambiente em inglês; docstrings das ações, `ModelRetry`, prompt e toda mensagem ao usuário em português. Sem emoji além dos que o design fixou nas mensagens de confirmação (⚠️ ✅ ❌ ⏰) e dos marcadores ▼/▲.

## Regras comuns a todo ticket

1. Leia `CLAUDE.md`, `docs/design/telegram-bot.md` e as seções citadas no ticket antes de começar. O design tem precedência sobre este índice; o requisito, sobre o design.
2. Só toque nos arquivos listados no ticket. Se precisar de algo de outra camada que não existe, **pare e anote** — não crie fora do escopo.
3. `tests/test_architecture.py` é a fonte da verdade da DAG (com a linha `bot` do 153). Se ele falhar, o desenho está errado, não o teste.
4. Caminho feliz **e** triste para cada função pública. SQLite real em `tmp_path`; modelo **sempre** `FunctionModel`/`TestModel`; nenhum teste toca a API — o `conftest` bloqueia.
5. `julius/bot/*` nunca fala SQL, nunca importa `repositories`, nunca lê `os.environ`, nunca importa `cli`.
6. Nenhuma ação executa efeito; só `execute` escreve, e só depois do tap. Nenhuma exceção atravessa um turno.
7. Sem comentários narrando código; docstring só quando o *porquê* não é óbvio — exceto as docstrings das ações, que são o **schema** que o modelo lê e precisam ser completas.
8. Aceite = `.venv/bin/pytest -q` totalmente verde + `grep -rn NotImplementedError julius` vazio + critérios do ticket.
9. Ao terminar, marque o ticket como `feito` na tabela abaixo e faça um commit só dele (mensagem em inglês, com "(ticket NNN)" como os anteriores).

## Trilha

| # | Ticket | Depende de | Esforço | Estado | Entrega |
|---|---|---|---|---|---|
| 150 | [`domain/formatting.py`](150-domain-formatting.md) | — | S | **feito** (`77b344c`) | `money`/`br_date`/`relative_age`/`content_text`/`store_labels`/`coverage_text`/`plural_groups` em `domain`; `cli` reexporta |
| 151 | [`Config` do bot](151-config-bot-settings.md) | — | S | **feito** (`120f4aa`) | `bot_token`, `bot_allowed_chat_id`, `bot_configured`; `JULIUS_BOT_*`; isolamento no `conftest` |
| 152 | [`suggestions.record_usage`](152-suggestions-record-usage.md) | — | S | **feito** (`cae53d8`) | cobrança + log públicos; `_ask` usa; `prompt_version` explícito |
| 153 | [Dependências, DAG, guardas](153-bot-packaging-dag-guards.md) | — | S | **feito** (`4a759ac`) | extras `bot`/`dev`; linha `bot` em `ALLOWED_IMPORTS`; `import julius.cli` sem deps do bot; `ALLOW_MODEL_REQUESTS=False` |
| 154 | [`bot/render.py`](154-bot-render.md) | 150, 153 | M | **feito** (`128b277`) | `escape`, `render_records`/`comparison`/`products`/`stores`, `fit` (4096) |
| 155 | [`bot/actions.py` — leitura](155-bot-actions-read.md) | 153 | M | **feito** (`241cb42`) | `Deps`, `ProductListing`/`StoreListing`, `resolve_product`/`resolve_store`, 4 ações; `search.matching_product_ids` |
| 156 | [`bot/actions.py` — nome e tag](156-bot-actions-write-names-tags.md) | 154, 155 | M | **feito** (`6d3a3ae`) | `PendingWrite`/`WriteResult`/`WriteFailed`, `execute`, 4 escritas; `render_pending`/`result`/`failure` |
| 157 | [`bot/actions.py` — tipo, conteúdo, fusão](157-bot-actions-write-kind-content-merge.md) | 156 | M | **feito** (`4850540`) | 6 escritas, `execute` completo, `ALL_ACTIONS` (14) |
| 158 | [`bot/agent.py`](158-bot-agent.md) | 155–157 | M | **feito** (`61af069`) | `build_model`, `build_agent` (output functions, `extra_body`), `SYSTEM_PROMPT` v1 |
| 159 | [`bot/turn.py` — texto](159-bot-turn-text.md) | 152, 154, 158 | M | **feito** (`2a03260`) | `ChatState`, `Reply`, `handle_text`: orçamento → agente → render/pendência → cobrança/logs |
| 160 | [`bot/turn.py` — tap](160-bot-turn-tap.md) | 159 | S | **feito** (`5b2567d`) | `handle_tap`, TTL 300 s, `_expired`, fail-closed com `finally` |
| 161 | [`bot/app.py` + `julius-bot`](161-bot-app-entrypoint.md) | 151, 153, 160 | M | **feito** (`6f31eaa`) | partida fail-fast, logger capado, 3 handlers, allowlist, botões, `run_polling`; script e `make install-bot` |
| 162 | [e2e, docs, smoke](162-bot-e2e-docs.md) | 161 | M | **feito** | `test_e2e.py` do bot; `README`/`CLAUDE.md`; lista do smoke real (dono: usuário) |

## Dependências e caminho crítico

```
150 ─┐
151 ─┼──────────────────────────────────┐
152 ─┼──────────────┐                   │
153 ─┴─┬─ 154 ──┐   │                   │
       └─ 155 ──┼── 156 ── 157 ── 158 ──┼── 159 ── 160 ── 161 ── 162
                └───────────────────────┘
```

150–153 são independentes entre si e podem ser feitos em qualquer ordem (ou em paralelo). O caminho crítico é **153 → 155 → 156 → 157 → 158 → 159 → 160 → 161 → 162** (nove tickets); 150/154 entram antes de 156, 151/152 antes de 159/161.

## Fases

- **Fundação (150–153)**: nada do bot existe ainda; o projeto passa a saber que ele vai existir. Todos S. Depois deles a suíte continua exatamente o que era, mais as guardas.
- **Ações e render (154–157)**: o menu fechado nasce e é testado pelo agente com modelo falso, sem Telegram. Depois de 157, `ALL_ACTIONS` tem 14 funções e nenhuma grava sem `execute`.
- **Agente e turno (158–160)**: a IA entra (só em teste, sempre falsa) e o fluxo texto → resposta/pendência → tap fecha. Tudo ainda sem PTB.
- **Transporte e fechamento (161–162)**: o único módulo que conhece o Telegram, o executável, o e2e e a documentação. O smoke real vem depois, pelo usuário.

## Riscos e onde os tickets os tratam

| Risco (do design §9) | Ticket | Mitigação |
|---|---|---|
| `deepseek-flash` não converge com `tools` / `thinking` não é desligado via `extra_body` | 158 (config), 162 (smoke item 3) | `extra_body` confirmado na doc; o smoke lê `output_tokens`/`latency_ms` em `ai_calls.jsonl` para detectar — mesma assinatura da pegadinha de 15/09 |
| *Output functions* não convivendo com `str`/`ModelRetry` como esperado | 155 (teste 8), 158 (testes 2–4) | testado com `FunctionModel`; plano B (*Deferred Tools*) descrito no design §4.3, contido em 156–160 |
| Nome de campo de `result.usage()` | 159 | `input_tokens`/`output_tokens` confirmados na doc de `RunUsage` |
| Nome exato do modelo na API | 162 (smoke item 9) | vem de `JULIUS_AI_MODEL`; nenhum ticket o fixa |
| Prosa do modelo vazando como resposta | 159 (teste 2) | despacho por tipo: só `str` vira resposta, e só quando nenhuma ação foi chamada |
| Token no log | 161 (teste 7) | `httpx`/`httpcore` em `WARNING` antes do polling |
| Pendência "travada" | 160 (teste 7) | `finally` limpa em todo ramo, inclusive exceção inesperada |
| História cortada no meio de um turno (API recusa) | 159 (teste 8) | histórico por turnos inteiros (`runs`), nunca por mensagens |

## Questões abertas (assumidas assim ao gerar; mudar é um `UPDATE` no ticket, não redesign)

1. **`drop_pending_updates=True`** (161): mensagens recebidas com o PC desligado são descartadas na volta. Alternativa: `False` e responder a fila — leituras são inofensivas, escritas pedem tap de qualquer jeito. Se o usuário preferir a fila, é uma flag.
2. **Dicas (`guidance`) fora do bot** (155): "Nenhum resultado." sem o "parecidos: …" que a CLI dá. Os textos vivem em `cli/_hints.py`; trazê-los exigiria movê-los para `domain` como no 150. Fica para uma rodada posterior se fizer falta.
3. **`HISTORY_TURNS = 3`** (159): número escolhido pelo custo de tokens, sem medição de uso. Ajustar quando `ai_calls.jsonl` mostrar o custo real por turno.
4. **Bootstrap por `0`** (151/161): resolve a circularidade "não sobe sem allowlist" × "descobre o id pelo log" sem terceiro. Se o usuário preferir `@userinfobot`, nada muda no código — só no README.
5. **`words` no `query_log.jsonl` do bot** (159): é `term_used.split()`, não o que o usuário digitou (a IA extraiu). Registrado para quem for recalibrar cortes com esse log: filtre por `channel`.

---

## Trilha v2.7 — a voz do Julius

> Gerado a partir de: o design "voz do Julius no bot (v2.7)" combinado em chat na sessão de 2026-09-18 (brainstorm → design, sem documento de design próprio ainda — o ticket 169 decide se um nasce em `docs/design/`), reagindo ao caso real do screenshot de 2026-09-18 16:09 (busca de preço respondida como tabela de log, sem personagem).
> Gerado em: 2026-09-18 · Estado do código **na geração**: commit `5e6d412` (162 fechado), working tree com um protótipo descartado (ver nota abaixo) e `persona-julius-rock.md` não rastreado na raiz.
> **Antes de começar o 163**: descarte o protótipo em `julius/bot/{actions,app,render,turn}.py`, `julius/services/suggestions.py` e os três `tests/test_bot_*`/`test_services_suggestions.py` (`git checkout -- <arquivos>` ou `git stash`) — ele não segue o corte Modo A/B nem o ponto único `narrate` que esta trilha define, e implementar por cima dele reabriria a mesma discussão de design.
> **Trilha implementada em 2026-09-18**: 163–169 feitos, um commit por ticket, **949 testes verdes**. Achado real durante a implementação (não no smoke): `asyncio.to_thread(suggestions.narrate, deps.conn, ...)` quebra porque `sqlite3.Connection` não atravessa thread — corrigido no 167, chamando `narrate()` direto; ver `<!-- adjustments -->` no topo do ticket 167. **Smoke da camada de IA rodado no mesmo dia**, contra cópia do banco de produção: `NARRATE_FULL_MAX_GROUPS` subiu de 3 para **6** (medido — é o número exato de grupos comparáveis do catálogo real, narrados inteiros sem a guarda rejeitar nada); `NARRATE_FULL_MAX_RECORDS = 6` confirmado (cobre 69 de 72 buscas reais); tom lido como funcional, mais comedido que o character bible completo. **Falta só o roteiro dentro do Telegram de verdade** (botões, edição de mensagem — passos 1–15/19 de `docs/como-testar-o-bot.md`), que é do usuário; a chamada a `narrate()` já foi validada fora do `python-telegram-bot`.

### Visão geral

Toda resposta de leitura do bot (busca, comparação, listagens de produto/mercado) passa a poder soar como o Julius Rock, narrada por uma segunda chamada de IA (`services/suggestions.py::narrate`, ticket 163) sobre fatos já calculados pelo banco — nunca por cima de dado que a IA inventou. Resultados pequenos (busca ≤6 registros, comparação ≤3 grupos — Modo A) trocam a tabela inteira por uma frase; resultados maiores e as listagens (Modo B) ganham só um comentário por cima da tabela de sempre. As três confirmações de escrita (`PendingWrite`/`WriteResult`/`WriteFailed`) ganham o mesmo comentário, mas o preview, o resumo e o `<code>` de desfazer nunca são tocados pela IA — só cercados por ela. Quando a IA falha, some ou é rejeitada pela guarda (nenhum valor em `R$ X,XX` fora dos fatos recebidos), a leitura pequena cai numa frase-molde escrita à mão, no mesmo tom, nunca de volta à tabela crua; a leitura grande e a escrita simplesmente ficam sem comentário, exatamente como hoje.

Trilha única, seguindo a numeração global (162 foi o último). Nenhum arquivo de `domain/`, `services/catalog|search|comparison`, `repositories/` ou `cli/` muda — só `bot/` e a nova função em `services/suggestions.py`, que já é a camada de IA compartilhada.

### Decisões aplicadas (vêm do brainstorm/design; não rediscutir dentro de ticket)

- **Mecanismo é IA real por resposta**, não moldes estáticos — aceitando o custo de mais uma chamada por leitura e uma leve por escrita.
- **Escrita entra na voz do Julius**, mas só como comentário ao redor do texto de hoje — nunca reescrevendo preview/resumo/undo.
- **Ponto único de narração** (`narrate(conn, config, client, context, facts)`), reaproveitado por toda leitura e escrita — um prompt, uma guarda, um `call_kind` de log (`"persona"`).
- **Guarda por dinheiro, não por identidade**: qualquer `R$ X,XX` na resposta que não esteja nos fatos derruba a resposta inteira. Guarda de nome/id de produto/mercado foi considerada e adiada por falta de caso medido — mesma disciplina do resto do projeto.
- **Prompt `persona` v2** (18/09/2026, feedback real do usuário testando pelo Telegram): resposta em duas partes — informação clara (preço, unidade, mercado, data) primeiro, comentário do Julius depois, podendo citar a diferença entre o mais barato e o mais caro porque `records_facts`/`comparison_facts` agora entregam esse número já calculado. A IA continua nunca somando nem subtraindo por conta própria.
- **Fallback com tom, mas só no Modo A** (busca/comparação pequenas): frase-molde determinística, sem IA. Modo B (listagens, escrita) degrada para "sem comentário", igual a hoje.
- **Corte de tamanho**: `NARRATE_FULL_MAX_RECORDS = 6`, `NARRATE_FULL_MAX_GROUPS = 6` — o segundo era chute (3) e foi corrigido pelo smoke da camada de IA em 18/09/2026 contra o catálogo real; o primeiro já nasceu medido.

### Trilha

| # | Ticket | Depende de | Esforço | Estado | Entrega |
|---|---|---|---|---|---|
| 163 | [`suggestions.narrate`](163-suggestions-narrate.md) | — | S | **feito** (`16ac10b`) | `PROMPT_VERSIONS["persona"]`, `SYSTEM_PROMPTS["persona"]`, `narrate()`, guarda de dinheiro |
| 164 | [`render.py` — fatos](164-render-facts.md) | — | S | **feito** (`007402e`) | `records_facts`, `comparison_facts`, `products_facts`, `stores_facts` |
| 165 | [`render.py` — frases-molde](165-render-fallback-lines.md) | — | S | **feito** (`e002d2a`) | `search_fallback_line`, `compare_fallback_line` |
| 166 | [`Deps.client` + fiação](166-deps-client-wiring.md) | — | S | **feito** (`650c261`) | `Deps.client`, `HttpLlmClient` em `build_application`/`on_text` |
| 167 | [`turn.py` — leituras](167-turn-narration-reads.md) | 163, 164, 165, 166 | M | **feito** | Modo A/B nas 4 leituras, `_narrate`, cortes de tamanho — achado: `asyncio.to_thread` quebra com `sqlite3` (ver ticket) |
| 168 | [`turn.py` — escrita](168-turn-narration-writes.md) | 163, 166 | M | **feito** | comentário em `PendingWrite`/`WriteResult`/`WriteFailed`, `client` em `on_tap` |
| 169 | [docs + smoke](169-docs-and-smoke.md) | 167, 168 | S | **feito** | `CLAUDE.md` v2.7, roteiro de smoke (passos 16–20), `julius-rock-persona.md` movido para `docs/requirements/` |

### Dependências e caminho crítico

```
163 ─┐
164 ─┼─┐
165 ─┤ │
166 ─┴─┼── 167 ──┐
       └── 168 ──┴── 169
```

163–166 são independentes entre si (podem ser feitos em paralelo); 167 e 168 dependem de 166 mas não uma da outra (também paralelizáveis); 169 fecha depois das duas.

### Riscos e onde os tickets os tratam

| Risco | Ticket | Mitigação |
|---|---|---|
| Corte de tamanho errado pro catálogo real | 167 (medido em 18/09/2026, ver `<!-- adjustments -->`) | `NARRATE_FULL_MAX_GROUPS` ajustado de 3 para 6 direto no código |
| Persona soar mecânica/genérica apesar da guarda | 163 (prompt conciso), 169 (achado qualitativo do smoke) | sem métrica automática — é leitura humana, mesmo espírito do resto da camada de IA deste projeto |
| Comentário de escrita insinuar que algo já foi feito antes do tap | 168 (nota para o agente) | revisão manual no smoke (169, item 5); design já exige o oposto (RF3 do brainstorm) |
| Custo por mensagem dobrar sem se perceber | 163/167/168 (reaproveitam `_ask`/`record_usage` sem caminho novo) | `ai_calls.jsonl` já registra tudo; smoke (169) lê o custo real |
