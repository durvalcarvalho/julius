# Requisitos: veredito de compra — ordem da resposta, itens que somem em silêncio, e agrupar por mercado

> Descoberta via `/sc:brainstorm`, 2026-09-19. Três screenshots reais anexados à sessão, todos depois da v2.10 (veredito por lista de compras) já estar em produção: (1) lista de 20 itens, resposta final "Costa Atacadao ADE Aguas Claras leva 4 dos 6 itens" — lida como se a lista tivesse 6 itens; (2) "qual mercado é mais barato pra tomate e cebola?" respondeu só sobre cebola, tomate nunca é mencionado; (3) "Eu tô no mercado e os ovos tão 14 reais, esse preço tá bom?" voltou uma comparação de duas lojas em vez de sim/não.

## Causa raiz medida (não só estilo de prosa)

**Confirmado ao vivo, contra `~/.local/share/julius/ai_calls.jsonl` e o banco de produção — não é o que a primeira leitura do código sugeria.** A hipótese inicial (tomate "só tem preço de uma loja") **é falsa**: medido no banco real, `tomate` tem preço em **3 mercados** (`SELECT p.kind, COUNT(DISTINCT store_cnpj) ... GROUP BY kind` → `('tomate', 3, 5)`). A causa real, reproduzida rodando `search_service.match_kind` direto contra o banco de produção:

```
match_kind(conn, "tomate") -> "passata de tomate"   # devia ser "tomate"
match_kind(conn, "cebola") -> "cebola"               # este casou certo
```

`passata de tomate` tem preço em **1 mercado só** — é esse grupo (errado) que `comparison_service.compare_stores()` descarta em `if len(cheapest) < 2: continue` (`services/comparison.py`, linha 63). Como `match_kind` devolveu um tipo (não `None`), "tomate" nunca cai em `unmatched_terms` — some sem deixar rastro em lugar nenhum da resposta. O log real da conversa bate exatamente com isso: `ai_calls.jsonl`, 2026-09-19T20:52:43, os `fatos` enviados à persona trazem só `cebola` e `"veredito: 1 de 1 itens"` — tomate nunca chegou a existir para o modelo, a IA não tem culpa nenhuma aqui.

**A causa da causa, já documentada no próprio código como limitação aceita — e agora com o "caso concreto observado em uso" que faltava para revisitá-la.** `services/search.py`, docstring de `KIND_MATCH_CUTOFF` (linhas 102–108): "*a generic term can tie 100 against more than one real kind (...) match_kind returns whichever sorts first alphabetically (...) Accepted (...) as a real limitation of matching a word against a vocabulary that was never designed to be unambiguous, not a bug to chase without a concrete wrong answer observed in use*" — e cita literalmente `"tomate" vs "manteiga"` como um dos pares de score alto medidos, mas não flagra `"tomate"` vs `"tomate"` (kind idêntico) vs `"passata de tomate"` (kind composto que também contém a palavra inteira "tomate"): as duas pontuam igual (100, casamento de palavra inteira) e o desempate por ordem alfabética (`p` antes de `t`) escolhe a errada. Este screenshot é exatamente o "caso concreto" que a nota pedia.

**A mesma classe de bug provavelmente também explica o "4 dos 6" da lista de 20 itens, mas isso não foi reproduzido com a mesma certeza.** Rodar `match_kind` direto contra as 20 linhas cruas da mensagem original não reproduz "6 grupos" — porque quem manda `items` para `compare_stores` (`bot/actions.py`, linha 147) é o próprio agente de IA, já tendo limpado "1 cacho de banana" para algo como "banana" antes de chamar a ferramenta, e **isso não fica gravado em lugar nenhum** (`ai_calls.jsonl` grava o texto cru do usuário para `bot_turn`, não os argumentos da chamada de ferramenta). Não dá para saber, sem instrumentar, quais termos exatos o agente passou nem quais kinds `match_kind` devolveu naquela conversa — só dá para afirmar, com o mesmo mecanismo comprovado no caso do tomate, que um termo pode casar um tipo (certo ou por ambiguidade, errado) cuja cobertura é de 1 mercado só e desaparecer da resposta sem nenhuma linha explicando por quê. **80 dos 98 `kind` do catálogo real hoje têm preço em 1 mercado só** — a superfície para este tipo de desaparecimento silencioso é grande.

**A frase "N de M itens" usa M = grupos que sobreviveram a `compare_stores`, não o tamanho da lista pedida nem o número de termos que casaram algum tipo** — daí o usuário ler "4 dos 6" como se a lista inteira fosse 6 itens, quando ele mandou 20.

**A ordem da resposta foi desenhada ao contrário do que o usuário quer agora.** O prompt `persona` (`services/suggestions.py`, `SYSTEM_PROMPTS["persona"]`, regra 3) instrui explicitamente "feche com um veredito direto" — informação e comentário vêm antes, o "compra em X" vem por último. No screenshot da lista de 20 itens isso produziu quatro mensagens, com a instrução realmente acionável ("Compra no Costa Atacadao pra banana, cebola, cenoura e limão; o creme de leite, no Assai") **por último**, depois de duas mensagens de exceção (creme de leite, manga). O usuário quer o inverso: a resposta primeiro, a justificativa depois.

**"Esse preço tá bom?" não é a mesma pergunta que "qual mercado é mais barato".** O prompt do agente (`bot/agent.py::SYSTEM_PROMPT`) já trata "está caro?" como proibido de virar veredito — rotea para `search_prices` de propósito ("Você mostra o que foi pago; nunca diz se um preço é caro ou barato"), decisão que vem desde o MVP (CLAUDE.md, "Sem veredito automático (barato/caro) no MVP"). O caso novo do usuário é diferente dos dois: ele está no mercado, tem um preço **que não veio de nenhuma nota importada** (é o que ele está vendo na etiqueta agora), e quer saber se vale a pena levar ali mesmo — comparado ao histórico. Não existe ação nem dado hoje para "compare este preço que estou te dizendo contra o histórico" — é escopo novo, não um ajuste do que já existe.

## Objetivo esclarecido

O usuário confirmou, com os próprios exemplos, que quer três coisas diferentes, todas sobre a forma da resposta de veredito de compra:

1. Quando ele pergunta "qual mercado", a resposta é o nome do mercado — logo de cara, sem rodeio.
2. Quando a pergunta é essencialmente sim/não ("esse preço tá bom?"), a resposta é sim ou não — não uma comparação entre lojas que ele não pediu.
3. A lógica de "vale a pena" não é centavo contra centavo: diferença pequena (poucos centavos) não muda a resposta; diferença grande, muda.
4. Ele pode aceitar ir a até uns 2 mercados numa mesma compra, dividindo por **categoria inteira** (ex.: comida num, limpeza noutro) — nunca fatiando o mesmo tipo de item (ex.: metade do hortifruti num mercado, metade no outro).

## Requisitos funcionais

**RF1 — Nenhum item pedido pode sumir sem explicação.** Todo item que a pessoa citou numa comparação (`compare_stores`) termina em uma de três categorias visíveis na resposta: (a) entrou no veredito porque o tipo casado tem preço em 2+ mercados; (b) casou um tipo, mas esse tipo só tem preço registrado em um mercado — precisa de uma frase própria, diferente da de "não reconheço esse item" (que é o `unmatched_terms` de hoje); (c) não casou tipo nenhum. Hoje só (a) e (c) existem; (b) é o buraco que fez tomate sumir e "6" parecer o tamanho da lista. Isso é necessário **mesmo depois** de corrigir a ambiguidade de `match_kind` (ver RF1.1) — 80 dos 98 tipos do catálogo real são de mercado único hoje, então itens vão continuar caindo em (b) com frequência real, não só por bug de casamento.

**RF1.1 (correção, não só cobertura) — `match_kind` não pode devolver o tipo errado por desempate alfabético quando um tipo mais específico "contém" a palavra do tipo genérico.** Medido e reproduzido: `match_kind(conn, "tomate")` devolve `"passata de tomate"` em vez de `"tomate"`, porque os dois pontuam 100 (casamento de palavra inteira) e o desempate hoje é ordem alfabética. Diferente de RF1 (que é sobre a resposta nunca esconder um item sem explicação), isto é uma correção de comportamento errado — o tipo casado está objetivamente errado, não é uma limitação de cobertura de dado.

**RF2 — A contagem do veredito distingue "itens pedidos" de "itens comparados".** A frase deixa de ser só "N de M itens mais baratos em X" (M = grupos comparáveis) e passa a deixar claro, quando M é menor que o total pedido, que M é um subconjunto — ex.: "Dos 20 itens da lista, comparei 6; desses, 4 saem mais em conta no Costa Atacadao."

**RF3 — Para pergunta de comparação de mercado ("qual mercado", lista de compras), a resposta abre com a instrução acionável, a justificativa vem depois.** Inverte a regra 3 do prompt `persona` para este tipo de pergunta especificamente: "vá a X para A, B, C; vá a Y para D" primeiro; exceções, comparação de preço e comentário do personagem depois. Não mexe no formato de busca de preço de um produto só (`search_prices`), onde "informação primeiro, comentário depois" já é, na prática, a resposta direta que se pede — o problema medido está em `compare_stores`/veredito de lista, não ali.

**RF4 (escopo novo, não ajuste) — Checar um preço visto ao vivo no mercado contra o histórico, com resposta sim/não.** Pergunta do tipo "os ovos tão a X reais aqui, tá bom?" — hoje roteia para `search_prices` e nunca dá veredito (decisão de design existente e deliberada). O pedido novo é: dado um preço que a pessoa está informando (não uma nota importada), comparar contra o mais barato já registrado daquele tipo e responder sim ou não, com a diferença como justificativa — nunca a resposta invertida (justificativa longa, sim/não perdido no meio).

**RF5 — Diferença pequena não muda a resposta; diferença grande, muda — mas o corte é relativo, não centavos fixos.** O exemplo do usuário: R$0,53 (mais barato conhecido) contra R$0,59 é "não importa, ainda tá barato"; contra R$0,75 é "bem mais caro". R$0,06 e R$0,22 são as duas diferenças em jogo — a primeira é ~11% acima do mínimo, a segunda ~42%. Confirma que o corte precisa ser um **percentual sobre o preço mais barato conhecido**, não um valor fixo em reais (R$0,06 muda pouco num item de R$0,53 mas seria grande num item de R$2,00). O valor exato do corte fica para o `/sc:design` (ver Questões).

**RF6 — Recomendação de compra agrupa por categoria, não por vencedor isolado a cada item.** Quando o veredito cobre itens de mais de uma categoria (ex.: hortifruti e limpeza), a resposta não deve indicar mercados diferentes para itens da MESMA categoria — ir a um mercado para metade do hortifruti e outro para a outra metade não é uma recomendação executável. A meta é no máximo ~2 mercados por resposta, com cada categoria inteira atribuída a um mercado só (o que vence a maioria dos itens daquela categoria), mesmo que item a item o vencedor variasse. **Isto não é um ajuste de prompt/ordem como RF3 — é trocar o algoritmo do veredito.** `shopping_verdict` (`services/comparison.py`) hoje conta vitória por `kind` individualmente e forma só um vencedor + um segundo colocado, sem noção de categoria; ele pode (e no caso hortifruti/limpeza, vai) picotar uma mesma categoria entre o vencedor e o segundo colocado. Fazer RF6 valer exige uma tally por categoria antes de consolidar em no máximo 2 mercados — não existe hoje um caminho de código nem um campo em `ShoppingVerdict` para isso; `/sc:design` trata como peça nova, não como reescrita de texto.

## Requisitos não funcionais

**RNF1 — A guarda de dinheiro não pode enfraquecer.** RF3/RF4/RF6 mudam ordem e agrupamento do texto, nunca a fonte dos números: todo preço, diferença e percentual citado continua vindo de fato já calculado em código (`comparison_facts`/`shopping_verdict`/o cálculo novo de RF4/RF5), nunca de conta que a IA faça sozinha — mesma disciplina de sempre neste projeto.

**RNF2 — RF4 reverte, de propósito e por pedido explícito do usuário, um requisito fundador do projeto.** CLAUDE.md lista em "Requisitos-chave": *"Sem 'veredito' automático (barato/caro) no MVP — dado histórico curto por produto, qualquer cálculo estatístico seria ruído. O usuário decide olhando a lista."* Isto não é um detalhe de estilo a ajustar — é a linha que `bot/agent.py::SYSTEM_PROMPT` cita quase literalmente ("nunca diz se um preço é caro ou barato"). RF4 abre uma exceção **estreita e registrada**: só quando a pessoa informa um preço que ela mesma está vendo agora (não uma nota importada), comparado contra o histórico, com o corte relativo de RF5. Fora dessa forma exata, a regra antiga continua valendo — "está caro?" sem preço nenhum informado continua roteando para `search_prices`, sem opinião. Registrar isto aqui evita que uma sessão futura trate a mudança como já resolvida "porque o veredito de lista (RF6) já existe" — são decisões distintas, tomadas em momentos distintos, por motivos distintos.

**RNF3 — Não regredir v2.7–v2.10.** Blocos curtos, humanização, veredito por lista (grupos com 2+ lojas, contagem de vitórias) continuam valendo; isto ajusta ordem, cobertura e agrupamento, não desfaz o que já funciona.

## Histórias de usuário

- **Como usuário**, ao perguntar qual mercado ir com uma lista de compras, quero ler primeiro para onde ir e com o quê, e só depois (se eu quiser) o porquê.
- **Como usuário**, quero saber quando um item da minha lista não entrou na comparação e por quê — se é porque o Julius não conhece o item, ou porque só tenho preço de um mercado para ele.
- **Como usuário**, ao perguntar se um preço que estou vendo agora no mercado tá bom, quero um sim ou não direto, considerando que poucos centavos de diferença não contam.
- **Como usuário**, quero uma recomendação de no máximo 2 mercados, sem fatiar a mesma categoria de produto entre eles.

## Critérios de aceite (rascunho, para o `/sc:design` refinar com números)

- Reproduzir o caso da lista de 20 itens: a resposta deixa explícito quantos itens foram pedidos, quantos entraram na comparação, e por que os que ficaram de fora ficaram de fora (tipo desconhecido vs. só um mercado tem preço).
- Reproduzir "qual mercado é mais barato pra tomate e cebola": se um dos dois não tem preço em 2 lojas, a resposta diz isso explicitamente sobre aquele item, não fica muda a respeito dele.
- Resposta de veredito de lista sempre abre com a instrução (mercado + itens), nunca fecha com ela.
- "Esse preço tá bom?" com um preço informado pelo usuário responde sim/não na primeira frase, com o corte percentual (RF5) decidido no design.
- Uma lista com itens de 2 categorias nunca recomenda mais de 2 mercados, e nenhuma categoria aparece dividida entre dois mercados na mesma resposta.

## Questões em aberto para a próxima fase (`/sc:design`)

1. **Valor do corte percentual de RF5** — os dois exemplos do usuário (~11% tolerável, ~42% não) dão só dois pontos; vale medir contra o catálogo real (distribuição de diferença entre mais barato e mais caro por `kind`, já calculada em `comparison_facts`) antes de fixar um número.
2. **RF4 é uma ação nova do agente** (`bot/actions.py`) — como a pessoa informa "qual produto" e "qual preço visto agora" numa frase livre ("os ovos tão 14 reais")? Precisa resolver o tipo (`match_kind`, já existe) e extrair o valor em reais da mensagem — hoje nenhuma ação faz isso.
3. **Categoria de RF6**: usar `products.tags` que já existe (hortifruti, limpeza, ...) ou inferir "categoria" a partir do `kind`? Produto sem tag entra em qual grupo?
4. **RF6 quando categorias empatam ou uma categoria só tem 1 item por mercado** — o algoritmo de contagem de vitórias (`shopping_verdict`) hoje ignora categoria; decidir se ele passa a rodar por categoria (um veredito por grupo de tags) e depois consolidar em no máximo 2 mercados, ou se é uma camada nova por cima do que já existe.
5. **RF1/RF2 — nome da nova categoria de item "matched mas sem 2 lojas"** (precisa de um `HintKind`/frase própria, mesmo padrão de `docs/design/...` anteriores) **e como corrigir o desempate de RF1.1** — um critério simples (preferir o `kind` cujas palavras batem exatamente com o termo inteiro, antes de cair no score por palavra) resolveria o caso medido (`tomate` teria prioridade sobre `passata de tomate`), mas precisa checar contra os 98 `kind` reais antes de fixar, mesma disciplina de todo cutoff já medido neste projeto. Vale também registrar o `items`/os kinds resolvidos de cada chamada de `compare_stores` em algum log (hoje só `bot_turn` grava o texto cru da pessoa) — foi a falta desse rastro que impediu reproduzir com certeza o "4 dos 6" da lista de 20 itens nesta sessão.
6. **Escopo de RF3 (inverter ordem)**: só `compare_stores`/veredito de lista, ou também a comparação de 1 produto entre lojas (`search_prices` com highlight, quando há 2+ registros)? Os screenshots só cobrem o caso de lista.

## Próximo passo

`/sc:design` para decidir os números (corte percentual, teto de mercados), o mecanismo de categoria em RF6, e como a ação nova de RF4 se encaixa no menu fechado de ações do agente. Nada foi implementado nesta sessão.
