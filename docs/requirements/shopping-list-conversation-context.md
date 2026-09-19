# Requisitos: veredito por lista de compras, e a conversa passando a lembrar do que já foi dito

> Descoberta via `/sc:brainstorm`, 2026-09-19. Nasceu de dois screenshots reais anexados à sessão: (1) "Qual mercado eu devo ir? Qual é mais barato?" voltou uma mensagem única enumerando 16 produtos (banana até vinho) com mínimo/máximo por um; (2) de 2026-09-18, o bot perguntou "o que você quer saber?", o usuário respondeu "Sim" e o bot devolveu "Não entendi — 'sim' o quê?".

## Causa raiz medida (não só estilo de prosa)

`grep` em `~/.local/share/julius/ai_calls.jsonl` no horário exato do primeiro screenshot (2026-09-19T17:42:52) confirma: a pergunta caiu em `compare_stores`, que hoje compara **todos os grupos (`kind`) do catálogo inteiro** — 16 no banco atual, tudo que o usuário já comprou alguma vez, não uma lista do que ele quer comprar agora. A narração (`persona` v3) tentou dar um veredito sobre os 16 juntos e truncou duas vezes (`"error": "finish_reason length"`, `max_tokens=500`); como 16 > `FALLBACK_LINE_MAX_GROUPS` (6), caiu na tabela crua — o textão do screenshot. O problema não é (só) formatação: é a pergunta errada sendo respondida.

O segundo screenshot aponta uma causa relacionada, mais profunda: o bot já reenvia histórico bruto à IA (`HISTORY_TURNS = 3`, `bot/turn.py`), mas não existe nenhum estado explícito de "que pergunta ficou pendente" ou "que itens já foram mencionados nesta conversa" — cada turno reconstrói a intenção do zero a partir do texto cru.

## Objetivo esclarecido

O usuário confirmou explicitamente que as duas coisas **são o mesmo problema** e entram juntas nesta rodada: o bot não constrói entendimento aos poucos, nem quando responde (despeja tudo de uma vez) nem quando conversa (trata cada mensagem como isolada).

## Requisitos funcionais

**RF1 — Pergunta vaga sobre mercado sem lista conhecida → o bot pergunta de volta.** "Qual mercado eu devo ir?"/"qual é mais barato?" sem nenhum item específico citado (nesta mensagem ou nas recentes da conversa) nunca aciona comparação sobre o catálogo inteiro. Resposta: pergunta pelo que a pessoa quer comprar (ex.: "Depende, o que você quer comprar? Tem uma lista?"), confirmado explicitamente pelo usuário.

**RF2 — Com lista conhecida, veredito agregado, não item por item.** Formato: "N de M itens da sua lista são mais baratos no mercado X, recomendo ir lá" — nunca o listão atual (um bloco por produto com mínimo/máximo).

**RF3 — Itens fora do vencedor: uma linha para o segundo colocado.** Confirmado: não ignorar o resto nem listar item por item — uma linha citando onde os itens restantes saem mais em conta (ex.: "os outros 4 saem mais em conta no Assaí").

**RF4 — Resposta curta/ambígua interpretada à luz da pergunta anterior do bot.** O caso "sim": se o turno anterior do próprio bot foi uma pergunta em aberto, a resposta seguinte do usuário — mesmo curta — deve ser tratada como resposta a ela, nunca como mensagem solta sem sentido.

**RF5 — Lista construída aos poucos, sem comando dedicado.** "Preciso de leite" → "e pão" → "qual mercado?" deve somar os itens mencionados na conversa recente como a lista implícita da pergunta final — sem exigir um comando tipo "adiciona X na lista" (isso é uma feature diferente, fora desta rodada por não ter sido pedida).

**RF6 — Retomar assunto fora da janela atual de histórico.** Hoje só as últimas `HISTORY_TURNS = 3` trocas são reenviadas ao modelo; algo mencionado antes disso já não está disponível. O usuário quer poder retomar um assunto mais antigo da mesma conversa quando for relevante. Critério exato de "até quando" e "o que conta como mesma conversa" fica para o design (ver Questões).

## Requisitos não funcionais

**RNF1 — A guarda de dinheiro não pode enfraquecer.** Nenhum `R$ X,XX` chega ao usuário sem estar nos fatos entregues ao modelo (`services/suggestions.narrate`) — vale também para o novo veredito agregado (RF2/RF3): a contagem "N de M" e o nome do 2º colocado têm que vir de fato calculado em código, nunca de conta que a IA faça sozinha.

**RNF2 — Orçamento de IA não pode crescer sem decisão consciente.** Qualquer mecanismo para RF4–RF6 (mais histórico reenviado, estado de conversa persistido, chamada extra) tem custo em tokens a medir antes de decidir — mesma disciplina de todo o resto do projeto (ver "medir antes de argumentar" nas convenções).

**RNF3 — Não regredir o que já foi resolvido.** v2.8 (várias mensagens curtas em vez de um textão) e a persona/humanização (v2.7.x) continuam valendo; isto é uma causa adicional de textão (catálogo inteiro em vez de lista), não uma reversão daquele trabalho.

## Histórias de usuário

- **Como usuário**, ao perguntar "qual mercado é mais barato" sem ter dito o que quero comprar, quero que o bot pergunte pela minha lista em vez de comparar tudo que já registrei alguma vez.
- **Como usuário**, com uma lista em mente, quero saber quantos itens saem mais barato em qual mercado e para onde ir com o resto, num resumo curto — não um item por vez.
- **Como usuário**, quero responder "sim" ou completar uma ideia numa mensagem curta e o bot entender à luz do que ele mesmo perguntou antes.
- **Como usuário**, quero montar o que preciso comprar aos poucos, em várias mensagens, sem precisar de um comando de "lista".

## Critérios de aceite (rascunho, para o `/sc:design` refinar com números)

- "Qual mercado é mais barato"/"onde eu devo ir" sem lista conhecida nunca aciona `compare_stores` sobre o catálogo inteiro — sempre pergunta pela lista primeiro.
- Resposta com lista conhecida nunca lista item por item: sempre "N de M ... recomendo X" + uma linha do 2º colocado.
- Uma resposta curta do usuário logo após uma pergunta do bot é interpretada como resposta àquela pergunta (teste de aceite: reproduzir o caso "sim" e obter uma resposta coerente, não "não entendi").
- Itens mencionados em mensagens anteriores da mesma conversa (dentro de uma janela a definir) entram na lista sem o usuário repetir.

## Questões em aberto para a próxima fase (`/sc:design`)

1. **O que conta como "mesma lista/conversa"?** Critério de expiração — tempo parado, comando explícito ("nova lista"/"esquece isso"), virada de dia? Hoje não existe conceito de sessão além do `HISTORY_TURNS = 3`.
2. **Mecanismo para lembrar além da janela atual (RF6)**: aumentar `HISTORY_TURNS` (mais tokens por turno, mais custo, ver RNF2) vs. um estado explícito persistido (nova tabela "intenção/lista corrente" por chat). Precisa de medição de custo antes de escolher.
3. **Como distinguir "resposta a pergunta pendente" de "assunto novo"** quando o usuário muda de ideia no meio — exige o bot registrar explicitamente "fiz esta pergunta, aguardo resposta sobre X", ou basta reforçar o prompt para usar o histórico que já existe (`state.history`)?
4. **Empate ou 3+ mercados divididos quase igual entre os itens da lista** — o que "recomendo X" vira quando não há um vencedor claro? Não perguntado ainda nesta rodada.
5. **Casar texto livre do item ("leite", "pão") com `products.kind`/`canonical_name`** — reaproveitar a busca (`rapidfuzz`) e o grupo de comparação que já existem, ou isso expõe um caso novo (ex.: item da lista que não tem nenhum registro de compra ainda)?
6. **Escopo**: isto vale só para `compare_stores` (o caso do screenshot), ou também para `search_prices` quando o usuário pergunta por vários produtos de uma vez?

## Próximo passo

`/sc:design` para resolver as questões acima e propor o mecanismo (onde a lista/estado de conversa vive, como o veredito agregado é calculado em código antes de ir à IA). Nada foi implementado nesta sessão.
