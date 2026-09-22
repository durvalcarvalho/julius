# Brainstorm: personalidade, fallback, contexto e CTA no bot (Julius)

> Status: **requisitos em discussão, nada implementado**. Documento de descoberta (`/sc:brainstorm`) — decide o quê e por quê, não o como. Confrontado linha a linha com o código real de `project-julius` em 2026-09-21, não só com a transcrição hipotética trazida no pedido.

## 0. Como este documento foi verificado

**Atualização de 2026-09-22, confirmada pelo usuário**: a conversa colada no pedido (batata "dinheiro de gente grande" → "quanto tempo de luz isso paga?" → coca → refrigerante) **é real**, aconteceu no Telegram — não uma ilustração. Isso eleva o Caso 2 ao mesmo padrão de evidência de toda outra rodada deste projeto (screenshot/log real, não hipótese), e retira o motivo (i) da objeção de tempo que este documento levantava no §8 original. A frase "sabe quanto tempo de luz isso paga?" também é, à parte, o exemplo de saída do próprio prompt `persona` (`julius/services/suggestions.py`, achado da rodada v2.7.1, citado em `CLAUDE.md`) — o que reforça a leitura do Caso 2: o usuário **ecoou de volta** um comentário retórico que o próprio Julius costuma soltar, e o roteador não tem instrução nenhuma pra reconhecer isso como referência à fala anterior dele mesmo, em vez de um produto novo.

Cada requisito abaixo foi checado contra:
- `julius/bot/agent.py` — `SYSTEM_PROMPT` (roteamento) e as duas guardas (`no_unlicensed_data_claims`, `no_write_without_permission`)
- `julius/services/suggestions.py` — `SYSTEM_PROMPTS["persona"]` (narração) e seu histórico de versões (v1→v6, com achados medidos)
- `julius/bot/render.py` — todas as `*_fallback_line`/`*_facts`, sem IA
- `julius/bot/actions.py` — as 14 ações existentes (4 leitura + 10 escrita)
- `CLAUDE.md` — 13 rodadas reais já medidas (v2.7 a v2.13) sobre exatamente este tema (voz, fallback, memória de conversa, CTA implícito)

## 1. O que já funciona (confirmado no código, não só na prosa do pedido)

- **Duas bolhas fato+opinião**: `bot/app.py::_chunks`/`_send` já quebram a resposta da persona em mensagens separadas por parágrafo (v2.8); o prompt `persona` já exige "informação primeiro, comentário depois" (`suggestions.py` linhas 203-216).
- **Veredito com 2+ mercados, nunca com 1 registro**: já implementado e testado (regra 3 do prompt `persona`).
- **Memória de curto prazo já existe, em algum grau**: `HISTORY_TURNS = 3` turnos inteiros de conversa vão pro modelo a cada mensagem (`bot/agent.py`), e o próprio `SYSTEM_PROMPT` já instrui "se sua última mensagem foi uma pergunta, trate a próxima como resposta a ela" e "junte o que foi mencionado nas últimas mensagens, não só na mais recente" (linhas 79-95). Ou seja: parte do Caso 3 (ligar duas perguntas parecidas) já é uma instrução existente — o que falta é medir se ela cobre o caso específico de "coca" → "refrigerante 2L", que é reconhecimento de **produto equivalente**, não só resposta a pergunta pendente.
- **"Tá caro?" com preço visto ao vivo já tem veredito sim/não com quantidade** (`check_price`, v2.11-v2.13) — o Caso 4 do pedido (preço muito diferente do último registrado) já é parcialmente coberto quando os dois preços já estão no catálogo: `records_facts`/`search_prices` já calculam e citam a diferença mais-barato-menos-mais-caro entre registros do mesmo produto (é literalmente o mesmo mecanismo do exemplo real de cebola em `CLAUDE.md`, v2.7.1). O que **não** existe é isso disparar a partir de um preço só **falado**, sem consulta — ver §3.

## 2. Tensão medida que o pedido contradiz — não aplicar sem decisão explícita

Duas descobertas do levantamento pesam mais que qualquer case novo:

**(a) O prompt `persona` hoje proíbe exatamente o CTA que o pedido pede sempre.** Linha 210-212 de `suggestions.py`:

> "Se um fato que você esperava não veio [...], não explique a ausência nem peça mais dados — comente só com o que tem."

Essa frase **não é descuido** — foi adicionada na v2 (`CLAUDE.md`, "Reprovado por medição") depois de o modelo, sem ela, soltar frases como "não veio nenhum preço nos fatos..." e quebrar o personagem; e reforçada na v2.7.1 como "achado qualitativo, sem métrica" (o hábito "explicativo" voltando em contextos sem preço). O pedido do usuário ("toda resposta sem dado devia terminar pedindo algo específico") é o **oposto** dessa regra medida. Isso pode estar certo — a régua de "explicar a ausência" e "pedir o dado que falta" são coisas diferentes, e é defensável que só a primeira tenha sido reprovada — mas não dá pra aplicar o Caso 1/6 do pedido sem reabrir essa decisão de propósito, com o motivo escrito, do jeito que este projeto já fez três vezes com confiança de IA (`CLAUDE.md`, "Auto-relato de confiança da IA falhou três vezes").

**(b) Não existe, em lugar nenhum do código, uma ação que grave um preço reportado por texto.** As 10 ações de escrita (`bot/actions.py::WRITE_ACTIONS`) são: renomear produto/mercado, tag/untag, tipo, conteúdo, fundir/desfundir. Nenhuma cria uma linha em `prices`. E `prices` tem `PRIMARY KEY (access_key, item_index)` — é modelada em torno de **um item de uma nota fiscal importada**, não de um preço solto que a pessoa digita no chat. Isso quer dizer que a frase que fecha os Casos 1, 3 e 6 do pedido —

> "Me diz o preço e o mercado que eu guardo pra próxima vez que alguém perguntar" / "Anotado. R$ 12 no Extra vira a referência agora"

— **hoje seria uma mentira do bot**, exatamente o tipo de coisa que a guarda `no_unlicensed_data_claims` existe pra impedir (v2.12, nasceu de um incidente real de o bot afirmar algo que não checou). Isso não é um ajuste de prompt: é uma **funcionalidade nova** — "registrar um preço avulso, sem nota fiscal, dito por texto" — com decisões de schema em aberto (fica em `prices` com uma chave sintética? vira uma tabela separada, `manual_prices`, que `search_prices`/`compare_stores` passam a unir? qual `access_key` finge existir?). Fica registrado como o requisito de maior custo deste documento (§4.1) e não deve ser confundido com "só reescrever a frase do fallback".

## 3. Catálogo de melhorias propostas — o que cada uma realmente é

| # | Do pedido | Tipo | Status hoje | Observação |
|---|---|---|---|---|
| 1 | Fallback de "sem preço" com voz, não texto neutro | prompt/texto | **parcial**: `no_match_fallback_line`/`search_fallback_line` (render.py) já têm alguma voz | **Decidido (2026-09-22): só voz, sem CTA.** Reescrever a frase com personagem é barato; pedir preço/mercado de volta fica fora, porque não há onde gravar isso e o preço avulso foi rejeitado (ver §4.1) |
| 2 | Reconhecer pergunta de brincadeira/eco do próprio comentário anterior | prompt (roteamento) | **gap real**: `SYSTEM_PROMPT` não tem regra nenhuma para "a pessoa está comentando minha fala anterior, não pedindo preço novo" | Ver §0 — é o achado mais concreto do documento; candidato barato (é só prompt) |
| 3 | Ligar duas perguntas parecidas em sequência (coca vs. refrigerante 2L) | prompt (roteamento + narração) | **parcial**: `HISTORY_TURNS=3` e a instrução de "juntar menções das últimas mensagens" já existem; não há instrução específica pra "isto pode ser o mesmo item que a pessoa acabou de perguntar, só outra embalagem" | Risco already-flagged no projeto: `match_kind`/resolução de produto já teve bug de desempate errado (tomate/passata, v2.11) — juntar "coca" e "coca 2L" é o mesmo tipo de risco, exige medição, não só instrução em prosa (ver `CLAUDE.md`, "só a instrução em prosa não bastou" na v2.8) |
| 4 | Comparar com preço muito diferente do último registrado | já existe quando os dois preços estão no catálogo | **feito** (records_facts) para busca; **feito** (check_price) para preço visto ao vivo | Não é uma feature nova — é garantir que a narração sempre cite a diferença quando ela existir, o que já é regra do prompt |
| 5 | Pergunta vaga ("tá caro?") aproveitar contexto | prompt (roteamento) | **parcial**: regra já existe para "sem preço dito → search_prices, nunca veredito seu" (linha 84-85), mas não cobre explicitamente "sem item nenhum dito, nem nas últimas mensagens" | Reforço pequeno de prompt: instruir pra perguntar o item quando nem a mensagem atual nem o histórico trouxerem um |
| 6 | Fechar o loop confirmando que o dado vai servir a alguém, não só "ok" | dependia de #4.1 | **descartado (2026-09-22)**: sem gravação de preço avulso, não existe loop nenhum pra fechar — não é mais um requisito | As confirmações de escrita reais que já existem (`render_result`/`WriteResult.summary`) já são específicas; não havia problema de fala aqui, só um requisito que deixou de fazer sentido |

## 4. Requisitos funcionais (a decidir, não a implementar ainda)

### 4.1 ~~[MAIOR] Registrar preço avulso por chat, sem nota fiscal~~ — REJEITADO (2026-09-22)
- **Decisão do usuário**: não construir. Um CTA prometendo "eu guardo" sem essa ação seria promessa vazia — e a resposta, confirmada por pergunta direta, foi não fazer a promessa, não construir a ação.
- Este item chegou a ganhar um desenho completo (`docs/design/manual-price-report.md`, tabela `manual_prices`, contrato de ação, fluxo) a partir de uma leitura errada de uma resposta ambígua — mantido pausado, não implementado, só como registro caso a decisão seja reaberta um dia com evidência nova (ver §9 para a correção completa).
- Consequência: os Casos 1, 3 e 6 do pedido original perdem a metade de "gravar o dado" — sobra só voz (ver §3, linha 1).

### 4.2 Regra de prompt para eco de comentário anterior (Caso 2)
- Instruir o roteador: se a mensagem da pessoa parece reagir/comentar a última fala do próprio bot (pergunta retórica, brincadeira) em vez de pedir preço de um item novo, responder em texto reconhecendo a piada, sem chamar `search_prices`.
- Risco a medir: como diferenciar "sabe quanto tempo de luz isso paga?" (eco) de "quanto custa uma conta de luz?" (pedido de preço de um item real, ainda que fora do catálogo) — são superficialmente parecidas.

### 4.3 Reforço de resolução de item ao ligar perguntas parecidas (Caso 3)
- Hoje `match_kind`/resolução de produto já erraram desempate uma vez em produção (v2.11). Antes de pedir ao modelo "note que isso pode ser o mesmo item em outra embalagem", medir se isso não reintroduz o mesmo tipo de falso-positivo (ex.: "guaraná" vs "guaraná zero" tratados como a mesma pergunta).

### 4.4 Reforço de prompt: pedir o item quando "tá caro?" não tem contexto nenhum (Caso 5)
- Menor risco dos quatro — é adicionar uma frase à regra que já existe (linha 84-85 do `SYSTEM_PROMPT`).

## 5. Requisitos não-funcionais

- **Nenhuma mudança de prompt entra sem o par exemplo-de-entrada/saída** — o próprio histórico do projeto registra que "só a instrução em prosa não bastou" mais de uma vez (v2.8, agrupamento de produtos).
- **Nenhuma reversão da regra "não explique a ausência" sem medição própria** — não herdar o pedido do usuário como veredito; ele é hipótese, a regra atual é medição (§2a).
- **Toda promessa que a fala do bot faz precisa ter uma ação real por trás** — é a mesma disciplina que gerou a guarda `no_unlicensed_data_claims` em v2.12; é exatamente por isso que §4.1 foi rejeitado em vez de "resolvido com prompt": sem a ação, a promessa seria falsa.
- **Orçamento de IA**: nenhuma das mudanças de §4.2-4.4 muda o volume de chamadas (mesmo ponto único de narração/roteamento).

## 6. Exploração ampliada — outras frentes do produto (além de personalidade/fallback)

O pedido original pediu "muitas features, melhorias novas" — as §§1-5 ficaram estritas ao tema personalidade/fallback/CTA. Esta seção alarga pra outras frentes do Julius, cruzadas com o que `CLAUDE.md` já registrou como testado, rejeitado por medição, ou deliberadamente adiado — pra não repropor sem evidência nova o que já foi reprovado.

### 6.1 Memória e proatividade

- **Estado explícito de pergunta pendente** (ex.: `PendingQuestion`, irmão de `PendingWrite`). Já foi cogitado e **adiado três vezes** (v2.10, v2.11, v2.13) — sempre pela mesma razão: medir o que os 3 turnos de histórico já resolvem antes de construir estado novo. As três rodadas deixaram escrito "se isso falhar no uso real, é o gatilho pra construir". **Pergunta**: já falhou, no uso real desde a v2.13? Se sim, isso deveria vir antes de qualquer feature nova de personalidade.
- **Alerta proativo de preço** ("Cebola que você compra sempre caiu pra R$ 5,90 no Costa Atacadao"): o bot passaria de puramente reativo (só responde quando perguntado) para também iniciar mensagem. Mudança de natureza, não de grau — hoje o `julius-bot` só reage a `Update`; um alerta exige um processo em background (cron/poll periódico) checando o catálogo e decidindo "vale avisar". Custo de decisão: que threshold dispara aviso, e não virar spam.
- **Lembrar preferência de mercado** ("você sempre compra tomate no Costa Atacadao — assumo isso quando não disser onde?"): reduziria perguntas, mas contraria o princípio atual de "nunca decide sozinho o que a pessoa quis dizer" — precisaria ser sempre uma sugestão confirmável, não um default silencioso.
- **Resumo periódico** (semana/mês: "você gastou X, Y% a mais que o mês passado, Z produtos subiram de preço"): é basicamente `mercados comparar` + `consultar` agregados por período, hoje só disponíveis por comando explícito na CLI — o trabalho novo seria decidir a cadência e se isso é puxado (`/resumo`) ou empurrado (mensagem automática, mesma questão do alerta proativo).

### 6.2 Entrada de dados (além de texto digitado)

- **Preço avulso por chat** — era o §4.1 deste documento; **rejeitado em 2026-09-22** (ver §9). Citado aqui só para não reaparecer como ideia nova sem lembrar que já foi decidido que não.
- **Foto do recibo/QR (OCR)**: já registrado em `CLAUDE.md` como "Evolução futura (não construir agora, sem prazo)" — pipeline totalmente diferente do parser de HTML (texto não estruturado, sujeito a erro de leitura), e decodificar o QR **não** resolve sozinho (a URL cai no mesmo captcha da Receita que já foi descartado). **Pergunta**: isso continua fora de prazo, ou virou prioridade?
- **Mensagem de voz do Telegram**: `python-telegram-bot` já recebe áudio; transcrição exigiria outro serviço (Whisper ou equivalente) — puramente novo, sem nenhuma base no código atual.
- **Importação automática por e-mail (IMAP)**: se os cupons chegam por e-mail em vez de link salvo manualmente, poderia varrer uma caixa de entrada — mas isso é uma segunda "fonte" de entrada, na mesma família de decisão que "Canal de entrega" em "Evolução futura" (transporte é ortogonal ao parsing).

### 6.3 Saída e relatórios

- **Exportar relatório em PDF/imagem** — hoje só existe `julius exportar` (CSV). Formatar bonito exigiria uma lib nova (ex. geração de PDF) — desproporcional se o uso real é só o bot conversacional.
- **Dashboard visual**: fora do espírito do produto ("memória de preços + decisão de compra", não uma ferramenta de BI) — mencionar só para descartar explicitamente, a menos que o usuário queira reabrir.

### 6.4 Multi-usuário / colaboração

- **Mais de um chat_id confiável** (ex.: cônjuge também reporta preço): hoje `JULIUS_BOT_ALLOWED_CHAT_ID` é um único id (v2.6, "Allowlist é o primeiro `if`"). Ampliar pra uma lista é uma mudança pequena de código, mas levanta uma pergunta de produto: preços reportados por pessoas diferentes têm a mesma confiança? Precisa registrar quem reportou o quê?

### 6.5 Qualidade da personalidade — variações e correção

- **Corrigir um valor dito por engano** ("na verdade foi R$ 14, não R$ 12"): hoje toda escrita tem `execute`/desfazer via comando explícito (`produtos desfundir`, etc.) — sem preço avulso (§4.1, rejeitado), este item fica sem objeto: não há valor de preço avulso pra corrigir.
- **Variar o humor por categoria** (ex.: mais impaciente com desperdício em carnes, mais econômico em limpeza): nenhuma base hoje — o character bible (`docs/requirements/julius-rock-persona.md`) não distingue por categoria. Baixo valor aparente sem pedido concreto do usuário; registrar só como ideia, não como requisito.

### 6.6 Itens já medidos e rejeitados — não repropor sem evidência nova

Estes já têm decisão tomada; citados aqui só para não reaparecerem como "novidade" sem perceber que já foram fechados:
- **Preço avulso por chat / CTA "eu guardo"** — rejeitado nesta rodada, 2026-09-22 (§4.1, §9). Decisão do usuário, não medição, mas mesmo peso: não reabrir sem ele pedir de novo, e desta vez confirmar a leitura antes de desenhar qualquer coisa.

Estes já têm decisão tomada e registrada em `CLAUDE.md`; citados aqui só para não reaparecerem como "novidade" sem perceber que já foram fechados:
- **Cache de respostas de IA** — rejeitado ("o caminho durável é corrigir o dado, não lembrar a resposta antiga").
- **Analytics sobre `query_log.jsonl`/`actions.jsonl`** — rejeitado (`jq`/`Counter` por conta do usuário já bastam).
- **Fusão automática em qualquer confiança, ou por tipo igual** — rejeitado por medição dupla (confiança e `kind` como filtro, os dois reprovaram).
- **Busca semântica/embeddings** — rejeitado (desproporcional pro tamanho do catálogo).
- **`julius ia status`** — rejeitado (`tail`/`SELECT` já cobrem).

## 7. Perguntas em aberto para o usuário

**Atualização (2026-09-22): 5 das 11 perguntas abaixo já foram resolvidas** (rejeição do preço avulso, §9) — mantidas riscadas, não apagadas, pra quem ler o histórico entender a curva sem procurar em outro lugar. Só as que continuam de pé valem resposta agora.

### Sobre o núcleo deste documento (personalidade/fallback/CTA)

1. ~~§4.1 (registrar preço avulso) é o item mais caro...~~ — **resolvida**: rejeitado, não se aplica mais (§9).
2. ~~Se §4.1 avançar: confirmação por botão ou gravar direto?~~ — **resolvida**: não se aplica, §4.1 não existe.
3. ~~A regra "não explique a ausência, não peça mais dados" — reabrir para zero-resultado?~~ — **resolvida**: não precisa reabrir. Sem CTA (§9), o Caso 1 já é compatível com a regra como está — sobra só medir o TOM da nova frase, não o comportamento (ver §10, critério de verificação do Caso 1).
4. ~~O exemplo do Caso 2 é real ou ilustrativo?~~ — **resolvida**: é real (§9).

### Sobre escopo do produto (§6 — ainda em aberto, nada destas está sendo construído agora)

5. **Reativo vs. proativo**: alertas de preço e resumos periódicos (§6.1) mudam a natureza do produto — é algo que você quer, ou o valor é justamente ser só memória sob consulta?
6. **Pergunta pendente (§6.1)**: desde a v2.13, o loop de "check_price pergunta quantidade, pessoa responde" já foi usado de verdade no Telegram? Se já travou ou "esqueceu" alguma vez, isso é dívida de confiabilidade, prioridade acima de qualquer item deste documento.
7. **Entrada por foto/OCR (§6.2)**: continua "sem prazo", ou subiu de prioridade no uso real?
8. **Multi-usuário (§6.4)**: allowlist de 1 chat_id é decisão permanente, ou outras pessoas da casa vão eventualmente usar o bot?

### Reflexão geral

9. ~~Correção em linguagem natural de preço avulso~~ — **resolvida**: sem objeto, §4.1 não existe.
10. ~~Das três famílias, qual é a prioridade real?~~ — **resolvida por eliminação**: (ii) preço avulso rejeitado; (iii) proatividade/multi-usuário não está sendo perseguida agora (§5-8 acima continuam abertas, mas nenhuma virou trabalho); só (i) personalidade/fallback segue, detalhada em §10.
11. Itens de §6 que dependeriam de "a IA ter certeza" continuam parqueados junto com o resto de §6 — sem ação agora, sem necessidade de resposta enquanto §6 não virar prioridade.

## 8. É um bom momento para essa mudança de entendimento do produto?

O pedido que gerou este documento veio com uma observação explícita: "o entendimento do produto mudou". Isso merece resposta direta, não só mais opções — porque é justamente o tipo de coisa que a descoberta de requisitos deveria fechar antes de qualquer design.

**Não é veredito único — o pedido mistura duas mudanças de natureza diferente:**

**(a) Os ajustes de prompt (Casos 2/3/5, §4.2-4.4) — SIM, bom momento.** O projeto está em modo de polimento fino há sete rodadas seguidas (v2.7 → v2.13), todas sobre a mesma coisa: a voz do bot em situações de borda. Reconhecer eco de fala anterior, ou ligar "coca" com "refrigerante 2L", é a continuação natural dessa trajetória — barato, reversível, não toca em dado nenhum. Não é mudança de entendimento do produto, é o produto fazendo o que já vinha fazendo.

**(b) O preço avulso por chat (§4.1) — o motivo da evidência caiu (§0: confirmado real), mas um motivo estrutural continua de pé:**

1. **Quebra o único invariante que o projeto nunca quebrou em 13 versões**: todo preço entra pela nota fiscal, nunca por texto solto. Não é acidente — é a razão de existir de metade do código (`UNIT_MAP` curado, `comparison_basis`, o cuidado com separador decimal e unidade ambígua em "Fatos e pegadinhas"). Preço digitado no chat reabre essa classe inteira de problema, sem nota pra conferir contra. Isso não é mais um argumento de "esperar a evidência" — é um argumento de desenho, que continua valendo mesmo com o log real confirmado.
2. ~~A evidência que sustenta o pedido é de um tipo diferente~~ — **retirado em 2026-09-22**: o usuário confirmou que a conversa é real, não ilustrativa (ver §0). Este documento errou ao supor o contrário; registrado aqui para não repetir o erro de tratar um relato do próprio usuário como hipótese sem perguntar primeiro.

A proatividade e o multi-usuário (§6.1/6.4) continuam numa categoria à parte: `CLAUDE.md` define o produto, na primeira linha, como "ferramenta **pessoal**... memória de preços + decisão de compra" — reativo por desenho, um usuário só. Isso não é uma lacuna, é escopo que o projeto respeitou até agora, e não foi tocado pela confirmação de que o log do §0 é real.

## 9. Decisões do usuário (2026-09-22) e o que elas implicam

Respondido por Q&A direto (`AskUserQuestion`), registrado aqui porque muda o resto do documento:

| Pergunta | Resposta | Implicação |
|---|---|---|
| A conversa é real ou ilustrativa? | **Real**, aconteceu no Telegram | §0 e §8 atualizados acima — a objeção "é só hipótese" cai para o Caso 2 e para os demais casos do documento original |
| Qual mudança priorizar primeiro? | **"Todas devem ser feitas, todas são prioridade"** | Ver correção abaixo — a leitura inicial (que isso implicava §4.1) estava errada |
| CTA sem gravar preço faz sentido? | **Não — seria promessa vazia** | Lido primeiro como "construa a gravação"; correção abaixo: era "não façam a promessa" |
| Reabrir "não explique a ausência" no caso de catálogo vazio? | **Medir antes, com `make test-ia`** | Vira passo de validação antes de qualquer texto de prompt final, não uma decisão de prosa |

**Correção (2026-09-22): a leitura acima estava errada.** A resposta 3 ("Não — seria promessa vazia") tinha duas leituras opostas — "não faz sentido *sem gravar*, então construa a gravação" (o que este documento concluiu primeiro) ou "não faz sentido *fazer a promessa*, então não a façam" — e a primeira virou um desenho inteiro (`docs/design/manual-price-report.md`) sem confirmar qual das duas era. Perguntado diretamente depois: **é a segunda**. Preço avulso por chat **não vai ser construído**. `docs/design/manual-price-report.md` fica pausado, mantido só como registro do raciocínio de schema caso isso seja reaberto um dia.

**O que isso muda nos Casos 1/3/6**: sem gravação, não existe CTA "eu guardo" nem "loop" pra fechar — o Caso 6 (confirmar que o dado vai servir a alguém) deixa de existir como requisito. Os Casos 1 e 3 sobrevivem só na metade de **voz**: trocar o fallback robótico por algo com personagem, **sem pedir preço/mercado de volta** — o que, na prática, devolve o documento à regra que já estava medida desde a v2 (§2a): "não explique a ausência, não peça mais dados". Essa regra não precisa mais ser reaberta para o Caso 1 — ela já é a resposta certa, e o trabalho que sobra é só de tom, não de comportamento.

**"Todas são prioridade" (resposta 2), corrigido**: passa a significar as mudanças de prompt puras — Casos 1 (só voz), 2, 3 (parte de ligar perguntas parecidas, sem prometer gravar), 4 e 5 — todas independentes, todas sem decisão de schema, todas podíam andar em paralelo desde o início. Não há mais nenhuma dependência bloqueando por §4.1.

## 10. Critérios de aceite — gatilho, não-gatilho, exemplo (reduzindo ambiguidade)

Depois do mal-entendido do §9 (uma resposta ambígua virando um desenho inteiro na direção errada), esta seção substitui a prosa solta de §3/§4.2-4.4 por algo verificável: pra cada caso que sobreviveu, o que dispara, o que **não** dispara (a fronteira é o que costuma ficar implícito e gerar erro), e um exemplo de entrada/saída. Nenhum destes é texto de prompt final — são o contrato que o texto final tem que satisfazer.

### Caso 1 — fallback de item sem preço, só voz, sem CTA
- **Gatilho**: `no_match_fallback_line`/busca zero resultado, sem alternativas (`alternatives` vazio).
- **Não-gatilho**: zero resultado COM alternativas — esse caminho já convida a ver outra coisa ("Ainda não tenho preço de X, mas tenho: ..."), não muda.
- **Proibido na resposta**: qualquer frase terminando em pedido de dado ("me diga o preço", "me diz o mercado") — decisão §9, não é esquecimento.
- **Exemplo**: input "quanto tá o feijão?", fatos = zero registros/zero alternativas → resposta no tom Julius, comentando a ausência sem pedir nada de volta e sem explicar por que falta (regra já medida, §2a se mantém).
- **Verificação**: rodar um caso assim em `make test-ia` (decisão §9, pergunta 4) antes de fechar o texto — confirmar que a resposta não cai de volta no hábito "explicativo" que a v2/v2.7.1 já corrigiram.

### Caso 2 — eco de comentário anterior do próprio bot, não item novo
- **Gatilho**: a mensagem nova (a) não contém nome de produto reconhecível nem preço, **e** (b) a última fala do bot no histórico (`HISTORY_TURNS=3`) trazia uma pergunta retórica ou comentário de personagem.
- **Não-gatilho**: a mensagem cita um produto de mercado real, mesmo remoto do assunto anterior ("quanto custa uma lâmpada?" continua indo para `search_prices`, mesmo que o catálogo não tenha lâmpada — a resposta certa nesse caso é o fallback do Caso 1, não o reconhecimento de piada).
- **Exemplo**: bot disse "sabe quanto tempo de luz isso paga?"; pessoa responde "quanto tempo então?" → reconhecer como continuação da piada, texto livre, **nunca** chamar `search_prices("luz")` nem `search_prices("tempo")`.
- **Risco já registrado** (§4.2): a fronteira entre "eco" e "pergunta real sobre algo fora do catálogo" é a parte genuinamente ambígua que sobra — não dá pra eliminar só com definição, precisa de exemplo no prompt e de um caso em `ROUTING_CASES`.

### Caso 3 — ligar perguntas parecidas em sequência
- **Gatilho**: dois turnos consecutivos, dentro de `HISTORY_TURNS=3`, citam nomes que resolveriam para o mesmo produto/`kind`, mas com variação de embalagem/tamanho explícita na segunda menção (ex.: sem tamanho → "2L").
- **Não-gatilho**: nomes que resolvem a `kind` diferente, mesmo soando parecido (ex.: "guaraná" depois "guaraná zero") — tratar como itens possivelmente diferentes, nunca assumir igual. Mesma cautela que o bug tomate/passata (v2.11) já ensinou sobre desempate errado.
- **Exemplo**: "coca por 12 reais" seguido de "refrigerante 2L por 12 reais" → antes de tratar como pergunta nova, perguntar "é a mesma coca de agora, só em 2L?".
- **Verificação obrigatória**: um caso `("coca", depois "refrigerante 2L")` em `tests/test_real_ai.py::ROUTING_CASES` — não aceitar só pela leitura da prosa do prompt (mesma lição já registrada da v2.8: "só a instrução em prosa não bastou").

### Caso 4 — já implementado, sem mudança
Critério de aceite = regressão zero: `records_facts`/`check_price` continuam citando a diferença mais-barato/mais-caro exatamente como já fazem. Nenhum trabalho novo aqui.

### Caso 5 — pergunta vaga sem contexto nenhum
- **Gatilho**: "tá caro?"/"isso é caro?" (ou variação) sem item citado nem na mensagem atual nem nas últimas `HISTORY_TURNS` mensagens da conversa.
- **Não-gatilho**: item já mencionado nas últimas mensagens — já coberto pela regra existente do `SYSTEM_PROMPT` ("junte o que foi mencionado nas últimas mensagens, não só na mais recente"); esta mudança só cobre o caso em que não há nada pra juntar.
- **Exemplo**: primeira mensagem da conversa é "tá caro?" → bot pergunta o item, nunca chama `search_prices` com termo vazio, nunca dá veredito.

## 11. Fora de escopo deste documento

Como em toda rodada anterior deste projeto: nenhuma implementação, nenhum texto de prompt final, nenhuma migração de schema. Depois de decidir as perguntas do §6, o próximo passo é `/sc:design` (ou o padrão já usado no projeto: `docs/requirements/*.md` → `docs/design/*.md`) só para os itens aprovados.
