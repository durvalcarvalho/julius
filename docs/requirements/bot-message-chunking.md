# Requisitos: várias mensagens curtas, em vez de um textão

> Descoberta via `/sc:brainstorm`, 2026-09-19. Nasceu de um screenshot real do bot (anexo à sessão): uma pergunta sobre carnes voltou um parágrafo único de introdução, duas tabelas `<pre>` e uma linha de conclusão — tudo numa mensagem só; a pergunta seguinte sobre "qual mercado" voltou um segundo parágrafo único enumerando banana, cebola, tomate, uva e vinho sem quebra nenhuma. Motivo dado pelo usuário: "no final das contas é um 'ajudante' de mercado" — ninguém quer ler um texto enorme por produto consultado.

## Objetivo esclarecido

Duas mudanças, não uma — confirmado explicitamente pelo usuário quando perguntado se o problema era só o formato (bloco único) ou o volume de texto: **as duas**.

1. **Menos texto por resposta.** O comentário do Julius (comparação, pergunta retórica) continua existindo — o usuário quer manter o tom, só "mais curto". O textão de hoje não é só formatação ruim, é conteúdo demais.
2. **Várias mensagens, não uma.** O que sobrar depois de cortar deve chegar como várias bolhas curtas no Telegram, do jeito que uma pessoa manda mensagem — não um parágrafo com quebra de linha manual.

A tabela `<pre>` de hoje foi chamada pelo próprio usuário de "uma merda" visualmente. Ele especulou que um dia isso pode virar imagem renderizada, mas **decidiu explicitamente deixar essa ideia para depois** — fora do escopo desta rodada.

## Requisitos funcionais

**RF1 — Resposta com muitos itens vira poucas mensagens, nunca uma por item sem limite.** Confirmado: quando uma busca/comparação traz vários produtos (ex.: "quanto tá custando as carnes", 6 tipos), o critério é **agrupar em poucas bolhas** (o usuário escolheu essa opção explicitamente sobre "uma bolha por item sem limite" e "depende da quantidade"). Isso descarta enviar 6 mensagens para 6 itens; o número de mensagens deve ficar baixo (ordem de grandeza: poucas unidades) independente de quantos itens vierem.

**RF2 — Cada bolha carrega um resumo curto, não a tabela detalhada de hoje.** A tabela completa (`<pre>` com todas as linhas, todas as datas) sai da resposta padrão do bot nesta rodada. O que substitui: um resumo por item/grupo com o essencial — preço, unidade (nunca omitir se é por quilo, litro ou unidade, regra que já existe e continua valendo) e mercado.

**RF3 — O comentário do Julius encolhe, mas não desaparece.** Comparação e pergunta retórica continuam fazendo parte da resposta; a mudança é caber em uma bolha curta em vez de um parágrafo. Não é para virar resposta seca só de fato — o usuário rejeitou essa opção quando perguntado.

**RF4 — O agrupamento é "inteligente", critério ainda em aberto (ver Questões).** O usuário usou esse termo sem detalhar o critério exato (por categoria/tag, por extremos mais barato/mais caro, por lote de tamanho fixo). Isso é uma decisão de design, não de requisito — listada abaixo para a próxima fase resolver.

## Requisitos não funcionais

**RNF1 — A guarda de dinheiro não pode enfraquecer.** Hoje `services/suggestions.narrate` garante que nenhum `R$ X,XX` chega ao usuário sem estar nos fatos entregues ao modelo (`services/suggestions.py`, ver CLAUDE.md "v2.7"). Se a resposta virar várias mensagens — geradas por uma chamada só de IA fatiada, ou por várias chamadas — essa garantia tem que valer em **cada** mensagem enviada, sem exceção.

**RNF2 — Orçamento de IA não pode explodir sem decisão consciente.** O orçamento é US$5/mês; o custo por narração hoje já está medido (ver v2.7/v2.7.1 no CLAUDE.md, US$0,0002–0,0007 por chamada). Trocar "uma chamada de IA gera um texto que o código fatia em N mensagens" por "uma chamada de IA por mensagem/grupo" multiplica o custo por N — decisão que precisa ser explícita no design, não um efeito colateral de implementação.

**RNF3 — Preservar o que já funciona.** O indicador "digitando..." (`_show_typing`, pesquisa de humanização validada em 2026-09-18), a guarda de dinheiro, o corte de 4096 caracteres do Telegram (`fit`) e o fluxo de confirmação de escrita (`PendingWrite`/botões) não fazem parte deste pedido e não devem regredir.

## Histórias de usuário

- **Como usuário**, ao perguntar o preço de vários tipos de carne de uma vez, quero receber poucas mensagens curtas — não uma por produto nem um bloco único — para poder ler rolando o dedo, como numa conversa normal.
- **Como usuário**, ao comparar preços entre mercados para vários produtos (banana, cebola, tomate, uva, vinho), quero um veredito compacto por mensagem, não um parágrafo enumerando tudo sem quebra.
- **Como usuário**, quero que o Julius continue comentando e comparando preços com a personalidade de sempre, só que em frases mais curtas que cabem numa bolha de chat.

## Critérios de aceite (rascunho, para o `/sc:design` refinar com números)

- Nenhuma resposta de busca/comparação com múltiplos itens sai como uma mensagem única de parágrafo corrido.
- Nenhuma resposta desse tipo vira mais que um punhado de mensagens (a contagem exata é decisão de design, não deste documento) — nunca uma bolha por item sem teto.
- Toda mensagem enviada continua sem nenhum valor `R$` que não esteja nos fatos originais (guarda existente, não pode regredir).
- O comentário de personagem em cada bolha é sensivelmente mais curto que os exemplos do screenshot (hoje: parágrafos de 3+ frases; alvo: 1–2 frases curtas).

## Questões em aberto para a próxima fase (`/sc:design`)

1. **Critério de agrupamento** — "poucas bolhas" agrupando por quê: categoria/tag do produto (`products.kind`, já existe), por extremos (só o mais barato e o mais caro, resto vira contagem), ou por lote de tamanho fixo (ex.: 2–3 itens por bolha, na ordem que vierem)?
2. **Custo: uma chamada de IA ou várias?** Fatiar o texto de uma única resposta de IA em N mensagens do Telegram (custo igual a hoje) vs. pedir à IA um comentário por grupo (custo multiplicado, mais grounded por grupo). Precisa de medição antes de decidir — ver "medir antes de argumentar" nas convenções do projeto.
3. **A tabela detalhada desaparece de vez do bot, ou fica disponível sob pedido** ("manda a lista completa")? O usuário adiou "virar imagem" para depois, mas não disse se a tabela de texto simplesmente some ou se continua existindo como opção secundária.
4. **Resposta de item único também é fatiada?** O screenshot só mostra o problema em respostas com vários itens. Uma resposta de um produto só (hoje: fato + comentário no mesmo texto) também deveria virar duas mensagens, ou já é curta o suficiente para ficar como está?
5. **Ritmo entre as mensagens** — enviar as várias bolhas em sequência imediata, ou repetir o indicador "digitando..." entre elas (mesmo espírito da pesquisa de humanização já aplicada à primeira resposta)?
6. **Escopo**: isso vale só para busca de preço e comparação entre mercados (os dois casos do screenshot), ou também para listagens (`produtos`/`mercados`) e confirmações de escrita?

## Fora do escopo desta rodada (decisão explícita do usuário)

- Renderizar a tabela de preços como imagem — ideia levantada pelo próprio usuário, adiada de propósito.
- Cortar o comentário do Julius a ponto de virar resposta só-fato (rejeitado quando perguntado).

## Próximo passo

`/sc:design` para resolver as questões em aberto acima e propor o mecanismo (onde a "fatiação" acontece: no prompt da IA, em `bot/render.py`, ou em `bot/app.py`/`bot/turn.py` no envio) — ou `/sc:workflow` se as questões já tiverem resposta. Nada foi implementado nesta sessão.
