# Julius num app de mensageria: requisitos

> Brainstorm de 2026-09-17 (`/sc:brainstorm`), continuação da pesquisa do mesmo dia (`/sc:research`, `claudedocs/research_messaging_bot_integration_20260917.md`). Disparado pelo desejo do usuário de consultar/comparar preços por mensagem de texto em vez de CLI — "interface de linha de comando é pra desenvolvimento, é pra outro tipo de usuário". Este documento fecha requisitos; nenhuma arquitetura de código foi decidida aqui (isso é `/sc:design`).
>
> **Segunda rodada, mesmo dia (`/sc:brainstorm`)**: o usuário levantou a lacuna que a primeira rodada não cobriu — como a mensagem em texto livre vira uma ação do Julius, e a preocupação de segurança de "não quero que qualquer pessoa que converse com o chat consiga executar o que quiser no meu computador e na minha rede doméstica". §0 (F9–F12) e §2 (RF6–RF9) registram o que foi decidido.

## 0. Fatos e decisões já fechadas

| # | Fato/decisão | Origem |
|---|---|---|
| F1 | **Telegram**, não WhatsApp. WhatsApp exige verificação de negócio para sair do limite de 250 conversas/24h, cobra por conversa acima de 1000/mês, e a Meta baniu assistentes de IA de terceiros da própria Business API em jan/2026 — risco direto para um sistema que já usa `deepseek-flash` na curadoria. Automação não-oficial do WhatsApp roda no número pessoal do usuário e tem histórico medido de detecção em 2–8 semanas. | `/sc:research` 17/09 |
| F2 | **BotFather** é a ferramenta oficial do Telegram pra criar o bot: `/newbot`, escolhe nome e `username` terminado em `bot`, recebe o token na hora. Ele cria só a identidade do bot (nome, username, comandos do autocomplete) — a lógica de resposta continua sendo código do Julius. | `/sc:brainstorm` 17/09, confirmado por pesquisa |
| F3 | **Long polling (`getUpdates`) não tem o atraso que o usuário temia.** O Telegram segura a conexão HTTP aberta (parâmetro `timeout`, tipicamente 30s) e responde **na hora** (sub-segundo, medido) assim que uma mensagem chega; o timeout só é atingido quando não há mensagem nenhuma, e nesse caso o bot reabre a conexão sem intervalo perceptível. Não existe, neste volume de uso, diferença de latência real entre polling e webhook. | `/sc:brainstorm` 17/09 |
| F4 | Por causa de F3, **webhook e túnel (ngrok/Cloudflare Tunnel/Tailscale Funnel) não têm motivo técnico aqui** — decisão do usuário: só long polling, sem domínio, sem certificado, sem porta exposta. | Resposta do usuário, `/sc:brainstorm` 17/09 |
| F5 | O bot vai rodar num **computador extra em casa**, **diferente** da máquina de desenvolvimento atual, que **liga/desliga conforme o uso** (não é servidor 24/7). O usuário aceita que o bot fique indisponível quando essa máquina estiver desligada, sem qualquer aviso do lado do Telegram. | Resposta do usuário, `/sc:brainstorm` 17/09 |
| F6 | Os dados das duas máquinas **são e continuarão independentes** — não há requisito de sincronizar `prices.db`/`entrada/` entre a máquina de desenvolvimento e a de deploy. Quando o setup for feito na máquina de deploy, o usuário vai reimportar os 6 HTMLs reais que já tem, criando ali um banco próprio, do zero. | Resposta do usuário, `/sc:brainstorm` 17/09 |
| F7 | O bot deve consumir a camada `services/*` do Julius **no mesmo processo Python**, exatamente como `cli/*` já faz — nunca via `subprocess` do `julius` instalado (pagaria custo de start de processo e desfaria formatação pensada pra terminal, quando a função Python por trás já devolve dado estruturado). | `/sc:research` 17/09 |
| F8 | Um bot do Telegram é alcançável por qualquer pessoa que souber o `@username` — a API não restringe remetente. Como o Julius guarda histórico de compras de uma pessoa só, é necessário checar o `chat_id` de quem escreve contra uma allowlist de um único ID antes de responder qualquer coisa. | `/sc:research` 17/09 |
| F9 | O que o usuário descreveu leigamente ("apresentar os comandos pra IA e pedir pra ela escolher") é o padrão conhecido como **function calling / tool use**. O DeepSeek suporta isso nativamente (parâmetro `tools`, formato compatível com OpenAI) nos modelos V3/V4-flash — falta confirmar com um teste real se o `deepseek-flash` já configurado no Julius se comporta bem com `tools` (mesma disciplina do smoke test que revelou a pegadinha do `thinking` ligado). | `/sc:brainstorm` 17/09, pesquisa |
| F10 | **A IA nunca executa a ação — ela só propõe.** O fluxo é: a IA devolve "quero chamar a função X com esses argumentos"; o código do bot recebe essa proposta, valida, e só então roda a função de verdade contra `services/*`. O "menu" de ações é uma allowlist fechada, definida no código — nunca uma capacidade genérica de "executar comando" ou acessar shell/rede/sistema de arquivos. | Pesquisa (docs do DeepSeek + práticas de tool-calling) |
| F11 | **Prompt injection é um risco real e documentado** em sistemas de tool-calling: texto pode tentar convencer o modelo a chamar uma função diferente da pretendida. A mitigação de mercado é tratar toda entrada como não confiável e nunca expor uma ação poderosa demais — o que F10 já impõe aqui. Consequência direta: o `chat_id` de quem está falando **nunca** pode ser um argumento que a IA lê/gera — tem que vir do transporte (Telegram), senão a allowlist de segurança (F8) perde efeito. | Pesquisa |
| F12 | O próprio Julius já é "seguro por padrão" para esse uso: nenhuma ação hoje exposta via `services/*` apaga preço, e fusão de produto é reversível (`produtos desfundir`) desde a v2.4. Um erro de interpretação da IA tem teto conhecido, mesmo sem essa allowlist ser nova. | `CLAUDE.md` (fusão reversível, v2.4) |

## 1. Objetivo

Permitir consultar e comparar preços já guardados pelo Julius por mensagem de texto no Telegram, sem custo de infraestrutura, rodando num computador doméstico de uso intermitente — sem abrir porta nenhuma e sem expandir a superfície de rede do sistema.

## 2. Requisitos funcionais

| # | Requisito |
|---|---|
| RF1 | O bot deve responder, por mensagem em texto livre no Telegram, tanto a ações de **leitura** (no mínimo `consultar`, `mercados comparar`) quanto de **escrita reversível** já existentes no Julius (`renomear` produto/mercado, `tag`, `definir-conteudo`, `fundir`/`desfundir`). Toda mensagem é roteada por IA (RF6) — não há vocabulário de slash-command fixo a decorar. |
| RF2 | O bot só processa e responde mensagens vindas do `chat_id` do próprio usuário (F8); mensagem de qualquer outro remetente é ignorada ou recusada, nunca respondida com dado do catálogo nem chega a ser roteada pela IA (F11). |
| RF3 | O processo do bot conecta ao Telegram exclusivamente via long polling (`getUpdates`, F3/F4); nenhum endpoint HTTP é exposto pelo sistema, nenhuma porta aberta. |
| RF4 | O bot é registrado via BotFather (F2); o token recebido nunca é commitado no repositório — mesma disciplina que `JULIUS_AI_API_KEY` já segue hoje (variável de ambiente). |
| RF5 | O bot lê e grava no `prices.db`/`entrada/` locais à própria máquina onde ele roda (F6) — sem lógica de sincronização com outra máquina. |
| RF6 | Toda mensagem de texto do usuário autorizado (RF2) é enviada à IA junto com o catálogo fechado de ações disponíveis (function calling, F9/F10); a IA responde propondo qual ação chamar e com quais argumentos — nunca executa nada diretamente. |
| RF7 | O código do bot valida a proposta da IA (produto/mercado referenciado existe, argumentos têm o tipo esperado) antes de executar qualquer ação contra `services/*` — a validação é sempre no código, nunca delegada à IA (F10). |
| RF8 | Ação de **leitura** é executada e respondida imediatamente. Ação de **escrita** exige uma mensagem de confirmação prévia — mostrando a ação entendida e os argumentos resolvidos (ex.: "Vou fundir Tomate Italiano (23) com Tomate União (7) — confirma?") — e só executa após resposta afirmativa explícita do usuário. |
| RF9 | O `chat_id` usado para checar a allowlist (RF2) vem sempre do transporte (Telegram), nunca de um campo que a IA preenche ou lê da mensagem (F11). |

## 3. Requisitos não funcionais

| # | Requisito |
|---|---|
| RNF1 | Custo de infraestrutura zero: sem VPS, sem domínio, sem assinatura de túnel (F1, F4, F5 já convergem pra isso). |
| RNF2 | Nenhuma porta de rede aberta, nenhum certificado TLS para manter (F4). |
| RNF3 | Indisponibilidade é aceita quando a máquina hospedeira está desligada — sem SLA, sem fallback, sem notificação de "bot offline" (F5). |
| RNF4 | **Decisão explícita nesta rodada**: toda mensagem do bot chama IA para rotear a ação (RF6), o que passa a competir pelo mesmo `JULIUS_AI_BUDGET_USD` hoje dedicado à curadoria de catálogo — contraria o princípio de "IA só em pontos de baixa frequência" por escolha consciente do usuário, não por descuido. Estimativa (não medição — o volume real só existirá com uso): rodadas de curadoria com dezenas de produtos custaram centavos de dólar no banco real; uma mensagem de roteamento usa uma fração desses tokens, mas confirmar que o orçamento de US$5/mês aguenta o volume de uso real do bot fica para acompanhar depois de implementado, mesma disciplina do `ai_calls.jsonl`. |
| RNF5 | O menu de ações (tools) exposto à IA é uma allowlist fechada, definida no código do bot — nunca uma ação genérica de "executar comando" ou acesso a shell/rede/sistema de arquivos além do que `services/*` já expõe hoje (F10, F11). |

## 4. Critérios de aceite (exemplos)

- Mandando "banana tá cara?" pro bot no Telegram, a IA propõe chamar a ação de consulta, o bot executa e a resposta traz o mesmo dado que `julius consultar banana` traz na CLI, em formato de texto — sem confirmação prévia (é leitura).
- Mandando "funde o tomate italiano com o tomate união" (ou pedido equivalente de escrita), o bot responde mostrando a ação e os IDs/nomes que entendeu e só executa `merge_products` depois de uma resposta afirmativa explícita.
- Mandando qualquer mensagem de um `chat_id` que não é o do usuário, o bot não devolve nenhum dado do catálogo e não chama a IA para essa mensagem.
- Com a máquina de casa desligada, mensagens ficam sem resposta — nenhum comportamento de erro visível é esperado além do silêncio.
- Ao fazer o setup do bot na máquina de deploy, o usuário reimporta os HTMLs reais e o catálogo nasce vazio ali, independente do que existe na máquina de desenvolvimento.

## 5. Fora do escopo deste documento (perguntas para `/sc:design`)

- **Biblioteca**: `python-telegram-bot` (síncrona, mais parecida com o resto do código — o Julius hoje não usa `asyncio` em lugar nenhum) vs. `aiogram` (assíncrona). A pesquisa aponta a primeira como encaixe mais natural, mas não é decisão travada aqui.
- **Como o processo inicia** quando a máquina liga — como não há requisito de disponibilidade 24/7 (RNF3), início manual pode bastar até incomodar; automatizar (`systemd --user` com lingering, autostart) é decisão de design, não requisito.
- **Foto do recibo/QR code via Telegram** — já registrado como evolução futura no `CLAUDE.md` ("Canal de entrega" + "Foto do QR Code"/"Foto do recibo impresso"); esta integração de mensageria é exatamente o canal que faltava, mas decidir se entra nesta rodada ou fica para depois é decisão separada.
- **Onde o código do bot mora na árvore do projeto** — herda de F7 que ele é um consumidor de `services/*` na mesma camada (L4) que `cli/`, mas o layout exato (`julius/bot/`, módulo novo, etc.) é decisão de design.
- **Schema exato das tools**: quais funções de `services/catalog.py`/`search.py`/`comparison.py` entram no menu (RNF5), o JSON schema de argumentos de cada uma, e o texto do prompt de sistema que descreve as ações à IA — tudo isso é design/implementação, não requisito.
- **Modelagem do estado de "confirmação pendente"** (RF8): como o bot lembra, entre uma mensagem e a resposta "sim" do usuário, qual ação e argumentos estavam propostos — é modelagem de conversa, decisão de design.
- **Validar com teste real** se `deepseek-flash` (o modelo já configurado) tem o mesmo comportamento de tool-calling documentado para a família V3/V4-flash (F9), e se a mesma pegadinha do `thinking` ligado (já registrada no `CLAUDE.md`) se repete aqui — é validação técnica da implementação, não requisito.
