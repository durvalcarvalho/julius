# Requisitos: quem não é de confiança só consulta, nunca escreve

> Descoberta via `/sc:brainstorm`, 2026-09-20, na sequência direta da sessão anterior (mesmo dia): o bot deixou de responder só ao dono (`JULIUS_BOT_ALLOWED_CHAT_ID`) e passou a aceitar qualquer `chat_id`, com `JULIUS_BOT_UNLIMITED_CHAT_IDS` marcando quem não tem cota por hora e todo o resto caindo em `JULIUS_BOT_RATE_LIMIT_PER_HOUR` mensagens/hora (`julius/bot/app.py::_gate`). Nessa mesma conversa o usuário levantou o próximo problema, na hora: "sem deixar a porta escancarada aberta pra eles fazerem o que quiser" — e junto trouxe uma ideia maior, de médio/longo prazo, sobre uma rede de preços compartilhada entre várias pessoas. As duas foram deliberadamente separadas nesta sessão (ver "Fora de escopo" no fim).

## Causa raiz — o que já existe e por que não basta

`_gate` (`julius/bot/app.py`) resolve **quantas mensagens por hora**, não **o que a mensagem pode fazer**. Um `chat_id` estranho, dentro da própria cota gratuita, chega ao mesmo agente (`bot/agent.py`) com o mesmo menu fechado de ações que o dono usa — hoje **5 de leitura** (`search_prices`, `compare_stores`, `check_price`, `list_products`, `list_stores`) e **10 de escrita** (`rename_product`, `rename_store`, `tag_product`, `untag_product`, `set_product_kind`, `clear_product_kind`, `set_product_content`, `clear_product_content`, `merge_products`, `unmerge_product`, todas em `julius/bot/actions.py`). Se a IA escolher uma ação de escrita, o próprio estranho recebe o botão "✅ Confirmar" e pode gravar no banco pessoal do dono — a única barreira que existe hoje é ele *querer* apertar o botão, não uma checagem de quem ele é. A sessão anterior resolveu volume; não resolveu **o quê**.

## Objetivo esclarecido (decisões já tomadas nesta sessão, com o usuário)

1. **Escopo desta especificação — só leitura × escrita.** A ideia de rede de preços compartilhada entre pessoas fica registrada como direção futura (seção própria no fim), sem requisito funcional aqui.
2. **Um papel só, derivado da lista que já existe.** Não nasce uma terceira variável de ambiente: `chat_id` em `unlimited_chat_ids` (dono + `JULIUS_BOT_UNLIMITED_CHAT_IDS`) pode ler e escrever, exatamente como hoje; qualquer outro `chat_id` — mesmo dentro da própria cota de mensagens — só lê. "Sem limite de mensagens" e "pode escrever" são a mesma coisa, de propósito: confiança é binária aqui, não uma matriz de combinações.
3. **Leitura nunca muda.** As 5 ações de leitura de hoje continuam abertas pra qualquer `chat_id` (sujeitas só ao rate limit já existente) — é o que faz "deixar as pessoas testarem" continuar valendo a pena mesmo fechando a escrita.
4. **A recusa fala na voz do Julius**, não com uma mensagem crua de sistema tipo "ação negada" — mesma persona que já narra todo o resto do bot.
5. **A tentativa fica registrada** para o dono — sinal de quem está usando de verdade e pode merecer virar `unlimited` (não é comando de analytics novo; é log, no mesmo espírito do `log.info` que já existe pra rate limit).

## Requisitos funcionais

**RF1 — o papel de quem escreve para de ser "todo mundo" e passa a ser `chat.id in settings.unlimited_chat_ids`.** Hoje toda ação de escrita está disponível pra qualquer `chat_id` que chegue à IA; passa a estar disponível só pra quem já é considerado confiável pela lista existente (dono + `JULIUS_BOT_UNLIMITED_CHAT_IDS`). Nenhuma lista nova.

**RF2 — quem não está na lista nunca chega a ver o teclado de confirmar/cancelar.** Quando a IA escolhe uma das 10 ações de escrita para um `chat_id` fora de `unlimited_chat_ids`, o bot não computa nem envia o `PendingWrite`/`InlineKeyboardMarkup` — a resposta é uma recusa, sem pré-visualização de "vai virar X" alguma (evita até mostrar, de relance, dado do catálogo que essa pessoa não devia enxergar formatado como uma mudança pendente).

**RF3 — as 5 ações de leitura continuam idênticas para qualquer `chat_id`.** Nenhuma mudança de comportamento, texto ou narração para `search_prices`, `compare_stores`, `check_price`, `list_products`, `list_stores` — a única porta que fecha é a de escrita.

**RF4 — a recusa é narrada, não uma string de sistema solta.** Usa a mesma voz (persona Julius) que o resto do bot já fala, coerente com o tom de todas as outras respostas — não é um erro técnico, é o personagem dizendo que essa parte não é aberta pra quem pediu.

**RF5 — toda tentativa de escrita bloqueada vira uma linha de log identificável** (no mínimo: `chat_id`, qual ação a IA tinha escolhido, quando). É o dado que permite ao dono decidir, olhando o log como já faz hoje, se algum `chat_id` merece ser promovido para `JULIUS_BOT_UNLIMITED_CHAT_IDS`.

**RF6 — quem já está em `unlimited_chat_ids` não percebe nenhuma mudança.** Dono e amigos de confiança continuam com leitura e escrita exatamente como hoje, sem esse gate interferindo.

## Requisitos não funcionais

**RNF1 — zero configuração nova.** A regra usa a variável que a sessão anterior já criou (`JULIUS_BOT_UNLIMITED_CHAT_IDS` + `JULIUS_BOT_ALLOWED_CHAT_ID`); não introduz uma terceira lista nem um novo formato de env var.

**RNF2 — a checagem de papel é independente da checagem de cota.** Rate limit (quantidade de mensagens) e papel (pode escrever ou não) continuam sendo duas perguntas diferentes internamente, mesmo que a resposta de "quem" seja a mesma lista hoje — se um dia divergirem (ver questão aberta 1), a separação já precisa existir no código pra não virar retrabalho.

**RNF3 — não reabre a guarda de honestidade da v2.12.** A recusa não pode alegar um motivo que não é verdade (ex.: fingir erro de rede) nem confirmar/negar implicitamente algo sobre o estado do banco que o solicitante não tinha por que saber — é uma recusa de permissão, não um relato de falha técnica.

**RNF4 — nenhum custo de IA extra por recusa.** Bloquear um estranho abusando não pode consumir chamada de IA nova por tentativa — mesma disciplina de sempre neste projeto (orçamento é o que protege contra abuso de custo).

## Histórias de usuário

- **Como dono**, quero que qualquer pessoa testando o bot possa perguntar preço e comparar mercados, mas não consiga renomear, fundir ou apagar categoria do meu catálogo sem eu ter decidido confiar nela antes.
- **Como amigo de um amigo testando o bot**, quando peço pra corrigir um nome errado e não posso, quero entender que é por permissão (e como resolver isso), não achar que o bot travou ou ignorou meu pedido.
- **Como dono**, quero ver no log quem tentou escrever e o que tentou, pra decidir se coloco esse `chat_id` na lista de confiança.

## Critérios de aceite (rascunho, para o `/sc:design` refinar)

- Um `chat_id` fora de `unlimited_chat_ids` nunca recebe um teclado de confirmar/cancelar, em nenhuma das 10 ações de escrita.
- O mesmo `chat_id`, pedindo qualquer uma das 5 ações de leitura, recebe resposta idêntica à de hoje.
- Cada tentativa de escrita bloqueada aparece no log com `chat_id` e a ação que seria executada.
- Um `chat_id` em `unlimited_chat_ids` não tem nenhuma mudança de comportamento observável antes/depois desta mudança.
- A mensagem de recusa não é uma string crua de erro — passa pela mesma narração de personagem do resto do bot.

## Questões em aberto para a próxima fase (`/sc:design`)

1. **Papel e cota são a mesma lista hoje, mas o código deveria tratá-los como dois conceitos, não um só?** Combinado nesta sessão como "mesma lista" por simplicidade — mas se no futuro você quiser alguém com escrita liberada e cota baixa (ou o oposto: um grupo grande com leitura ilimitada e sem escrita), o design precisa decidir se separa as duas checagens agora (custo baixo) ou só quando o caso real aparecer (YAGNI, no estilo já adotado no resto do projeto).
2. **Onde exatamente interceptar, dentro de `bot/turn.py`/`bot/agent.py`.** Antes de a IA escolher a ação (o modelo nem vê as 10 ferramentas de escrita como opção) ou depois de escolhida, mas antes de virar `PendingWrite`? A primeira evita qualquer chance de a IA "insistir" numa ação inexistente; a segunda é mais simples de implementar em cima do que já existe. Decisão de design, não resolvida aqui.
3. **Texto exato da recusa e se ela custa uma chamada de narração (IA) ou é uma frase fixa sem IA**, dado o RNF4 (não gastar orçamento com abuso). Se for fixa, precisa decidir se soa "na voz do Julius" mesmo sem passar pelo prompt `persona`.
4. **O que logar além de `chat_id` + ação** — argumentos da tentativa (ex.: "queria renomear a loja X pra Y") ajudam a decidir se promove a pessoa, mas também guardam mais dado de quem não é confiável ainda; até onde vale detalhar.
5. **Confirmar que a lista de 5 leituras / 10 escritas é exaustiva** — nenhuma ação nova deveria ser criada nem dividida só para caber nesta regra; a expectativa é que o gate seja transversal (checa a categoria da ação escolhida), não uma lista mantida à mão em paralelo às 15 ferramentas do agente.

## Fora de escopo (registrado, não especificado): a rede de preços compartilhada

O usuário também trouxe, na mesma conversa, uma ideia maior: várias pessoas contribuindo pro mesmo catálogo de preços — "um Waze de preço de mercado" — em vez de cada um ter sua memória isolada. Perguntado se isso significa dado compartilhado (um catálogo só, todo mundo vê/contribui) ou histórico privado com agregado comparável, a resposta foi **dado compartilhado, um catálogo só**. Isso não vira requisito nesta sessão porque contradiz suposições estruturais que o projeto inteiro carrega até aqui — vale registrar quais, pra quando a ideia for retomada:

- O projeto é declaradamente pessoal desde a primeira linha do design ("não é uma ferramenta de comparação entre mercados em geral") — um catálogo só, sem conceito de dono por linha (`prices`/`products`/`stores` não têm coluna de usuário).
- A curadoria (nome legível, tipo, conteúdo, fusão) é feita por IA **com confirmação de uma pessoa só** — todo o histórico deste projeto (`Alho`↔`Pão de Alho`, `Filme PVC`→`30 UN`, os três fracassos de auto-relato de confiança da IA) mostra que confiar em julgamento automático sem revisão humana já falhou várias vezes **com um curador só, de boa-fé**. Um catálogo alimentado por várias pessoas desconhecidas multiplica esse risco (preço errado de propósito ou por engano, produto "fundido" errado por alguém sem contexto).
- O orçamento de IA (`ai_usage`, US$5/mês) e o rate limit recém-criado assumem um só "dono" pagando a conta; uma rede com contribuição de terceiros levanta a pergunta de quem paga a curadoria do que os outros escrevem.
- CNPJ/mercado hoje é uma tabela sem noção de região além do endereço; uma rede de preços faz sentido comparar só entre pessoas fisicamente próximas (preço de Brasília não compara com o de outra cidade), o que é uma dimensão nova que não existe em nenhuma parte do schema atual.

Nenhuma dessas objeções é "não fazer" — são exatamente o tipo de pergunta que motivou perguntar antes de especificar. Fica como ponto de partida para um `/sc:brainstorm` dedicado no futuro, não como bloqueio.

## Próximo passo

`/sc:design` para decidir o ponto de interceptação (questão 2) e o texto/custo da recusa (questão 3) — as duas coisas que realmente mudam a implementação. Nada foi implementado nesta sessão.
