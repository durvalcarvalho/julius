# Julius — interface de bot no Telegram: design

> `/sc:design` de 2026-09-17, a partir de `docs/requirements/messaging-bot-integration.md` (F1–F12, RF1–RF9, RNF1–RNF5) e das duas pesquisas do mesmo dia (`claudedocs/research_messaging_bot_integration_20260917.md`, `claudedocs/research_bot_stack_libraries_20260917.md`). Especificação de alto nível; **nenhum código foi alterado.**
> Referência estudada com desconfiança: `../majordomo` (fora deste repo). §8 lista o que foi adaptado dele e o que foi deixado lá, com o motivo de cada um.
> **Implementado em 2026-09-17 (tickets 150–162).** O §4.3 não foi vetado: as ações são *output functions*, e a implementação confirmou a premissa — a chamada encerra o run e o resultado não volta ao modelo (teste que conta chamadas de modelo). O que mudou em relação ao texto abaixo está registrado em §9.
> **Um ponto da pilha pesquisada fica mais estreito neste design** (§4.3): o mecanismo de confirmação do PydanticAI ("Deferred Tools") passa de "o mecanismo" para "alternativa documentada" — a leitura da documentação mostrou que ele devolve o resultado da escrita **ao modelo**, que gera a frase final, e é exatamente essa frase que o próprio brief manda não usar como resposta. O requisito (RF8) não muda; o encaixe muda. Decisão do usuário, registrada para veto.

## 0. O que os requisitos já decidiram e este design obedece

| Decisão fechada | Consequência no design |
|---|---|
| Telegram, long polling, sem porta exposta (F1, F3, F4, RF3, RNF2) | `python-telegram-bot` com `run_polling()`; nenhum servidor HTTP, nenhum webhook, nenhuma URL pública em lugar nenhum do código (§2) |
| Bot é consumidor de `services/*` no mesmo processo (F7) | Pacote novo `julius/bot/`, camada L4 ao lado de `cli/`, com a **mesma** linha de permissões na DAG; `cli` e `bot` nunca se importam (§1) |
| Toda mensagem passa pela IA (RF6, RNF4) | Uma chamada de modelo por mensagem, sempre; orçamento partilhado com a curadoria via o **mesmo** contador `ai_usage` e o **mesmo** log `ai_calls.jsonl` (§5) |
| Menu de ações fechado, IA só propõe (F10, RNF5) | Ações são funções Python registradas explicitamente no agente; não existe tool genérica; a IA nunca recebe `conn`, shell, arquivo ou rede (§3) |
| Código valida antes de executar (RF7) | Toda ação resolve/valida seus alvos em código **antes** de qualquer efeito; id inexistente vira `ModelRetry` com os candidatos reais, nunca exceção solta (§3.3) |
| Escrita exige confirmação; leitura não (RF8) | Ação de escrita **não executa** na primeira passada — devolve uma pendência; o tap do usuário é o que executa, em código, sem o modelo no caminho (§4) |
| `chat_id` vem do transporte (F11, RF9) | Allowlist checada no handler mais externo do Telegram, antes da IA; nenhuma tool tem parâmetro `chat_id` (§2.2) |
| Escrita reversível, escopo = comandos que já existem (RF1) | As ações são espelho 1:1 dos comandos de `julius produtos`/`mercados` que gravam dado reversível; nada novo é gravado (§3.1) |
| PC liga/desliga, dados locais, sem sincronização (F5, F6, RNF3) | Estado pendente e histórico em memória; reiniciar perde os dois, e isso é aceito; banco é o `prices.db` local via `infra.db.connect` (§4.4) |
| Curadoria (`enrich`, `merge`, `packaging`, `store`) não muda | `infra/llm_client.py` e `services/suggestions.py` seguem intactos no que já fazem; o bot **não** reaproveita o client `urllib` — usa o do PydanticAI (§5.3) |

## 1. Onde o bot entra na árvore

```
julius/
├── cli/      # L4 · interface de terminal (existente)
└── bot/      # L4 · interface de mensageria (novo) — irmão de cli, nunca filho nem pai
```

**Regra da DAG.** `tests/test_architecture.py::ALLOWED_IMPORTS` ganha uma linha: `"bot": {"domain", "config", "infra", "services"}`. Sem `parsers` — o bot não lê recibo (o `importar` fica fora do escopo, §3.1) e sem `cli`. A ausência de `bot` na linha de `cli` é o que garante que `import julius.cli` continua sem `python-telegram-bot`/`pydantic-ai` no grafo (`tests/test_cli.py` já protege "import sem efeito colateral"; ganha o irmão "import sem dependência do bot").

**Ponto de entrada próprio, não um subcomando da CLI.** `[project.scripts]` ganha `julius-bot = "julius.bot:main"`. Um `julius bot` dentro do Typer faria `cli → bot`, quebrando a simetria acima e arrastando as dependências do bot para todo comando de terminal. Duas interfaces, dois executáveis, um pacote.

**Dependências como extra opcional.** `[project.optional-dependencies] bot = ["python-telegram-bot", "pydantic-ai-slim[openai]"]` (a variante *slim* com só o provider OpenAI-compatível — é o formato da API do DeepSeek — evita instalar todos os outros provedores). A máquina de desenvolvimento continua com `pipx install --editable .`; a de deploy usa `.[bot]` (um alvo novo no `Makefile`). `pydantic-ai` traz `pydantic` e `httpx`; `python-telegram-bot` traz `httpx` — uma pilha HTTP assíncrona só.

**O único toque em código existente fora de `config.py`/`pyproject.toml`**: os quatro formatadores puros de `cli/_common.py` — `money`, `br_date`, `relative_age`, `content_text` — são exatamente o que o bot também precisa, e são funções sem I/O, só stdlib. Eles **se movem para `domain/`** (um módulo de formatação de texto) e `cli/_common.py` passa a importá-los de lá; `date_cell` fica em `cli` porque devolve `rich.text.Text`. É mover, não reescrever — `tests/test_cli_common.py` continua valendo pelo import antigo ou passa a importar do novo lugar, à escolha da implementação. A alternativa (o bot importar `cli._common`) foi rejeitada: criaria a única seta L4→L4 do projeto e traria `typer`/`rich` para o grafo do bot por causa de quatro funções de string. `test_domain_imports_nothing_outside_the_standard_library` já garante que nada de terceiro entra junto.

## 2. Os módulos do pacote `bot` e o que cada um faz

Quatro responsabilidades, quatro módulos (nomes ilustrativos — o layout exato é da implementação, o que importa é a fronteira entre eles):

| Módulo | Responsabilidade | Não faz |
|---|---|---|
| **`app`** (`main()`) | Checagens de partida (§2.1), construção do `Application` do PTB, registro de **três** handlers (texto, callback de botão, `/start`), teto do logger HTTP, `run_polling()` | Nenhuma lógica de negócio; nenhuma chamada de IA |
| **`turn`** | O turno de uma mensagem já autorizada: orçamento → agente → resultado → resposta ou pendência; e o turno de um tap: pendência → execução em código → resposta. É uma função `async` que recebe deps e texto e **devolve** o que responder — não fala com o Telegram | Não sabe o que é um `Update`; é o que os testes exercitam sem PTB |
| **`actions`** | As tools: funções Python finas sobre `services/*`, com type hints e docstring (o schema nasce daí). Divididas em leitura, consulta de apoio e escrita (§3) | Não formatam texto para o usuário; devolvem dados de `domain` ou uma pendência |
| **`render`** | `list[PriceRecord]`, `StoreComparison`, `Product`, `Store`, a pendência e o resultado de uma escrita → texto do Telegram (§6) | Não decide nada; regra de negócio (destaque, base de comparação) já vem pronta de `services` |

O estado por conversa — histórico curto e a pendência de escrita — vive no `chat_data` que o próprio PTB oferece por chat, em memória. Não há módulo de estado nem persistência: com um usuário, um chat e um PC que desliga, um dicionário é o tamanho certo (§4.4).

### 2.1 Partida: recusar a subir é melhor que subir aberto

`main()` verifica, nesta ordem, e **termina com mensagem clara** se qualquer item falhar — sem `doctor`, sem aviso-e-segue:

1. `JULIUS_BOT_TOKEN` definido (`Config.bot_token`).
2. `JULIUS_BOT_ALLOWED_CHAT_ID` definido e inteiro (`Config.bot_allowed_chat_id`). Lista vazia = não sobe (adaptado do `majordomo`, §8).
3. `Config.ai_configured` **e** os dois preços por token — sem isso não há roteamento (RF6) nem contador de gasto (RNF4); o bot não tem modo "sem IA".
4. `infra.db.connect(config.db_path)` abre (roda migrações pendentes exatamente como o primeiro comando da CLI faria).

`Config` ganha os dois campos e uma propriedade `bot_configured`; `config.load` lê as duas variáveis — mesmo padrão dos `JULIUS_AI_*`, testado em `tests/test_config.py`.

**Teto de log.** `httpx` e `httpcore` em `WARNING` antes de qualquer polling: em `INFO` a URL do `getUpdates` sai no log com o token dentro (pitfall documentado no `majordomo`, verificado na fonte).

### 2.2 A allowlist é o primeiro `if` de cada handler

Os três handlers começam igual: `update.effective_chat.id == config.bot_allowed_chat_id`, senão **retornam sem responder** e registram uma linha de log com o `chat_id` recebido. Isso serve a dois propósitos: (a) um estranho que achar o bot não recebe nem "acesso negado" — silêncio não confirma que há alguém do outro lado; (b) é o **bootstrap** do próprio usuário: na primeira vez, ele manda `/start`, lê o próprio `chat_id` no log, coloca na variável e reinicia — sem comando especial, sem passo de "descoberta".

O callback do botão (tap de confirmação) passa pela mesma checagem, no mesmo lugar: quem confirma tem que ser o mesmo chat que pediu.

## 3. O menu de ações e o contrato com `services/*`

### 3.1 O que entra e o que fica de fora

As ações são o espelho dos comandos que **já existem** e cabem em texto curto. Nada aqui grava um dado que a CLI não grave hoje.

| Grupo | Ações (o que a IA pode escolher) | Chama | Confirmação |
|---|---|---|---|
| **Leitura** | consultar preços (termo e/ou tag) · comparar mercados · listar produtos · listar mercados | `search.search_free_text` / `search.search_prices` · `comparison.compare_stores` · `catalog.list_products` · `catalog.list_stores` | Nenhuma; responde na hora |
| **Escrita reversível** | renomear produto · renomear mercado · marcar/remover tag · definir/remover tipo · definir/remover conteúdo · fundir · desfundir | `catalog.rename_product` · `rename_store` · `tag_product`/`untag_product` · `set_product_kind`/`clear_product_kind` · `set_product_content`/`clear_product_content` · `merge_products` · `unmerge_product` | Sempre (§4) |

**Fora, com motivo:**
- `importar` — precisa de um HTML no disco; o canal para isso (foto do QR/recibo) é evolução futura do `CLAUDE.md`, e quando vier entra por um handler de foto no mesmo pacote, não por esta rodada.
- `exportar` — produz arquivo; mandar CSV pelo chat é feature própria, não cabe aqui.
- `produtos revisar`/`mercados revisar` — fluxos interativos com prompts próprios e gasto de IA em lote; rodam na CLI.
- `produtos comparar ID_A ID_B` — seria uma chamada de IA dentro de um turno de IA; a pergunta "esses dois são o mesmo?" pode virar ação mais tarde se fizer falta.

### 3.2 O contrato: deps, não parâmetros

Cada ação recebe do PydanticAI um `RunContext[Deps]`, onde `Deps` carrega a conexão do turno e a `Config`. **A IA nunca vê nem preenche `conn`, `config` ou `chat_id`** — eles entram pelo lado do código, exatamente como a CLI passa `open_db()` aos serviços. Os parâmetros que a IA preenche são só os do domínio: termo, tag, id, nome, quantidade, unidade.

A conexão é **por turno**: aberta no handler com `infra.db.connect` e fechada no `finally`, como todo comando da CLI faz. As ações são `async def` finas que chamam o serviço síncrono diretamente — SQLite local responde em sub-milissegundo (medido no projeto para a view `product_group`: 21 ms para 105 produtos), então não há motivo para thread nem para `check_same_thread=False`. A única espera longa do turno é a chamada ao modelo, e essa o PydanticAI já faz com `httpx` assíncrono — o polling nunca bloqueia. (Corrige a nota da pesquisa: `asyncio.to_thread` só seria necessário se o bot reaproveitasse `infra/llm_client.py`, e ele não reaproveita.)

### 3.3 Validar antes, e recusar nomeando a saída

Toda ação que recebe um id resolve o alvo em código **antes** de qualquer efeito (`catalog._require_product`/`get_product`, `list_stores` por CNPJ). Id inexistente ou nome ambíguo → a ação levanta `ModelRetry` com os **candidatos reais** (id · nome, via a mesma busca palavra a palavra de `services/search.py`), e o modelo devolve uma pergunta ao usuário ou corrige o argumento. É a versão de duas linhas da regra que o `majordomo` aprendeu caro: "uma recusa carrega os candidatos, senão o modelo inventa um id" (§8).

As ações de escrita aceitam **id ou nome** para produto/mercado. Nome único → resolve; nome ambíguo → `ModelRetry` com a lista; a IA não é quem decide qual "tomate" é — ela pergunta. `ValueError`/`LookupError` dos serviços (nome vazio, ciclo de fusão, id inexistente) são convertidos no mesmo ponto; **nenhuma exceção atravessa uma ação** — o turno sempre termina em resposta ou em silêncio deliberado.

## 4. O turno: como a mensagem vira ação, e a escrita vira pendência

### 4.1 O princípio que organiza o fluxo: o modelo roteia, o código executa e responde

A resposta que o usuário lê é **renderizada pelo código a partir do retorno real** do serviço (F10, e a lição central do `majordomo`). O texto do modelo só chega ao usuário num caso: quando **nenhuma** ação foi escolhida — saudação, pergunta de esclarecimento ("qual tomate: [23] ou [7]?"), "não entendi". O mecanismo que garante isso está em §4.3.

### 4.2 Turno de leitura

```
Telegram ──getUpdates──▶ handler de texto
  allowlist? não ──▶ log + silêncio
  pendência de escrita neste chat? sim ──▶ cancela, avisa, e segue com o texto novo
  orçamento do mês ok? não ──▶ resposta determinística: "IA do mês esgotada (US$ x de y)"
  conn = infra.db.connect(...)
  agent.run(texto, deps=Deps(conn, config), message_history=últimas N)
     ├─ saída: texto do modelo ──────────────▶ responde o texto (único caso de prosa da IA)
     └─ saída: retorno de uma ação de leitura ▶ render(retorno) ──▶ responde
  cobra tokens em ai_usage · linha em ai_calls.jsonl · (consulta) linha em query_log.jsonl
  conn.close()
```

### 4.3 Turno de escrita — duas passadas, o modelo só na primeira

```
passada 1 (mensagem)                       passada 2 (tap no botão)
────────────────────────────────           ─────────────────────────────────────
agent.run(...) escolhe ação de escrita     callback ──▶ allowlist? nonce bate e não expirou?
  ação valida alvos em código                 sim ──▶ executa o serviço EM CÓDIGO
  ação devolve PendingWrite                          render(retorno real) + comando de desfazer
  (ação, args validados, preview do banco,           edita a mensagem: congela o desfecho
   nonce, criado_em)                          não ──▶ "não executado" (expirado / cancelado)
render(pendência) + botões                 qualquer texto novo enquanto pende ──▶ cancela
[✅ Confirmar] [❌ Cancelar]                timeout (5 min) ──▶ nega, avisa
```

**O que a pendência carrega é o que o usuário lê, e nada dela veio do modelo além dos argumentos já validados.** O *preview* — "Vou fundir **Tomate italiano União (23)** em **Tomate italiano (7)**; 3 preços passam a aparecer no grupo" — é computado pela ação com os nomes lidos do banco pelos ids, nunca com o nome que o modelo "lembrou" (F12 e §8). Para `definir-conteudo`, o preview mostra a unidade **já normalizada** (`500 G` → `0,5 KG`), que é o que será gravado.

**Mecanismo no PydanticAI — e a tensão com a pilha pesquisada.** A pesquisa apontou os *Deferred Tools* (`requires_approval=True`). Lendo a documentação para este design, o fluxo deles é: a tool marcada pausa, o run devolve `DeferredToolRequests`, o código decide, e **roda o agente de novo** com `deferred_tool_results` — a tool executa e o resultado volta **para o modelo**, que gera a frase final. Isso colide com §4.1 em dois pontos: (1) a frase final é prosa do modelo sobre uma escrita, exatamente o que não pode ser a resposta; (2) pagar uma segunda chamada de modelo para produzir um texto que será descartado. Uma escrita negada vira `ToolDenied` **no contexto do modelo**, e é justamente nesse cenário que o `majordomo` registrou "Done — recorded ₱500" depois de uma negação.

Por isso o design usa o **outro** mecanismo pronto do PydanticAI, *output functions*: `output_type=[str, <ações...>]` — "o modelo é forçado a chamar uma delas, a chamada encerra o run, e o resultado **não volta ao modelo**" (documentação, verbatim). Para leitura, a função devolve os dados e o run termina; para escrita, a função **não executa** — devolve a `PendingWrite`. A execução, no tap, é uma chamada direta ao serviço, sem agente. Uma chamada de modelo por mensagem, zero prosa sobre efeitos, e a máquina de estados da confirmação é um dicionário com um nonce.

**Custo aceito do mecanismo:** o modelo não vê resultado de ação nenhuma, então **não encadeia** ("busca o id e depois renomeia" em um turno só). É por isso que as ações de escrita aceitam nome e resolvem em código (§3.3), e é por isso que uma mensagem com duas ações ("renomeia X e marca tag Y") executa a primeira e o modelo é instruído a pedir a segunda em outra mensagem — uma ação por mensagem é uma limitação declarada, não um bug. *Deferred Tools* ficam como alternativa documentada se a implementação encontrar um limite de biblioteca em *output functions* (por exemplo, `ModelRetry` ou `str` não convivendo como esperado com elas) — a mudança seria contida em `turn`/`actions`, sem tocar RF8.

**Fail-closed em todos os caminhos** (RF8, §8): nonce diferente, pendência expirada, texto novo, exceção ao editar a mensagem, exceção ao executar — nada disso executa, tudo limpa a pendência num `finally`, e o usuário recebe "não executado" onde houver alguém para ler. Timeout de **5 minutos**: o `majordomo` começou com 120 s e subiu para 300 s depois que um tap real caiu em 121 s; com um usuário só e sem fila, o lado mais generoso é o mais barato.

**Botão, não "sim" por texto.** O `callback_data` leva o nonce da pendência, então um tap atrasado numa mensagem antiga não confirma uma pendência nova; um "sim" digitado seria ambíguo com uma frase qualquer que comece com "sim". A mensagem de confirmação é **editada** depois do desfecho (✅/❌/⏰) para nunca parecer pendente numa tela rolada — padrão do `majordomo` que custa três linhas.

### 4.4 Estado por conversa: em memória, de propósito

- **Histórico**: as últimas *N* mensagens (número pequeno, na casa de 6 — cada uma volta ao modelo como tokens e o orçamento é partilhado) em `chat_data`, passadas como `message_history`. Dá contexto a "e no Assaí?" depois de uma consulta. Reiniciar zera.
- **Pendência**: **uma** por chat — uma nova substitui e cancela a anterior (a última palavra do usuário é a única que vale). Reiniciar perde a pendência; o tap que chegar depois encontra nonce nenhum e recebe "expirou". O `majordomo` documenta o mesmo vão como "deliberately not built"; aqui coincide com RNF3 — o PC desliga, o estado em voo vai junto, e a única consequência é repetir o pedido.

## 5. Orçamento, logs e o modelo

### 5.1 Um contador, um log — os que já existem

Antes do agente: `suggestions.is_available(conn, config)` — falso por orçamento estourado gera a resposta determinística com `spent_this_month` e o teto, sem tocar o modelo (mesma separação de motivos que `produtos comparar` já faz).

Depois do agente: o custo é `result.usage()` × os dois preços de `Config`, gravado por `repositories.ai_usage.add_spent` **através de um serviço**, porque o bot não importa `repositories` (§1). Hoje a cobrança e o registro vivem dentro de `suggestions._ask`, privados. O design pede que esse trecho vire **uma função pública** em `services/suggestions.py` — cobrar e logar uma tentativa, dados tokens, custo, latência e erro — chamada por `_ask` e pelo bot. **Não há um segundo contador nem um segundo formato de linha**: o registro em `ai_calls.jsonl` é o mesmo dicionário, com `call_kind="bot_turn"` e a versão do prompt do bot em `PROMPT_VERSIONS`. Uma tentativa que falhou ou veio truncada é cobrada e logada como as outras — pagou, conta.

Consultas feitas pelo bot também escrevem em `query_log.jsonl` (mesmo `infra/ai_log.py::append`, mesmos campos, mais `channel: "bot"`): é o dado que a v2.1 guardou para recalibrar cortes, e o bot vai ser a origem da maioria das buscas.

**`actions.jsonl` não recebe as escritas do bot.** Aquele log existe para gravações **automáticas** da IA, com desfazer; uma escrita do bot é o usuário pedindo e confirmando, como um comando da CLI — e a CLI não loga os seus. A resposta traz o comando de desfazer, como `julius produtos fundir` já imprime. Simetria com a CLI, registrada como decisão.

### 5.2 O modelo: as mesmas três variáveis

`OpenAIChatModel(config.ai_model, provider=OpenAIProvider(base_url=config.ai_base_url, api_key=config.ai_api_key))` — reaproveita `JULIUS_AI_BASE_URL`/`_API_KEY`/`_MODEL` sem variável nova e sem o provider "DeepSeek" dedicado: a `base_url` já aponta para o DeepSeek, e é a única "abstração de provedor" que o projeto quer (mesma decisão registrada para o client da curadoria).

**`JULIUS_AI_REQUEST_EXTRAS` (o `thinking` desligado) precisa chegar ao corpo do request.** Sem isso o `deepseek-flash` raciocina até estourar `max_tokens` (medido no smoke test de 15/09). No PydanticAI o lugar é `model_settings` com corpo extra; **confirmar no smoke test real que o campo chega e que o modelo converge com `tools`** é o primeiro item de §9 — o mesmo achado da v2 pode se repetir, e é barato de detectar cedo.

### 5.3 O que não muda

`infra/llm_client.py` (urllib, JSON mode, `finish_reason` como erro) e tudo em `services/suggestions.py` que a curadoria usa continuam como estão: são chamadas simples, de baixa frequência, sem tool-calling — proporcionais ao `urllib`. O bot não passa por ali. Duas pilhas de IA no mesmo processo não são duplicação: são dois problemas de tamanhos diferentes com a ferramenta do tamanho de cada um. Se um dia a curadoria quiser tool-calling, aí sim ela migra para o mesmo agente — não antes.

## 6. Renderização: a tela é um celular

A CLI renderiza tabelas `rich` de seis colunas para um terminal largo; um celular tem ~40 colunas e o Telegram não tem cor. **Renderização diferente é feature, não duplicação** — a regra de negócio (destaque, base de comparação, colapso de linhas iguais) chega pronta de `services`; o bot só escolhe como mostrar.

- Uma linha por registro, em bloco monoespaçado (`<pre>`, HTML do Telegram): `16/09/2026 · há 1 dia · R$ 12,90/kg · Assaí — Águas Claras`. Destaque por marcador de texto (▼ menor · ▲ maior), já que não há verde/vermelho.
- Grupos por unidade continuam separados (UN e KG nunca na mesma lista), e a linha final "Mais barato por litro: …" continua existindo — é a mesma informação de `PriceRecord.price_per_content`/`highlight`, com outro layout.
- Datas e dinheiro pelos formatadores movidos para `domain/` (§1) — a mesma `relative_age` da CLI, com `today` injetável nos testes.
- **Escape de HTML obrigatório** em todo texto vindo do banco (nomes de produto com `&`, `<`): é o próprio bot mandando marcação para a própria tela, mas um nome como `AÇÚCAR & CIA` quebraria a mensagem em silêncio.
- **Limite de 4096 caracteres por mensagem**: o `limit` de `search_prices` (default 20) já segura o tamanho típico; acima do limite, corta e diz quantas linhas ficaram de fora e como estreitar (`limite` menor, tag). Sem paginação.

## 7. Testes que o design exige

Mesma regra do projeto: todo módulo com um `if` nasce com caminho feliz e triste, SQLite real em `tmp_path`, rede nunca. O que muda é a fonte do "modelo":

- **`FunctionModel` do PydanticAI** roteia o teste: um script diz "o modelo chamou a ação X com os argumentos Y" e o teste afirma o efeito real no banco e o texto renderizado. **`models.ALLOW_MODEL_REQUESTS = False`** no `conftest`, autouse — o irmão do `_no_cnpj_lookup`, pela mesma razão histórica (a suíte já consultou uma API de verdade uma vez, por 103 s).
- **A função de turno é testada sem PTB**: recebe deps e texto, devolve o que responder. Um único teste de fiação confirma que os handlers chamam o turno e respeitam a allowlist; o resto não sabe o que é um `Update`.
- Casos obrigatórios: chat fora da allowlist → nenhuma resposta **e nenhuma chamada de modelo** (o `FunctionModel` conta chamadas); orçamento estourado → resposta determinística e zero chamadas; leitura → resposta vem do banco, não do texto do modelo; escrita → **nada gravado** antes do tap; tap com nonce certo grava e responde com o desfazer; nonce errado, pendência expirada, texto novo e exceção na execução → nada gravado, pendência limpa; partida sem token, sem allowlist ou sem IA configurada → termina com mensagem; `import julius.cli` não importa `telegram` nem `pydantic_ai`; renderização escapa HTML e respeita o teto de 4096.
- O smoke test contra o DeepSeek real continua sendo do usuário, com a chave no shell dele — como sempre foi.

## 8. O que veio do `majordomo`, e o que ficou lá

Estudado com desconfiança, como pedido. Adaptado, porque é barato e cobre risco real nesta escala:

| Padrão | Onde entrou aqui |
|---|---|
| "O modelo não é confiável; o framework verifica" | §4.1/§4.3 — resposta vem do retorno real; o modelo nunca narra uma escrita |
| Preview computado pela ferramenta, não repetido do modelo | §4.3 — nomes lidos do banco pelos ids validados |
| Fail-closed em todo caminho de erro | §4.3 — timeout, nonce, exceção e texto novo negam |
| Recusa subir com allowlist vazia | §2.1 |
| Logger HTTP em `WARNING` para não vazar o token | §2.1 |
| Recusa que nomeia os candidatos, para o modelo não inventar id | §3.3 — `ModelRetry` com id · nome |
| Nonce no botão; mensagem editada com o desfecho | §4.3 |
| Timeout de 300 s aprendido na prática | §4.3 |

Deixado lá, porque resolve escala ou produto que o Julius não tem:

- Arquitetura hexagonal de 5 camadas com `import-linter` — a DAG de 4 camadas em `tests/test_architecture.py` já é enforcement, e ganhou uma linha.
- Fallback entre provedores; roles de modelo; canário de partida — um provedor, medido e orçado.
- Aprovação em lote com *fingerprint* — nasceu de 18% de negações em sessões de dezenas de escritas; aqui é uma ação por mensagem.
- Bloquear a tool **dentro** do turno esperando o tap (que exige `concurrent_updates` e lock por chat) — aqui o turno **termina** ao mandar a pergunta e o tap é um update novo; com processamento sequencial do PTB não há corrida nem lock.
- Detectores de "disse que fez mas não chamou" — desnecessários quando o modelo nunca é a fonte da resposta sobre efeitos.
- Memória com embeddings, RAG, execução de código, control room, skills, quatro arquivos de config — sem relação com o domínio.

E um princípio do `majordomo` que confirma um do Julius: a seção "Deliberately not built" dele mede e recusa o LiteLLM por trocar ~100 linhas por uma dependência grande. É a mesma disciplina do `urllib` na curadoria — copiada a atitude, não a decisão.

## 9. A verificar na implementação (não são decisões deste design)

1. **Smoke test real antes de qualquer outra coisa**: `deepseek-flash` com `tools` e `thinking` desligado via `model_settings` do PydanticAI converge? Qual é o nome exato do modelo que a API aceita hoje (`deepseek-flash` vs. `deepseek-v4-flash`)? Mesma disciplina do smoke test de 15/09, mesmo dono (o usuário).
2. *Output functions* convivendo com `str` e com `ModelRetry` no `deepseek-flash` — se algo não fechar, o plano B de §4.3 (*Deferred Tools*, resposta renderizada do `ToolReturnPart`) está descrito e é contido.
3. Nomes dos campos de `result.usage()` na versão instalada do PydanticAI, para a cobrança de §5.1.
4. Texto do prompt de sistema do bot — em português, versionado em `PROMPT_VERSIONS`, e **medido** contra uma dúzia de frases reais antes de fechar (o projeto já aprendeu que mexer em prompt medido invalida a medição; este nasce medido).
5. Como o PTB é iniciado quando o PC liga fica de fora, como os requisitos já disseram (§5 deles): `julius-bot` na mão até incomodar.

### 9.1 Respondido pela implementação (2026-09-17, pydantic-ai 2.44.0, python-telegram-bot 22.8)

- **Item 2 — resolvido, e com uma pegadinha.** *Output functions* convivem com `str` e com `ModelRetry` exatamente como o design supôs: a chamada encerra o run (um teste conta as chamadas de modelo e exige **uma**), `ModelRetry` devolve o turno ao modelo, e prosa vira `str`. O plano B (*Deferred Tools*) **não** foi necessário. A pegadinha: o PydanticAI expõe a ação como **`final_result_<nome>`**, não pelo nome da função — chamar o nome nu cai no caminho de "Unknown tool", que **ainda assim termina o run** com a prosa do modelo como saída. Os testes derivam o nome de `__name__` e um deles afirma a convenção, para que uma mudança de biblioteca falhe em vez de passar em silêncio.
- **Item 3 — respondido.** `result.usage` é **propriedade**, não método (`result.usage()` levanta `TypeError`). Os campos `input_tokens`/`output_tokens` estão corretos.
- **Item 4 — parcialmente.** O prompt nasceu em português e versionado, mas em `BOT_PROMPT_VERSION` e **fora** de `PROMPT_VERSIONS` (esse dict é dos prompts da curadoria; o bot passa a versão explicitamente em `record_usage`). Ele **ainda não foi medido** contra frases reais: o `FunctionModel` da suíte não exercita prompt nenhum. A medição é o smoke do usuário.
- **Itens 1 e 5 — ainda do usuário.** O smoke real é o que confirma se o `deepseek-flash` escolhe ação de forma confiável com catorze opções e se o `extra_body` desliga o *thinking* no caminho do PydanticAI. A assinatura da falha é a de 15/09: `output_tokens` na casa dos milhares em vez de dezenas, ou `error` preenchido em `ai_calls.jsonl`. Lista completa do smoke em `docs/tickets/julius-bot/162-bot-e2e-docs.md`; **anote o resultado aqui**.

### 9.2 O que a implementação descobriu e o design não previa

- `catalog.get_product` resolve para a **raiz do grupo**, então `Product.merged_into` nunca chega preenchido por `services`: a pré-checagem de `unmerge_product` foi refeita perguntando por id e comparando o que volta (id diferente **é** a fusão). Duas consequências, as duas mais seguras do que o desenho supunha: um ciclo de fusão não pode nem ser **proposto** pela ação, e desfundir por nome não pode errar de linha. Limite anotado no código: o `undo` do desfundir refunde na raiz, que é o pai direto de toda fusão feita em um passo.

## 10. Fora do escopo, de propósito

Foto de recibo/QR pelo bot (o pacote é o canal certo quando vier; hoje nenhum handler de foto), `exportar` pelo chat, pendência durável entre reinícios, histórico persistido, mais de uma ação por mensagem, menu de slash-commands do BotFather além de `/start` (o roteamento é por IA; um menu convidaria a decorar comandos, o oposto do pedido), streaming/edição progressiva de mensagem, qualquer segundo canal (WhatsApp, web).
