# Requisitos: o veredito de compra passa a pesar quantidade, não só percentual

> Descoberta via `/sc:brainstorm`, 2026-09-19. Dois screenshots reais anexados (a mesma conversa do acém a R$40 e a R$50, já documentada como o exemplo que fechou RF4/RF5 de `docs/design/shopping-verdict-shape.md`/v2.11). O pedido novo não é sobre esse exemplo em si — é sobre o que ele esconde: o corte fixo de 15% que decide esse veredito hoje trata R$5 e R$500 de diferença real do mesmo jeito, porque nunca sabe quanto a pessoa vai comprar.

## Causa raiz — o que já existe e por que não basta

`services/comparison.py::check_price` (linha 196) já compara um preço visto ao vivo contra o mínimo já registrado e devolve sim/não — é `LIVE_PRICE_TOLERANCE_PCT = 15.0` (linha 182), constante isolada, documentada no próprio design como "palpite conservador" com só 2 pontos de dado (~11% e ~42%). `services/comparison.py::shopping_verdict` (linha 152), usado por `compare_stores` (`bot/actions.py`), faz o mesmo tipo de corte para lista de compras: conta vitória por `kind`, nunca por valor economizado, e fecha em "compra em X" sem saber se X são 200g ou 14kg.

**Os dois mecanismos respondem "qual % é melhor", nunca "vale a pena ir".** O usuário trouxe o caso que separa as duas perguntas: 14% de diferença numa compra de 14kg de carne é uma diferença real em reais (o suficiente pra valer trocar de mercado); os mesmos 14% em meio quilo são R$5–10, que não pagam o deslocamento. O corte percentual sozinho nunca vai distinguir os dois casos, porque quantidade não entra em nenhuma conta hoje — nem em `check_price` nem em `shopping_verdict`.

## Objetivo esclarecido (decisões já tomadas nesta sessão, com o usuário)

1. **Escopo — os dois fluxos.** Tanto `check_price` (preço único visto ao vivo) quanto o veredito de lista de compras (`compare_stores`/`shopping_verdict`) passam a considerar quantidade antes de fechar a recomendação.
2. **Base do corte — diferença em reais estimada**, não só percentual: `diferença_percentual × preço × quantidade informada` vira um valor em R$; é esse valor (não o percentual sozinho) que decide se vale trocar de mercado.
3. **Quando perguntar — pula nos extremos.** Diferença claramente pequena (ex.: alguns reais mesmo em quantidade razoável) responde direto, sem perguntar nada. Diferença claramente grande responde direto também. A pergunta de quantidade só aparece na faixa do meio, onde a resposta muda dependendo de quanto a pessoa vai comprar — é exatamente o comportamento do exemplo do usuário: "informação + pergunta; usuário responde; Julius dá a palavra final".
4. **Loop/fallback — repete com limite de tentativas.** Se a pessoa não responder a pergunta de quantidade, ou responder algo sem relação, Julius insiste até um número limitado de vezes; esgotado o limite, cai num veredito conservador assumindo quantidade pequena (mesmo espírito de "sem dado suficiente, decide pelo caminho que não superestima a economia").

## Requisitos funcionais

**RF1 — `check_price` pergunta quantidade antes do veredito, quando a diferença cai na faixa intermediária.** Hoje ele responde sim/não na hora, sempre. Passa a: (a) se a diferença estimada é claramente pequena ou claramente grande em qualquer quantidade plausível, responde direto, como hoje; (b) caso contrário, responde com o fato (preço visto vs. referência, igual hoje) **mais uma pergunta de quantidade** ("você vai comprar quantos kg?") antes de dar a palavra final — é a estrutura literal do exemplo do usuário ("bem você já conseguiu comprar por R$35,00; você vai comprar quantos kg?").

**RF2 — o veredito de lista de compras (`shopping_verdict`) também pode pedir quantidade, não só contar vitórias por tipo.** Quando o resultado de "quem ganha essa categoria" depende de quanto será comprado (ex.: toda a compra do mês de carnes vs. um corte avulso), a resposta não fecha direto — mesma lógica do RF1, adaptada a lista: um item, ou uma categoria inteira, pode entrar na faixa intermediária e pedir quantidade antes do "compra em X" final.

**RF3 — o corte que decide "vale a pena" é sobre reais estimados, não sobre percentual isolado.** `diferença_percentual × preço_de_referência × quantidade` dá um valor em R$; esse valor (não o percentual bruto do RF4/RF5 atual) decide o lado do corte. Isto não substitui o cálculo de `diff_pct` que `check_price` já faz (a fonte do percentual continua a mesma, código já existente) — adiciona uma multiplicação por quantidade em cima do que já é fato calculado.

**RF4 — a pergunta de quantidade tem loop com limite, nunca trava esperando pra sempre.** Sem resposta (ou resposta fora do assunto) depois de um número limitado de tentativas, Julius fecha com um veredito conservador (assume quantidade pequena, decide pelo lado que não manda a pessoa atravessar a cidade por pouco dinheiro) — nunca fica repetindo a pergunta indefinidamente nem trava o chat.

**RF5 — nenhum cálculo de reais é feito pela IA.** Mesma disciplina de sempre neste projeto (guarda de dinheiro): `diferença_percentual`, `preço`, `quantidade` e o produto dos três são fatos calculados em código antes de chegar à persona; a IA só narra o resultado e formula a pergunta de quantidade quando o código decidir que ela é necessária — nunca decide sozinha se pergunta ou não, nem soma/multiplica por conta própria.

## Requisitos não funcionais

**RNF1 — isto reabre RF4/RF5 de `docs/design/shopping-verdict-shape.md` (v2.11), já implementado e em produção.** `LIVE_PRICE_TOLERANCE_PCT = 15%` não é descartado como sinal (o percentual continua entrando na conta), mas deixa de ser, sozinho, o critério de decisão — passa a ser um dos dois fatores (junto de quantidade) que formam o corte em reais do RF3. Registrar isto evita que uma sessão futura trate os dois cortes como coisas independentes que podem divergir.

**RNF2 — mesma guarda de dinheiro de sempre.** Nenhum valor citado ao usuário (preço, diferença, estimativa em reais) pode vir de conta feita pela IA — sempre fato pronto calculado em `services/comparison.py` ou equivalente, mesma disciplina de `comparison_facts`/`shopping_verdict`/`check_price` já existentes.

**RNF3 — não regredir os casos já medidos da rodada real de v2.11/v2.12.** O roteamento e a estrutura de resposta (abre com a decisão, fecha com o porquê — RF3 de v2.11) continuam valendo; esta mudança altera *quando* a decisão pode ser adiada por uma pergunta, não a ordem da resposta quando ela já pode ser dada.

## Histórias de usuário

- **Como usuário fazendo a compra do mês**, ao perguntar se um preço de carne está bom, quero que o Julius considere que vou levar bastante quantidade antes de dizer se vale ir a outro mercado.
- **Como usuário comprando pouca quantidade**, não quero ser mandado pra outro mercado por uma diferença de R$5–10 que a viagem não paga.
- **Como usuário**, se o Julius me perguntar quantidade e eu não responder ou falar de outra coisa, quero que ele não fique travado nem repita a pergunta pra sempre — que ele decida com o que tem.

## Critérios de aceite (rascunho, para o `/sc:design` refinar com números)

- Reproduzir o caso do usuário: acém a R$40 (14% acima do mínimo de R$35) — em quantidade pequena (ex.: 1kg), a resposta não manda trocar de mercado; em quantidade grande (ex.: 14kg), a resposta muda para "vale a pena".
- Uma diferença claramente pequena (poucos reais mesmo em quantidade generosa) nunca dispara a pergunta de quantidade — responde direto.
- Uma diferença claramente grande (mesmo em pouca quantidade já compensa) nunca dispara a pergunta de quantidade — responde direto.
- Sem resposta à pergunta de quantidade após o limite de tentativas, o veredito fecha mesmo assim, nunca trava o chat.
- Nenhum valor em reais citado na resposta vem de conta feita pela IA — todos vêm de fato já calculado em código.

## Questões em aberto para a próxima fase (`/sc:design`)

1. **Os dois limiares que definem "extremo" (RF1/RF3)** — o piso de reais abaixo do qual nunca vale perguntar e o teto acima do qual já vale trocar de mercado em qualquer quantidade plausível. Só há os dois pontos de sempre (~11%, ~42%) mais o exemplo novo (14%/14kg); precisa medir contra o catálogo real antes de fixar número, mesma disciplina de `LIVE_PRICE_TOLERANCE_PCT` original.
2. **Quantas tentativas antes do fallback conservador (RF4)** — 1? 2? E o texto/tom da segunda pergunta, se a primeira resposta não serviu.
3. **Mecanismo do loop de pergunta pendente.** `docs/design/shopping-verdict-shape.md` já registrava esta lacuna como não verificada (`reason="ambiguous_unit"` dependendo de `HISTORY_TURNS=3` sem confirmação real) — este requisito a torna crítica: agora existe um número de tentativas explícito, que `HISTORY_TURNS=3` sozinho não modela (não conta tentativas, não sabe distinguir "resposta fora do assunto" de "resposta à pergunta"). Precisa decidir se isto finalmente justifica o estado explícito de pergunta pendente que as duas rodadas anteriores adiaram por falta de caso medido.
4. **Granularidade da pergunta em lista de compras (RF2).** Uma lista pode ter vários itens na faixa intermediária ao mesmo tempo (o exemplo do usuário — "só esse corte ou vários cortes de carne" — sugere que a resposta também depende de quantos itens/cortes compõem a compra, não só do kg de um item). Perguntar item por item numa lista de 20 itens não é a mesma conversa que perguntar uma vez "quanto no total"; qual das duas (ou algo entre elas) o desenho deve seguir fica para o `/sc:design`.
5. **Quantidade "por corte" vs. quantidade agregada da categoria.** O exemplo do usuário mistura as duas ideias (14kg de carne no total, mas potencialmente vários cortes diferentes) — se a pergunta de quantidade é por item (`kind`) ou por categoria inteira (`tag`, reaproveitando `kind_categories` de RF6/v2.11) é decisão de design, não resolvida aqui.
6. **Efeito "vale a pena pela viagem toda", não só por este item** — o usuário levantou que, mesmo com uma diferença pequena por item, ir a outro mercado pode compensar se **vários** itens da lista favorecem o mesmo mercado (soma de pequenas diferenças). Se RF3 soma savings entre itens antes de decidir, ou decide item a item, é questão de escopo pendente — o RF6 de v2.11 (agrupar por categoria, no máximo 2 mercados) já toca nisso parcialmente, mas não pondera por quantidade.

## Próximo passo

`/sc:design` para decidir os números (limiares de extremo, número de tentativas) e, principalmente, o mecanismo de pergunta pendente (questão 3 acima) — que RF4 torna, pela primeira vez neste projeto, uma dependência real e não apenas uma lacuna registrada. Nada foi implementado nesta sessão.
