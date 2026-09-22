# Requisitos: camada de decisão de IA estruturada (TypeSafe/Jev, de forma defensiva)

**Status**: requisitos discutidos via `/sc:brainstorm`, 2026-09-21. Sem desenho de arquitetura nem código — próximo passo é `/sc:design`.

## Contexto e motivação

Uma pesquisa (`claudedocs/research_typesafe_ai_20260921.md`) e uma medição real contra os 20 candidatos a duplicata do catálogo de produção mostraram que o TypeSafe/Jev (perguntas tipadas Choice/Score/Noul, com `confidence` derivada estatisticamente da distribuição de probabilidade, não autorrelatada pelo modelo) acerta um caso que o DeepSeek erra: o par `Alho ↔ Pão de Alho Pradella 400g Picante` — falso positivo documentado, que o DeepSeek confirmou com confiança autorrelatada de **1,00** — saiu com `noul = 0,02` no Jev. Os outros 12 pares negativos documentados (Dry Rub, água com/sem gás, Coca-Cola Zero/original, aveia fino/regular, cortes de carne diferentes) também saíram baixos (0,02–0,15); 5 pares sintéticos obviamente idênticos saíram em 0,64–0,92.

O usuário quer aproveitar esse ganho em mais de um ponto do sistema, mas de forma **defensiva**: se o TypeSafe encarecer, sair do ar, ou surgir um concorrente melhor, ele precisa conseguir desligar ou trocar sem impacto no resto do sistema.

## Objetivos esclarecidos (via diálogo)

1. **Escopo desta rodada**: três pontos de decisão, todos do tipo "escolher 1 de N com critério fechado" — os únicos formatos que Jev atende (ele nunca gera texto livre):
   - **Fusão de produtos** (`services/curation.judge_duplicates`, hoje prompt `merge` do DeepSeek) — Noul, **já medido**.
   - **Forma da embalagem** (`suggestions.suggest_packaging`, campo `form`: unit/pack/weight/volume/unknown) — Choice, **ainda não medido**.
   - **Categoria/tag do produto** (`suggestions.enrich_products`, parte de tag) — Choice sobre o vocabulário fechado de tags — **ainda não medido**, ganho mais modesto (hoje já acerta 25/25 medido).
2. **Interface bem definida para qualquer decisão de IA futura**: pedido explícito do usuário — *"deveríamos ter uma interface muito bem definida para todos esses pontos onde entra IA, para sempre que surgir algo novo de IA a gente consiga plugar facilmente"*. Isso é maior que só "desligar o TypeSafe": é um ponto de entrada único para decisões estruturadas (Choice/Score/Noul-like), separado do que já existe para geração de texto livre (`infra/llm_client.py::LlmClient`, que continua servindo `enrich`/`packaging` (conteúdo)/`store`/`persona`).
3. **Kill switch sem impacto**: ausência de `JULIUS_TYPESAFE_API_KEY` **ou** o serviço do TypeSafe fora do ar/com erro devem produzir exatamente o mesmo comportamento — o sistema volta a se comportar como se o Jev nunca tivesse existido, sem exceção, sem bloquear nenhum fluxo. Mesmo contrato que `LlmClient`/`services/suggestions.py` já cumprem hoje para o DeepSeek.
4. **Camada de troca pronta, mesmo sem concorrente hoje**: decisão explícita do usuário, contra a recomendação inicial de YAGNI — ele prefere pagar o custo de uma interface agora a ter que reescrever depois. Precedente já existe no projeto (`LlmClient` e `ReceiptParser` são `Protocol` por antecipação de segunda implementação).
5. **Mais automação, decidido agora**: o usuário topou definir um corte de auto-fusão a partir da medição **já feita** (13 negativos documentados + 5 positivos sintéticos), sem exigir mais medição antes — override explícito da minha recomendação de esperar por positivos reais. Risco aceito conscientemente: a amostra não tem nenhum positivo real (não sintético) medido ainda.

## Requisitos funcionais

- **FR1**: Deve existir uma camada de "decisão de IA estruturada" (Choice/Score/Noul), paralela e distinta da camada de geração de texto livre (`LlmClient`) já existente. Todo ponto de negócio (`services/curation.py`, `services/suggestions.py`) consome essa camada por uma interface só — nenhum SDK ou detalhe de transporte do TypeSafe vaza para fora dela.
- **FR2**: `judge_duplicates` passa a consultar essa camada (Noul "mesmo produto?") como uma segunda fonte de julgamento, ao lado do prompt `merge` do DeepSeek.
- **FR3**: Um corte de `noul` (derivado da medição em `research_typesafe_ai_20260921.md`) autoriza fusão automática **sem revisão humana** quando ultrapassado — usando o mecanismo de fusão já reversível (`merged_into`/`produtos desfundir`), nunca um caminho novo e destrutivo.
- **FR4**: `suggest_packaging` (form) e `enrich_products` (tag) passam a consultar Choice como segunda fonte/validação quando a camada estiver disponível — sem mudar o comportamento de hoje quando ela não estiver.
- **FR5**: Falta de chave, orçamento estourado, ou falha/timeout do provedor degradam graciosamente nos três pontos — nunca lançam exceção, nunca bloqueiam `produtos revisar`/`importar`.
- **FR6**: Toda chamada (sucesso ou falha) é logada no mesmo padrão de `ai_calls.jsonl`, para permitir medir calibração ao longo do tempo — inclusive os casos reais de "sim" que faltam na amostra atual.
- **FR7**: Orçamento mensal próprio e configurável para a nova camada, cortando chamadas sozinho antes de estourar (mesma disciplina de `ai_usage`/`JULIUS_AI_BUDGET_USD`).

## Requisitos não funcionais

- **NFR1**: Zero dependência de SDK — chamada HTTP crua, mesmo padrão do cliente DeepSeek atual.
- **NFR2**: Trocar de provedor de decisão estruturada deve custar o mesmo que hoje custa trocar de provedor de LLM de texto (mudar variáveis de ambiente / reimplementar um `Protocol` pequeno) — nunca uma reescrita de `services/`.
- **NFR3**: Regra de DAG já existente do projeto continua valendo: só `infra/` conhece o transporte; `services/` só conhece a interface.
- **NFR4**: Toda automação nova habilitada por essa camada precisa ser reversível por construção — nenhum caminho destrutivo novo.
- **NFR5**: Custo mensal da nova camada é visível (log + orçamento), no mesmo lugar/formato que o DeepSeek já usa.

## Histórias de usuário / critérios de aceite

- **US1**: Como usuário, ao remover ou deixar de renovar `JULIUS_TYPESAFE_API_KEY`, quero que o sistema volte a se comportar exatamente como hoje, sem mudar mais nada.
  - AC: com a chave ausente, fusão/embalagem/tag produzem resultado idêntico ao comportamento atual (sem Jev).
  - AC: uma falha de rede/timeout do TypeSafe cai no mesmo caminho — não derruba `produtos revisar` nem `importar`.
- **US2**: Como usuário, quero ver quanto a nova camada custa e com que frequência falha, no mesmo lugar de sempre.
- **US3**: Como usuário, quero que produtos que batem um corte alto de `noul` na fusão sejam fundidos automaticamente, sem passar pela revisão manual — mas continuando reversível via `produtos desfundir`.
  - AC: o corte escolhido deixa os 13 negativos documentados abaixo dele e os 5 positivos sintéticos acima.
  - Risco aceito e registrado: nenhum positivo real (não sintético) foi medido ainda.
- **US4**: Como usuário, quero que qualquer novo tipo de decisão de IA que eu queira plugar no futuro passe pela mesma interface, sem reescrever `curation.py`/`suggestions.py`.

## Em aberto (para `/sc:design` ou decisão do usuário)

1. Quando o Jev e o DeepSeek discordarem sobre uma fusão, qual pesa mais — ou isso vira um terceiro estado ("incerto, perguntar ao usuário")?
2. A segunda opinião do Jev deve aparecer visível na tela de `produtos revisar` (dado extra), ou só influenciar o corte automático internamente, sem UI nova?
3. O corte de auto-fusão deve ser fixo no código ou parametrizável por variável de ambiente (ex.: `JULIUS_TYPESAFE_MERGE_CUTOFF`)?
4. Para embalagem e tag (itens sem medição ainda): rodar uma medição real antes de escrever critérios de aceite específicos, ou seguir com os requisitos genéricos acima e medir na fase de implementação?
5. Orçamento mensal do TypeSafe: fatia do teto atual de US$5, ou teto novo e separado?
6. Nome e localização da nova camada na estrutura de pacote (`infra/` é o candidato natural, paralelo a `llm_client.py`, mas fica para o design).

## Fora de escopo (nesta rodada)

- Roteamento do bot (`bot/agent.py`) — já mede 100% de acerto com DeepSeek, Choice sozinho não resolve a extração de argumentos, sem dor a resolver.
- Guarda `_claims_unchecked_data` — lista de frases já resolve de graça.
- Qualquer decisão que exija geração de texto livre (nome legível, narração da persona, nome fantasia do mercado) — Jev não gera texto, por desenho.
