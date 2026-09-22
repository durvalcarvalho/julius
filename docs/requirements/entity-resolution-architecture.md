# Requisitos: da correção pontual pra arquitetura de resolução de entidade — três frentes

> Descoberta via `/sc:brainstorm`, 2026-09-22, em cima de `claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md`. O usuário leu a pesquisa e pediu as três alavancas de uma vez: camada semântica sob o casamento lexical, memória de conversa estruturada, e formalizar a pergunta de esclarecimento como arquitetura permanente (não mais "mais um patch").

## Por que três frentes, não uma

A pesquisa mostrou que os bugs das duas rodadas de monkey test (picanha/pinha, queijo/pão de queijo, coca/pepsi, o loop de quantidade, o "grounding gap" da memória) não são falhas isoladas — são todos sintomas de três peças de uma arquitetura padrão da indústria (blocking→matching, slot-filling com desambiguação, grounding/faithfulness em geração) que o projeto já está construindo, uma de cada vez, reagindo a incidente. As três frentes abaixo são essas três peças, nomeadas explicitamente em vez de esperar o próximo bug pra descobrir de novo que existem.

**Sobre orçamento e proporção — vale para as três frentes, não repetido em cada uma:** este é um catálogo de uma pessoa (hoje ~300 produtos, 99 `kind`s), orçamento de IA de US$5/mês, já gastando na casa de centavos por rodada de teste. Nenhuma das três frentes deve assumir infraestrutura de escala industrial (banco vetorial, serviço de embedding hospedado, pipeline de re-treino) sem medir primeiro que o volume atual justifica — mesma disciplina que already existe pra cada cutoff deste projeto.

---

## Frente A — Camada semântica sob o casamento lexical

### Causa raiz (recapitulando a pesquisa, não repetindo)

`_name_score`/`rapidfuzz` mede sobreposição de caracteres, não significado. Isso resolve typo (`pcanha`→`picanha`) e abreviação (`refri`→`REFRIGERANTE`) bem, mas não tem como distinguir "a mesma coisa escrita diferente" de "coisas diferentes que parecem com a mesma coisa" — são o mesmo padrão de bits pro scorer. A pesquisa mediu que a indústria (correspondência de produto em e-commerce, entity resolution em bancos de dados) resolve isso com uma camada semântica *abaixo* do casamento lexical, nunca removendo o lexical (que continua sendo o filtro barato de primeira passada — "blocking").

### Requisitos funcionais

**RF1 — Medir as duas variantes antes de escolher uma.** O usuário pediu explicitamente pra não decidir agora entre "LLM como resolvedor" (aprofundar `kind_candidates`/vocabulário no prompt, já em produção) e "embeddings de texto pro nome de produto" (novo). A medição precisa cobrir, contra o catálogo real:
  - **Cobertura do problema já medido**: os 50 pares de colisão que a varredura de `_name_score` encontrou (`picanha`/`Pinha`, `queijo`/`pão de queijo` etc.) — cada variante resolve quantos corretamente, sem quebrar nenhum caso de typo/abreviação já documentado como necessário (`arros`→`Arroz`, `pcanha`→`Picanha`, `refri`→`REFRIGERANTE`)?
  - **Custo por chamada**: tokens/latência (LLM) vs. custo de gerar+comparar vetores (embeddings) — nos dois casos, por *busca*, não por catálogo inteiro (o catálogo é recalculado raramente, buscas acontecem toda hora).
  - **Dependência nova**: LLM-como-resolvedor não adiciona nada (já é chamada existente); embeddings adiciona um modelo (local ou API) — qual, e o que isso muda no `pyproject.toml`/orçamento.
  - **Escala esperada**: como cada variante se comporta se o catálogo crescer uma ordem de grandeza (o gatilho que o próprio projeto já usa pra revisitar a decisão de não usar busca semântica, documentado em CLAUDE.md).

**RF2 — A camada semântica escolhida substitui listas de exceção *futuras*, não obrigatoriamente as existentes.** `KIND_NOISE_WORDS`, `CONNECTIVE_WORDS`, os cutoffs já calibrados continuam funcionando como o filtro barato de primeira passada (blocking) — a camada semântica entra como o que hoje é `_match_kind_via_product`/`kind_candidates`: o que roda quando o lexical não resolve com confiança. Não é reescrever o que já funciona, é parar de escrever a *próxima* lista de exceção quando o próximo caso aparecer.

**RF3 — Cobre tanto resolução de `kind` quanto de nome de produto.** Hoje só `match_kind` tem fallback (`_match_kind_via_product`); `matching_product_ids` (usado por `search_prices` direto) não tem nenhum — é por isso que "picanha"/"Pinha" foi corrigido com um guard de comprimento de palavra (um remendo a mais) em vez de resolvido pela raiz. A camada semântica, seja qual for a variante escolhida, deveria cobrir os dois pontos de entrada.

### Requisitos não funcionais

**RNF1 — Medição publicada antes de qualquer código.** Mesma disciplina de todo cutoff deste projeto: números contra o catálogo real, não estimativa, num documento (ou seção do `/sc:design`) antes de implementar.

**RNF2 — Não regride o caminho CLI.** `julius mercados comparar`/`consultar` não dependem de chamada de IA nem de embeddings hoje (exceto o fallback já existente de `consultar` vazio); isso não pode mudar sem decisão própria.

**RNF3 — A guarda de dinheiro e a guarda de veredito continuam intocadas.** Nenhuma correspondência de entidade, de qual variante for, pode virar fonte de valor em R$ ou veredito não verificado.

---

## Frente B — Memória de conversa estruturada (fechar o "grounding gap")

### Causa raiz (recapitulando a pesquisa)

O bot afirmou "você começou perguntando de cebola" quando a primeira pergunta real (banana) já tinha saído de `HISTORY_TURNS=3`. A pesquisa mostrou que isso é um "grounding gap" documentado na literatura de 2023-2025: reforçar o prompt não resolve, porque o modelo genuinamente não tem acesso à informação — não é falta de instrução, é falta de dado. Testado nesta sessão: o reforço de prompt (`BOT_PROMPT_VERSION` 5) não mudou o comportamento numa reprodução ao vivo do mesmo caso.

**Isto é distinto, e mais estreito, do que `docs/requirements/shopping-list-conversation-context.md` já pedia** (aquele documento cobre "pergunta pendente" e "lista de compras construída aos poucos" — RF4/RF5/RF6 daquele documento, adiados 3 vezes por falta de caso medido). Esta frente cobre especificamente: **o bot nunca deve afirmar como fato algo sobre turnos que já saíram da janela de histórico.** Pode ser a mesma peça de infraestrutura (estado de conversa persistido) resolvendo os dois problemas — isso é decisão de `/sc:design`, não desta fase.

### Requisitos funcionais

**RF4 — Nunca afirmar com confiança um fato sobre um turno fora da janela de memória.** Quando a pessoa pergunta sobre algo potencialmente anterior ao que `HISTORY_TURNS` retém, a resposta correta é uma das duas: (a) reconhecer que não lembra tão longe, ou (b) genuinamente saber a resposta porque foi guardada num estado que sobrevive à rotação de `HISTORY_TURNS` — nunca apresentar a borda da janela como se fosse o início real da conversa.

**RF5 — Escopo mínimo: só os fatos que já causaram um incidente real.** Não é "lembrar a conversa inteira pra sempre" — é decidir, medido, quais fatos específicos (ex.: primeiro item mencionado na sessão, itens já cotados) valem a pena persistir fora do histórico bruto, e por quanto tempo. RF6 do documento de lista de compras (retomar assunto fora da janela) e este RF4 podem compartilhar mecanismo; a decisão de unificar ou não fica pro design.

**RF6 — Se a solução envolver estado novo, ele precisa de uma forma clara de expirar.** Mesmo princípio já aplicado a `PendingWrite` (TTL) — um estado de conversa que nunca expira é o mesmo tipo de bug que motivou o TTL de 300s ali.

### Requisitos não funcionais

**RNF4 — Medir o custo antes de aumentar `HISTORY_TURNS` como alternativa.** Se a solução escolhida no design for "manda mais histórico" em vez de "guarda um resumo estruturado", o custo em tokens por turno precisa ser medido (mesma disciplina do RNF2 do documento de lista de compras, nunca resolvida por lá).

**RNF5 — Reabre RNF de projetos anteriores, não os contradiz.** v2.10 Decisão 4, v2.11 RF4, v2.13 e o documento de lista de compras já registraram o gatilho "construir estado explícito quando houver caso medido" — este é esse caso. Não é uma decisão nova solta, é a mesma decisão, agora com evidência.

---

## Frente C — Formalizar a pergunta de esclarecimento como arquitetura permanente

### Causa raiz

`resolve_product`/`resolve_store` (ambiguidade de produto/mercado) e, desde a sessão passada, `_resolve_kind` (ambiguidade de marca e de empate de `kind`) já usam o mesmo mecanismo: `ModelRetry` com as opções, o modelo pergunta, a pessoa responde, o modelo rechama. A pesquisa confirma que isso não é uma solução provisória — é a peça padrão de slot-filling com desambiguação em sistemas de diálogo há 30+ anos, e nenhum sistema maduro do campo tenta eliminar a pergunta (ambiguidade genuína sempre existe). O que falta é reconhecer isso como convenção nomeada, e auditar se sobrou algum ponto do bot que ainda escolhe sozinho em vez de perguntar.

### Requisitos funcionais

**RF7 — Documentar o padrão como convenção arquitetural, não como solução pontual de cada bug.** Um registro (design doc ou seção do CLAUDE.md) nomeando: "toda resolução de entidade no bot layer que encontra 2+ candidatos plausíveis, sem um vencedor claro, pergunta via `ModelRetry` — nunca escolhe sozinho." Isso já é verdade no código; falta estar escrito como regra, não como three incidentes separados.

**RF8 — Auditar os pontos do bot que ainda escolhem silenciosamente, e decidir caso a caso se é ambiguidade genuína (deve virar pergunta) ou empate de baixo risco já aceito (fica como está).** Candidatos a revisar no design, sem pré-julgar o resultado:
  - `detect_tag` (detecção de tag em texto livre do `consultar`) — escolhe a palavra de melhor score sem alternativa; nunca fundamentado se há empate real no vocabulário de 13 tags.
  - `resolve_store` por apelido — usa `matching_product_ids`-like fuzzy; nunca medido se duas lojas colidem por nome.
  - Os empates de `kind` já aceitos e NÃO revertidos na sessão passada (ex.: exatamente-empatados-mas-com-vencedor-exato, como `tomate`/`passata de tomate`) — confirmar que continuam corretamente fora do escopo, não reabrir sem motivo novo.

**RF9 — O padrão vale pra qualquer resolução de entidade nova que o bot ganhar no futuro**, não só as que já existem — isto é o critério de aceite mais importante desta frente: a próxima ambiguidade que aparecer não deveria precisar de uma sessão de troubleshoot pra "descobrir" que a resposta é perguntar.

### Requisitos não funcionais

**RNF6 — Não reabrir ambiguidades já aceitas sem medição nova**, mesmo com o padrão nomeado — nomear a arquitetura não é licença pra aplicá-la retroativamente em todo empate que já existe (ex.: "leite" tinha 1 empate aceito, virou pergunta na sessão passada por evidência concreta; outros empates do RF8 só mudam se a auditoria achar evidência equivalente).

---

## Histórias de usuário (as três frentes juntas)

- **Como usuário**, quero que perguntar sobre um produto do jeito que eu falo naturalmente ("picanha", "queijo", "aquele biscoito") ache a coisa certa, mesmo quando a palavra colide por acaso com outra coisa do catálogo — sem eu precisar saber que existe um "corte de pontuação" por trás.
- **Como usuário**, quero que o bot nunca me diga com confiança um fato errado sobre o que eu já perguntei antes na mesma conversa — prefiro que ele diga "não lembro tão longe" a inventar.
- **Como usuário**, quando o que eu pedi é genuinamente ambíguo, quero que o bot pergunte — isso já acontece pra marca e empate de tipo, e eu quero que continue acontecendo em qualquer situação parecida que apareça no futuro, sem precisar de outra sessão de bugfix pra chegar lá.

## Critérios de aceite (rascunho, para o `/sc:design` refinar)

- Frente A: número medido de quantos dos 50 pares de colisão cada variante (LLM-resolvedor vs. embeddings) resolve corretamente, sem regredir nenhum dos casos de typo/abreviação já documentados; custo por busca de cada variante, publicado antes da escolha.
- Frente B: reproduzir o caso banana/cebola/tomate/uva e obter uma resposta que não afirma um fato falso (nem que precise ser "lembra tudo perfeitamente" — só não pode inventar).
- Frente C: documento/seção existindo nomeando o padrão; ao menos os 2-3 candidatos do RF8 avaliados explicitamente (aceito como está, ou motivo pra mudar).

## Questões em aberto para a próxima fase (`/sc:design`)

1. **Frente A**: se embeddings vencer a medição, onde os vetores vivem (arquivo ao lado do `prices.db`, coluna nova, cache em memória recalculado no start)? Qual modelo de embedding (local via `sentence-transformers` — dependência nova — ou API de terceiro)?
2. **Frente A**: se LLM-resolvedor vencer, isso substitui `kind_candidates`/`_match_kind_via_product` ou convive com eles (um se torna o fallback do outro)?
3. **Frente B**: o mecanismo é estado em memória do processo (perdido no restart, como `ChatState` já é) ou persistido em disco (sobrevive restart, mais uma tabela/arquivo pra gerenciar)?
4. **Frente B**: isto se funde com a pendência de "lista de compras conversacional" (`shopping-list-conversation-context.md` RF4-RF6) numa peça só de "estado de conversa", ou ficam mecanismos separados por serem gatilhos diferentes?
5. **Frente C**: os candidatos do RF8 — depois de auditados, algum vira ticket de implementação nesta rodada, ou fica só documentado pra próxima vez que incomodar de verdade?

## Próximo passo

`/sc:design`, uma frente de cada vez ou as três em paralelo — decisão de sequenciamento também fica pra lá. Nenhum código foi escrito nesta sessão de brainstorm.
