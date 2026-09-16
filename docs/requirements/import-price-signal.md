# Julius — sinal de novo mínimo/máximo no `importar`: requisitos

> **Q1–Q3 fechadas em `docs/requirements/comparability-closure.md` §5** (mesmo dia), com uma mudança de escopo: o sinal compara contra o **grupo de comparação**, não só contra o `product_id` — é o que permite dizer "mais barato que na outra loja". Saída é linha por item que bateu extremo (limitada a 5), fora de `guidance.py` (é resultado, não dica), e só o caso "novo máximo" precisa de fixture sintético.

> Brainstorm de 2026-09-16 (`/sc:brainstorm`), disparado por um uso real: depois de rodar `julius importar` numa compra nova (FL 3 Costa, 46 itens), o usuário perguntou "paguei caro nessa compra?" — pergunta que o Julius não responde hoje (decisão registrada: "sem veredito automático no MVP").
> Insumos: resposta do usuário ao brainstorm; análise manual feita nesta sessão direto no `prices.db` real; código de `julius/services/search.py` (`_highlight_and_trim`) e `julius/cli/receipts.py::import_receipts`.
> Próximo passo: `/sc:design` → tickets em `docs/tickets/julius-v2/` (117+).

> **Correção (mesmo dia, brainstorm seguinte):** a linha "e só contra o mesmo produto na mesma loja (é o que `product_id` significa aqui)" — resposta dada ao usuário antes deste documento — estava errada. Ver F6: os dois itens usados como exemplo em F3 (Cebola, Tomate Italiano União) já são comparações **entre lojas**, porque o `product_id` deles já foi fundido manualmente antes desta sessão. `product_id` significa "mesmo produto, onde quer que o usuário tenha fundido" — não "mesmo produto, mesma loja". RF1 abaixo já refletia isso corretamente (compara por `product_id`, sem mencionar loja); só a prosa em volta é que subestimou o alcance. Ver `docs/requirements/cross-store-price-comparison.md` para o pedido mais amplo que essa correção destravou.

## 0. Ponto de partida — fatos verificados

| # | Fato | Evidência |
|---|---|---|
| F1 | Hoje `julius importar` só imprime `"{arquivo}: N itens novos, M já existiam"` — nenhum sinal sobre se algum preço foi bom ou ruim. | `cli/receipts.py::import_receipts`. |
| F2 | `PriceRecord.highlight` (`"lowest"`/`"highest"`/`None`) já existe e já é calculado por unidade — mas só dentro de `search_prices`, disparado por uma busca de termo, nunca no caminho de `importar`. | `domain/models.py::PriceRecord.highlight`; `services/search.py::_highlight_and_trim` (linha 152). |
| F3 | **Medição real de hoje**, banco de produção (`~/.local/share/julius/prices.db`), depois de importar a nota nova: dos 46 itens, **só 2 têm qualquer preço anterior** para o mesmo `product_id` — Cebola (R$ 7,89/kg hoje vs. R$ 9,99/kg antes) e Tomate Italiano União (R$ 11,89/kg hoje vs. R$ 14,99/kg antes); os outros 44 são primeira observação. O banco real tem só 6 notas importadas no total, em 5 lojas. | Query direta em `prices`/`products`, feita nesta sessão (ver transcript — não gravada em arquivo). |
| F6 | Os dois itens de F3 já são, na verdade, **comparações entre lojas**: `product_id` 5 (Cebola) tem SKUs em `DONA DE CASA S/A` e `FL 3 COSTA`; `product_id` 63 (Tomate Italiano União) tem SKUs em `FL 3 COSTA` e `DONA DE CASA S/A` — os R$ 9,99 e R$ 14,99 "anteriores" vieram da outra loja, fundidos manualmente antes desta sessão (o mesmo caso do tomate já registrado no `CLAUDE.md`, "Confirmação real do caso que `produtos fundir` existe para resolver"). `julius consultar cebola`/`consultar tomate`, rodado nesta sessão, já mostra as duas lojas lado a lado, com endereço, numa tabela só. | `product_skus`/`prices` reais, query feita nesta sessão; saída real de `julius consultar cebola`/`consultar tomate`. |
| F4 | O "próximo passo sugerido" já registrado no `CLAUDE.md` (rodar `julius importar ~/.local/share/julius/entrada/*.html` pra fazer o backfill) ainda não foi executado — é a causa direta de F3, não uma limitação do design. | `CLAUDE.md`, seção "Status" → "Próximo passo sugerido". |
| F5 | A justificativa original de "sem veredito automático" era "dado histórico curto por produto, qualquer cálculo estatístico seria ruído" — F3 acabou de confirmar essa premissa na prática, não a contradisse. | `CLAUDE.md`, seção "Requisitos-chave". |

## 1. Objetivo

Dar, sem inventar estatística nova, um sinal imediato no fim do próprio `julius importar`: "este item bateu um novo mínimo (ou máximo) pessoal, comparado ao que você já pagou por ele" — reaproveitando o `highlight` que `search_prices` já sabe calcular, nunca comparando unidades diferentes (UN com KG) nem contra a própria nota. "Já pagou por ele" é por `product_id`, não por loja (F6): se o usuário já fundiu esse produto entre lojas, o sinal automaticamente compara entre lojas também, de graça — nenhum requisito abaixo precisa mudar por causa disso. Isso não é reabrir "veredito automático" com estatística (média, faixa, desvio) — é expor um dado que o sistema já computa em outro lugar, no momento em que é mais útil. Em paralelo — não como código, como ação — fechar o backfill de `entrada/*.html` que falta pra esse sinal ter algo a dizer na maioria das notas.

## 2. Requisitos funcionais

| # | Requisito |
|---|---|
| RF1 | No fim de `julius importar`, para cada item recém-gravado, verificar se existe ao menos um preço anterior do mesmo `product_id`, na mesma `unit`, de uma nota diferente (mesma regra usada na análise manual desta sessão e a mesma de `_highlight_and_trim`). |
| RF2 | Quando existir histórico: sinalizar só se o preço pago **bateu um novo mínimo ou novo máximo** frente a esse histórico — mesmo critério de `highlight` (`lowest`/`highest`), não um cálculo novo. |
| RF3 | Quando **não** existir histórico prévio: nenhum sinal para esse item — silêncio é a resposta certa (evita ruído/falso "normal" onde não há base de comparação; ver F3, maioria dos itens hoje cai aqui). |
| RF4 | Itens que têm histórico mas não bateram mínimo nem máximo (preço "no meio") também não geram sinal — mesmo raciocínio de RF3, sinal é só para o que é notável. |

## 3. Requisitos não funcionais

- **N1** Zero estatística nova (sem média, desvio-padrão, percentual "X% mais caro") — só reaproveita mínimo/máximo já existente.
- **N2** Zero custo de IA — é leitura determinística de `prices`, igual à análise feita manualmente nesta sessão.
- **N3** Não muda o comportamento de `consultar`/`search_prices` — é aditivo, só no caminho de `importar`.
- **N4** Continua sem fundir, sugerir ou decidir nada sobre preço automaticamente — só relata um fato que já está no banco.

## 4. Decisões do usuário (Q&A do brainstorm)

| Questão | Decisão |
|---|---|
| Reabrir "sem veredito automático" agora, dado que 44/46 itens desta nota não têm histórico? | **Mistura de duas opções**: (a) esperar ter mais dado — rodar o backfill de `entrada/*.html` antes de esperar qualquer sinal ser útil na maioria dos itens; e (b) já construir a versão mínima que não inventa estatística nova, reaproveitando o `highlight` que já existe. Rejeitada explicitamente a opção de veredito mais elaborado (média, faixa, comparação por período) enquanto o histórico for curto. |

## 5. Histórias de usuário

- Como usuário, ao importar uma nota, se um item bateu o menor preço que já vi dele nesta loja, quero ver isso na hora, sem precisar rodar `consultar` item por item depois.
- Como usuário, se um item nunca foi visto antes (a maioria, hoje), não quero nenhuma mensagem sobre ele — quero saber que não há base de comparação, não uma opinião fabricada.
- Como usuário (dono do sistema), depois de rodar o backfill de `entrada/*.html`, quero que esse sinal automaticamente comece a aparecer com mais frequência, sem precisar mexer em código de novo.

## 6. Questões em aberto (para `/sc:design`)

| # | Questão | Observação |
|---|---|---|
| Q1 | Onde entra esse sinal na saída de `importar` — uma linha por item que bateu extremo, ou um resumo agregado ("2 itens bateram mínimo histórico: Cebola, Tomate Italiano União")? | Notas grandes (46 itens, como a de hoje) tornam "uma linha por item" potencialmente longo mesmo filtrado a só extremos — mas o volume real observado hoje (2 de 46) sugere que isso raramente será um problema. |
| Q2 | Isso é uma dica nova no sistema de `guidance.py` (`HintKind`) ou uma linha própria, fora do sistema de dicas? | O princípio 2 de "Dicas de uso" no `CLAUDE.md` diz "nunca em saída normal cheia — dica em cima de resultado bom vira ruído". Um novo mínimo é, por definição, resultado bom (ou notável) — pode não caber nos 3 gatilhos hoje permitidos (vazio, erro, primeira vez). Decidir no design se isso é uma dica, um novo tipo de saída, ou se o princípio precisa de uma exceção explícita. |
| Q3 | Precisa de um fixture sintético novo (no estilo do fixture de ovos, para preço por conteúdo) cobrindo os três casos — novo mínimo, novo máximo, sem histórico — ou os fixtures reais já bastam depois do backfill? | Medir depois do backfill (F4) antes de decidir se vale a pena um fixture sintético dedicado. |

## 7. Fora do escopo desta rodada

Veredito estatístico elaborado (média, faixa de preço, "X% mais caro que a média", comparação por período) — explicitamente adiado pelo próprio usuário até haver mais histórico; qualquer decisão automática sobre o preço (fundir, tag, etc. — já era fora de escopo, continua); comparação entre lojas diferentes para o mesmo tipo de produto (não existe sem fusão manual — mesma limitação de sempre, `product_id` é por loja).
