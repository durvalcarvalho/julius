# Pesquisa — bibliotecas prontas pro bot do Julius (function calling, confirmação humana, quem já fez isso)

Data: 2026-09-17. Escopo: com os requisitos fechados em `docs/requirements/messaging-bot-integration.md`, o pedido agora é achar o que já existe pronto — bibliotecas maduras e projetos reais — em vez de escrever o roteamento de mensagem, o loop de function-calling e a confirmação de escrita do zero. Relatório de pesquisa — nenhum código foi escrito, nenhuma decisão de arquitetura foi travada aqui.

## Resumo executivo

A pilha que resolve os requisitos quase inteira com peças prontas: **`python-telegram-bot` (assíncrono) + PydanticAI + o provider DeepSeek nativo do PydanticAI**. Três achados centrais:

1. **A recomendação anterior sobre `python-telegram-bot` precisa de correção**: desde a v20 (2023) a biblioteca **não tem mais API síncrona** — é assíncrona por completo. Isso parecia uma complicação frente ao resto do Julius (que não usa `asyncio` em lugar nenhum), mas é na verdade a solução de graça para um pitfall real e documentado: uma chamada de IA lenta **bloqueia o polling** e o Telegram derruba a conexão depois de ~30s se o handler for síncrono dentro de um bot assíncrono mal escrito.
2. **O padrão de confirmação antes de escrever (RF8, já fechado no brainstorm) já é uma feature pronta**, não uma modelagem que o Julius precisa inventar: **PydanticAI tem "Deferred Tools"** — marcar uma tool com `requires_approval=True` faz o framework parar antes de executar e devolver a proposta pra um código decidir, exatamente o fluxo "vou fundir X com Y — confirma?" que já foi desenhado sem saber que essa peça existia.
3. **Outras pessoas já construíram exatamente isto** — assistentes pessoais rodando dentro do Telegram, com tool-calling e escrita protegida por confirmação (`josephniel/majordomo` chama isso de "gated writes" e resume o princípio com uma frase que já é o F10 do nosso documento: "the model is not trusted to be correct; the framework verifies it").

## 1. Biblioteca do bot — correção da pesquisa anterior

| | Antes (pesquisa de infraestrutura) | Agora (com function calling no meio) |
|---|---|---|
| Suposição | `python-telegram-bot` como "mais parecido com o resto do código síncrono" | Não existe mais opção síncrona: desde a v20, a lib é 100% assíncrona (`run_polling()` roda sobre `asyncio`, sem wrapper síncrono). |
| Por que isso não é problema aqui | — | É a solução pronta pro pitfall documentado: se um handler síncrono chama uma IA que demora, o polling trava e o Telegram derruba a conexão em ~30s. Com o bot já em `asyncio`, múltiplas mensagens (e a espera pela IA) não bloqueiam o loop, desde que a chamada de rede também seja não-bloqueante (ver §5). |

Conclusão: `python-telegram-bot` continua sendo a escolha (madura, documentação extensa, API de alto nível pra registrar handlers) — só a premissa "por ser mais parecida com o resto do código" caiu; a razão certa agora é "resolve o bloqueio de I/O de graça".

## 2. Function calling / agent framework — PydanticAI

**O que ele resolve, ponto a ponto com os requisitos já fechados:**

| Requisito já fechado | O que PydanticAI já faz pronto |
|---|---|
| RF6 (apresentar o catálogo de ações à IA) | Tools são **funções Python comuns com type hints** — o framework gera o JSON schema sozinho a partir da assinatura, sem escrever o schema à mão. |
| RF7 (validar antes de executar) | Argumentos retornados pela IA já vêm **validados contra o tipo declarado** antes do código do bot recebê-los — validação de schema pronta, não código próprio de parsing. |
| RNF5 (allowlist fechada de ações, nunca "executar comando" genérico) | O menu de tools é a lista de funções que você registra explicitamente no `Agent` — não existe um modo "livre" de execução; é allowlist por construção. |

**Suporte a DeepSeek é nativo, de duas formas equivalentes:**
```python
# via provider dedicado (mais explícito sobre qual API está por trás)
from pydantic_ai import Agent
agent = Agent('deepseek:deepseek-v4-flash')

# ou apontando o modelo OpenAI-compatible pra base_url da DeepSeek
model = OpenAIChatModel('deepseek-v4-flash', provider=DeepSeekProvider(api_key=...))
```
Atenção: a documentação e exemplos referenciam `deepseek-v4-flash`; o `CLAUDE.md` do Julius usa o nome `deepseek-flash` (sem `v4`) para o modelo já configurado — vale confirmar com uma chamada real qual nome de modelo o `JULIUS_AI_MODEL` atual aceita antes de travar isso no design, mesma disciplina do smoke test que já pegou a pegadinha do `thinking`.

**Por que não LangChain**: o consenso de 2026 nas fontes pesquisadas é que LangChain é "overkill" quando o problema é só function calling — camadas de abstração pensadas pra pipelines complexos (RAG, múltiplos agentes encadeados) que o Julius não tem. PydanticAI, Instructor e Mirascope aparecem como as alternativas leves recomendadas; PydanticAI se destaca aqui porque já entrega, de fábrica, exatamente a peça que os outros dois não têm — o fluxo de aprovação (§3).

## 3. O padrão de confirmação de escrita já existe pronto: Deferred Tools

O que o brainstorm anterior desenhou organicamente ("ação de escrita mostra o que entendeu e só executa depois de confirmação") tem nome e implementação prontos no PydanticAI:

- Marcar uma tool com `requires_approval=True` faz a chamada **pausar** em vez de executar — o agente termina a rodada devolvendo um `DeferredToolRequests`, com o nome da tool, os argumentos já validados e um ID da chamada pendente.
- O código do bot decide o que fazer com essa pausa "como quiser — perguntar a um humano, checar uma política, inspecionar os argumentos" (é literalmente a descrição da documentação) — no caso do Julius, isso quer dizer mandar a mensagem de confirmação pro Telegram e esperar a resposta.
- Depois da resposta do usuário, o código monta um `DeferredToolResults` com o mesmo ID e roda o agente de novo, que só então executa a ação de verdade.
- Tools de leitura simplesmente **não** recebem `requires_approval=True` — executam direto, sem essa pausa. É o mesmo objeto/framework cobrindo os dois ramos do RF8, não dois mecanismos separados.

Isso substitui o que seria, sem a lib, uma máquina de estados própria pra "lembrar o que estava pendente entre a proposta da IA e o 'sim' do usuário" (um dos itens que o documento de requisitos deixou em aberto pro design) — o framework já guarda esse estado no próprio objeto de resultado.

## 4. MCP (Model Context Protocol) — avaliado e descartado

Vale registrar porque é a tecnologia "da moda" pra "expor funções como ferramentas de IA" (é inclusive o protocolo por trás das ferramentas desta própria sessão). A pesquisa confirma que **para um projeto de um usuário só, com um único provedor de IA, MCP é a escolha errada**: ele resolve um problema que o Julius não tem — portabilidade de tools entre múltiplos consumidores/clientes de IA diferentes. Isso significaria rodar um processo servidor MCP separado, gerenciar conexão entre ele e o bot, e nenhum ganho real, já que o único "consumidor" das tools do Julius é o próprio bot. O gatilho certo pra migrar pra MCP, segundo as fontes, é "quando aparece um segundo consumidor" das mesmas ferramentas — não é o caso aqui.

## 5. Pitfall documentado — bloqueio do event loop pela chamada de IA

Achado repetido em múltiplas fontes (issues reais do `python-telegram-bot`, guias de bots com LLM): declarar um handler `async` mas dentro dele chamar a IA de forma **síncrona/bloqueante** trava o loop de eventos inteiro — o polling para de responder, e o Telegram derruba a conexão de long-polling depois do timeout (~30s) se ela ficar presa tempo demais.

**Como isso toca o código que já existe no Julius**: `infra/llm_client.py` usa `urllib.request` (síncrono, por design — decisão registrada no `CLAUDE.md` pra chamadas simples de curadoria) e continua correto para os usos atuais (`enrich_products`, `suggest_merges`), que não mudam. Mas se o **mesmo client** for chamado direto de dentro de um handler assíncrono do bot, ele bloqueia o loop. A correção padrão documentada é rodar a chamada bloqueante dentro de `asyncio.to_thread(...)` — mantém o `llm_client.py` existente exatamente como está (reaproveita o código já testado da curadoria) e só isola a chamada síncrona numa thread quando invocada a partir do bot. Alternativa mais pesada (trocar o client HTTP inteiro por um assíncrono, ex. `httpx.AsyncClient`) resolveria o mesmo problema, mas reescreveria algo que já funciona — decisão pro `/sc:design`, não travada aqui.

## 6. Projetos que já fizeram isto — para aprender, não necessariamente para copiar

| Projeto | O que ensina |
|---|---|
| [`josephniel/majordomo`](https://github.com/josephniel/majordomo) | Assistente pessoal multi-provider (inclui DeepSeek) rodando no Telegram, com **"gated writes"** — escrita protegida por portão de aprovação, mesmo padrão do RF8. A descrição do próprio projeto resume o princípio F10 do nosso documento quase literalmente: "o modelo não é confiável por padrão; o framework verifica". Vale ler o código pra ver como ele modela a espera pela confirmação do usuário. |
| [`ma2za/telegram-llm-bot`](https://github.com/ma2za/telegram-llm-bot) | Bot local-first com tool calling (usa Ollama em vez de API remota, mas a estrutura de registrar tools e rotear por elas é equivalente); tem "readiness checks", relevante para o caso do PC que liga/desliga (F5 do documento de requisitos). |
| [`IvyZhang1113/personal-assistant-agent`](https://github.com/IvyZhang1113/personal-assistant-agent) | Multi-canal (Web/Telegram/Discord) com tools de calendário/tarefas/busca — mais genérico que o caso do Julius, mas mostra o padrão de sessão compartilhada entre canais, caso um dia o Julius ganhe mais de um canal. |
| [`AIXerum/AI-Telegram-Assistant`](https://github.com/AIXerum/AI-Telegram-Assistant) | Usa sub-agentes por domínio (email, agenda, tarefas) — analogia direta seria "um agente por área do Julius" (catálogo, preços), mas para o escopo atual (poucas tools) provavelmente é granularidade demais. |

Nenhum desses precisa virar dependência do Julius — são referência de padrão e de pitfalls já resolvidos por outros, que é exatamente o que foi pedido.

## 7. Pilha recomendada (síntese, decisão fica pro `/sc:design`)

- **Transporte**: `python-telegram-bot` (assíncrono, v22+) — long polling, allowlist de `chat_id` no handler mais externo, antes de qualquer coisa tocar a IA.
- **Roteamento/agent**: PydanticAI, com as funções de `services/*` (ou wrappers finos sobre elas) registradas como tools; tools de escrita com `requires_approval=True`, tools de leitura sem.
- **Provider de IA**: `DeepSeekProvider` nativo do PydanticAI, reaproveitando a mesma chave/variáveis de ambiente que a curadoria já usa — nome exato do modelo a confirmar por teste real.
- **Curadoria de catálogo (`enrich_products`, `suggest_merges` etc.)**: **sem mudança** — continua em `infra/llm_client.py` com `urllib.request`, que já é proporcional ao problema dela (chamada simples, sem tool-calling).
- **Concorrência**: chamada ao `llm_client.py` existente, se reaproveitada a partir de um handler do bot, entra via `asyncio.to_thread(...)` para não bloquear o polling — sem reescrever o client síncrono já testado.
- **MCP**: fora, por ora — sem segundo consumidor das tools, não se paga.

## Fontes

- [Pydantic AI: Build Type-Safe LLM Agents in Python – Real Python](https://realpython.com/pydantic-ai/)
- [Model Providers | Pydantic Docs](https://pydantic.dev/docs/ai/models/overview/)
- [OpenAI | Pydantic Docs](https://ai.pydantic.dev/models/openai/)
- [pydantic_ai.providers | Pydantic Docs](https://ai.pydantic.dev/api/providers/)
- [Deferred Tools | Pydantic Docs](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/)
- [Human-in-the-loop approval of tool calls · Issue #1995 · pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai/issues/1995)
- [Human-in-the-Loop | Pydantic AI - Andrei Nita](https://andreinita.co/learning/pydantic-ai/20-human-in-the-loop-deferred-tools/)
- [8 Best Function Calling Libraries for LLMs [2026] | TECHSY](https://techsy.io/en/blog/best-function-calling-libraries)
- [13 Best LangChain Alternatives for AI Agent Development (2026) | Rasa Blog](https://rasa.com/blog/langchain-alternatives)
- [PTB goes asyncio in v20! · python-telegram-bot/python-telegram-bot · Discussion #2351](https://github.com/python-telegram-bot/python-telegram-bot/discussions/2351)
- [python-telegram-bot v22.8 docs](https://docs.python-telegram-bot.org/)
- [Investigate delays in long polling · Issue #3691 · python-telegram-bot/python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot/issues/3691)
- [GitHub - josephniel/majordomo](https://github.com/josephniel/majordomo)
- [GitHub - ma2za/telegram-llm-bot](https://github.com/ma2za/telegram-llm-bot)
- [GitHub - IvyZhang1113/personal-assistant-agent](https://github.com/IvyZhang1113/personal-assistant-agent)
- [GitHub - AIXerum/AI-Telegram-Assistant](https://github.com/AIXerum/AI-Telegram-Assistant)
- [MCP vs Function Calling – How They Actually Work Together](https://portkey.ai/blog/mcp-vs-function-calling/)
- [Function-Calling VS Model Context Protocol (MCP): Complete Guide](https://runloop.ai/blog/function-calling-vs-model-context-protocol-mcp)
