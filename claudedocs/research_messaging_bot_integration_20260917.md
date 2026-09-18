# Pesquisa — Julius num app de mensageria (Telegram vs WhatsApp, arquitetura do "servidor", hospedagem)

Data: 2026-09-17. Escopo: brainstorm do usuário sobre tirar o Julius da CLI e colocá-lo atrás de um bot de mensageria. Três perguntas feitas: (1) Telegram ou WhatsApp, (2) como desenhar o componente que recebe a mensagem, fala com o Julius e responde, (3) onde hospedar isso. Relatório de pesquisa — nenhum código foi escrito, nenhuma decisão de arquitetura foi tomada aqui.

## Resumo executivo

1. **Telegram**, sem disputa para este caso. WhatsApp exige verificação de negócio (documento de empresa) para sair do limite de 250 conversas/24h, cobra por conversa acima de 1000/mês, e a Meta baniu explicitamente assistentes de IA de terceiros da Business API em janeiro/2026 — o próprio caso de uso do Julius (curadoria via `deepseek-flash`) fica em risco regulatório se um dia o "responder pergunta" usar IA no caminho do bot. Automação não-oficial do WhatsApp (`whatsapp-web.js`, Selenium) roda no número pessoal do usuário e tem histórico medido de detecção em 2–8 semanas — trocaria "ferramenta pessoal" por "risco de perder a conta do WhatsApp".
2. **Long polling, não webhook.** Webhook exige domínio próprio, certificado TLS válido e uma porta exposta à internet — infraestrutura nova para um bot de uso pessoal. Polling é só o processo abrindo conexões de saída para a API do Telegram, mesmo padrão que o Julius já segue para a IA (`urllib.request` de saída, nunca um servidor escutando).
3. **O bot é um consumidor da camada `services/`, exatamente como `cli/` já é** — nunca subprocess do `julius` instalado, nunca reimplementação de lógica. Isso é a mesma DAG de camadas que já existe (`cli` e o futuro "bot" convivem em L4, os dois só chamam `services`).
4. **Achado que muda a pergunta de hospedagem**: `prices.db` e o fluxo de `importar` hoje vivem só na máquina do usuário. Rodar o bot ali mesmo (polling, sem porta aberta, `systemd --user`) custa **zero infraestrutura nova e zero dinheiro**. Só vale considerar VPS se o requisito for "consultar de qualquer lugar mesmo com a máquina de casa desligada" — e aí o banco (ou o processo de importar) precisa se mudar junto, o que é uma decisão maior que hospedar um bot.

## 1. Telegram vs WhatsApp

| Critério | Telegram Bot API | WhatsApp (Cloud API oficial, Meta) | WhatsApp (não-oficial) |
|---|---|---|---|
| Setup | Fala com `@BotFather`, recebe token em menos de 1 minuto. Sem aprovação, sem revisão. | Conta de desenvolvedor Meta, WhatsApp Business Account, número dedicado que nunca foi usado no WhatsApp normal, verificação de negócio (documento) para destravar limites acima de 250 conversas/24h — processo de 2h a 2 semanas. | `whatsapp-web.js`/Selenium controlando o WhatsApp Web via navegador headless, no número pessoal do usuário. |
| Custo | Gratuito, sem limite de mensagens, sem mensalidade. | 1000 conversas de serviço grátis/mês; acima disso, cobrança por conversa via um Business Solution Provider (Twilio, 360dialog etc.) que ainda cobra mensalidade própria em cima do preço da Meta. | Gratuito, mas ver risco abaixo. |
| Restrição de conteúdo | Aberta a qualquer uso que não seja spam/ilegal. | Meta proibiu explicitamente assistentes de IA de terceiros (incluindo integrações tipo ChatGPT/Copilot) na Business API a partir de 15/01/2026 — risco direto para um bot que expõe curadoria via LLM. | Nenhuma política formal — está fora do sistema oficial. |
| Risco de perder a conta | Nenhum — bot é uma entidade separada da conta pessoal. | Nenhum, é o canal oficial. | Alto: uso de fingerprint de dispositivo, análise comportamental e detecção de mensagens sem resposta; ferramentas desse tipo têm histórico medido de detecção em 2–8 semanas, e o risco recai sobre o número de WhatsApp pessoal do usuário. |
| Biblioteca Python madura | `python-telegram-bot` (síncrono) e `aiogram` (assíncrono), ambas maduras e bem documentadas. | Requer HTTP direto contra a Graph API ou um SDK de terceiro; mais peças em série (Meta + BSP). | `pywhatkit`, wrappers sobre Selenium — nenhuma é uma "biblioteca de API", são automações de UI. |

**Conclusão**: para uma ferramenta pessoal de um usuário só, Telegram resolve com uma fração do atrito e sem custo recorrente. WhatsApp só faria sentido se o Julius um dia virasse produto para terceiros (múltiplos usuários, necessidade de credibilidade de canal "oficial") — não é o caso hoje.

## 2. Arquitetura do "Julius server"

### 2.1 Webhook vs long polling

- **Webhook**: o Telegram faz um POST HTTPS para uma URL sua a cada mensagem nova. Exige domínio, certificado TLS válido, porta exposta — vantagem real só em latência e em escala (não é o caso de um usuário só mandando algumas mensagens por dia).
- **Long polling**: o processo do bot pergunta ativamente ao Telegram "tem mensagem nova?" em loop, sem precisar de porta aberta nem IP público. É o modo recomendado para desenvolvimento e para deployments que não têm infraestrutura de rede dedicada.
- Ambas as bibliotecas Python (`python-telegram-bot`, `aiogram`) suportam os dois modos com a mesma base de código — trocar depois, se algum dia fizer sentido, não é reescrita.

**Por que polling é a escolha aqui, não só "a mais simples"**: o Julius já tem um princípio de design registrado no `CLAUDE.md` — nunca construir infraestrutura proporcional a um problema que não existe (é o mesmo raciocínio que rejeitou FTS5, embeddings, e "2–3 APIs em paralelo" para o CNPJ). Webhook resolveria um problema de escala que uma ferramenta de um usuário não tem, ao custo de expor uma porta e manter um certificado — superfície de ataque nova para zero ganho real.

### 2.2 Como o bot fala com o Julius

O código do Julius já separa "caso de uso" (`services/*`, devolve dados, nunca imprime) de "interface" (`cli/*`, só chama `services` e formata). Um bot de mensageria é **outra interface na mesma camada L4** — importa os mesmos `services.search.search_prices`, `services.comparison.compare_stores` etc., dentro do mesmo processo Python, e formata a resposta como texto para o Telegram em vez de tabela `rich`.

A alternativa rejeitada é o bot invocar `subprocess` chamando o `julius` instalado via pipx e fazer parsing da saída formatada em `rich` — isso pagaria o custo de start de processo a cada mensagem e exigiria desfazer uma formatação pensada para terminal, quando a função Python por trás já devolve dados estruturados. Mesma lógica que já vale para não ter uma "camada services chamando services": o bot depende de `services`, nunca de `cli`.

Isso implica autenticação de configuração igual à CLI — `Config` lido de variável de ambiente, sem banco separado, sem duplicar a lógica de conexão (`infra.db.connect`).

### 2.3 Tradução da mensagem em comando (fora do escopo desta pesquisa, registrado para o `/sc:design`)

Duas abordagens possíveis, sem decisão tomada aqui:
- **Comandos explícitos** (`/consultar banana`, `/comparar`) — Telegram já suporta autocomplete nativo de slash-commands, zero ambiguidade, zero custo de IA.
- **Linguagem natural roteada por IA** — o Julius já paga por chamadas de IA (`deepseek-flash`, orçamento US$5/mês); rotear toda mensagem do bot por IA competiria com esse orçamento e contradiria o princípio já registrado de "IA só em pontos de baixa frequência, nunca no caminho de leitura corriqueiro" (hoje aplicado a `consultar`).

### 2.4 Onde mora o estado — o achado que mais pesa na decisão de hospedagem

`prices.db`, `entrada/` e o fluxo de `julius importar` vivem hoje exclusivamente em `~/.local/share/julius/` na máquina do usuário. Um bot hospedado em outro lugar (VPS, nuvem) **não tem acesso a esse banco** a menos que:
- o banco (ou uma cópia sincronizada) more no mesmo lugar que o bot, ou
- o fluxo de importar HTML também se mude para lá (o que muda como o usuário salva os recibos hoje).

Isso não é um detalhe de deploy — é uma decisão de arquitetura que a pergunta "onde hospedar" não pode responder sozinha, porque hospedar o bot em outro lugar sem mover o banco quebra a ferramenta.

## 3. Hospedagem — opções medidas

| Opção | Custo | Observação |
|---|---|---|
| **Na própria máquina do usuário**, como serviço (`systemd --user`), long polling | **US$0** | Banco e `entrada/` já estão lá — zero mudança de dado. Só sai do ar se a máquina desligar; para um bot pessoal, aceitável e reversível (é só religar). |
| VPS pequeno (Hetzner, ~US$4–5/mês) | ~US$5/mês | Só se "consultar de qualquer lugar mesmo com a máquina de casa desligada" for requisito real — implica mover ou sincronizar `prices.db`/`entrada/` para lá. |
| Fly.io / Railway | ~US$4–6/mês na prática (o "grátis para sempre" das duas mudou para modelo de trial/uso em 2026) | Mesma ressalva de estado do VPS; menos controle que uma VPS pura. |
| Oracle Cloud Free Tier | US$0 "para sempre" | Free tier generoso (4 OCPU/24GB), mas a Oracle é conhecida por reclamar instâncias ociosas — exigiria um heartbeat artificial para não perder a máquina. Ganho de custo vem com esse atrito. |

**Recomendação**: começar pela própria máquina do usuário. É a opção que não exige nenhuma decisão sobre onde o banco mora, não custa nada, e não expõe porta nenhuma à internet (polling é só conexão de saída). Migrar para VPS é um passo separado e só se justifica quando "acesso de qualquer lugar, 24/7, independente da máquina de casa" virar necessidade — nesse momento a pergunta real não é mais "onde hospedar o bot", é "onde o banco mora agora".

## Achado de segurança a registrar (não é escopo do `/sc:design`, mas não pode ser esquecido lá)

Um bot do Telegram é alcançável por qualquer pessoa que souber o `@username` dele — a API não restringe quem manda mensagem. Como o Julius guarda histórico de compras de uma pessoa só, o bot precisa checar o `chat_id` de quem escreve contra uma allowlist de um único ID (o do próprio usuário) antes de responder qualquer coisa. Isso é código trivial (uma comparação, sem biblioteca), mas é fácil esquecer porque a CLI nunca teve esse problema (só roda na máquina do usuário).

## Fora do escopo desta pesquisa

Layout exato dos comandos do bot, ligação com a "foto do recibo/QR code" já registrada como evolução futura no `CLAUDE.md` (o bot é exatamente o "canal de entrega" que faltava para aquela ideia, mas decidir a costura é `/sc:design`), formato da allowlist/autenticação, biblioteca final entre `python-telegram-bot` e `aiogram` (ambas resolvem; `python-telegram-bot` tem API síncrona mais parecida com o resto do Julius, que hoje não usa `asyncio` em lugar nenhum — mas isso é uma escolha de poucos minutos no dia do design, não uma pesquisa).

## Fontes

- [Telegram vs WhatsApp: Which Messaging API is Best for Business?](https://www.wati.io/en/blog/telegram-vs-whatsapp/)
- [Telegram vs WhatsApp for An AI Agent](https://www.hermify.io/en/blog/telegram-vs-whatsapp-for-ai-agent)
- [WhatsApp vs Telegram Inbound in 2026: Real Cost, Setup Time, and Compliance Compared](https://www.unifyport.ai/blog/whatsapp-vs-telegram-inbound-2026-cost-setup-comparison/)
- [WhatsApp API 2026: Types, Access, Pricing & Limits](https://www.unipile.com/whatsapp-api-a-complete-guide-to-integration/)
- [Pricing on the WhatsApp Business Platform | Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)
- [Do I Need the WhatsApp Business API? 2026 Readiness Checklist](https://blueticks.co/blog/do-i-need-whatsapp-business-api)
- [Meta bans third-party LLM chatbots in WhatsApp — GSMArena](https://www.gsmarena.com/meta_bans_thirdparty_llm_chatbots_in_whatsapp_-news-70460.php)
- [WhatsApp Bot Banned in 2026? 12 Fixes from 50+ Cases](https://achiya-automation.com/en/blog/whatsapp-spam-detection-2026/)
- [WhatsApp API vs. Unofficial Tools: A Complete Risk-Reward Analysis](https://www.bot.space/blog/whatsapp-api-vs-unofficial-tools-a-complete-risk-reward-analysis-for-2025)
- [Long-polling — aiogram documentation](https://docs.aiogram.dev/en/latest/dispatcher/long_polling.html)
- [Webhook — aiogram documentation](https://docs.aiogram.dev/en/latest/dispatcher/webhook.html)
- [Long Polling vs Webhook — How Telegram Bots Receive Updates | GramIO](https://gramio.dev/updates/webhook)
- [Long Polling vs. Webhooks | grammY](https://grammy.dev/guide/deployment-types)
- [python-telegram-bot vs aiogram — piptrends](https://piptrends.com/compare/python-telegram-bot-vs-aiogram)
- [aiogram — official site](https://aiogram.dev/)
- [Cheap VPS for AI Agents (2026): Specs, Costs & Best Hosts](https://www.hermify.io/en/blog/cheap-vps-for-ai-agent)
- [7 Fly.io Alternatives in 2026: Real Pricing After the Free Tier Died](https://expresstech.io/7-fly-io-alternatives-in-2026-real-pricing-after-the-free-tier-died/)
- [GitHub - Awesome-Web-Hosting-2026](https://github.com/iSoumyaDey/Awesome-Web-Hosting-2026)
