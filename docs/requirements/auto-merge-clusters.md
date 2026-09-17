# Julius — fusão automática de duplicatas com alta confiança: requisitos

> ♻️ **REABERTO EM 17/09/2026 — ver `docs/requirements/auto-merge-and-unit-price-v2.4.md` §2.A.** A medição que derrubou esta proposta foi refeita contra o catálogo já curado pela v2.3: dos mesmos 19 candidatos, a IA confirma **2**, ambos corretos, e **rejeita** o `Alho` ↔ `Pão de Alho` que antes vinha com 1,00. `RF1`, `RF3`–`RF6` voltam a valer; `RF2` (corte de confiança) foi **substituído** por "a IA confirmar, sem limiar", porque os dois acertos vieram com 0,70/0,80 e o falso positivo com 1,00. O aviso original fica abaixo como registro do que era verdade em 16/09.
>
> ⚠️ **(16/09) RESOLVIDO CONTRA ESTA PROPOSTA — ver `docs/requirements/comparability-closure.md` §3.** A rodada de fechamento (mesmo dia) rodou `duplicate_candidates` no catálogo inteiro pela primeira vez: 19 pares acima do corte, no máximo 2 defensáveis, e o pior falso positivo (`Alho` ↔ `Pão de Alho Pradella 400g Picante`) tira a **nota máxima, 1,00** — nenhum corte de similaridade é seguro. Decisão do usuário: **agrupar sem fundir**. `RF1`–`RF6` abaixo estão **sem efeito**; a reversibilidade do merge (RF1) deixou de ser pré-requisito porque fusão saiu do caminho automático. O documento fica como registro do raciocínio e das evidências, não como especificação a implementar.

> Brainstorm de 2026-09-16 (`/sc:brainstorm`), continuação da sessão anterior. O usuário rejeitou explicitamente o modelo "sugere, humano confirma" pra duplicatas: quer que o sistema funda sozinho quando tiver alta confiança, notifique o que fez, e — se for preciso desfazer — que desfazer seja simplesmente possível. Proposta do próprio usuário: "os hints agora começam a ser 'ações inteligentes' que vão ser executadas" (inverter o padrão atual — fazer, e avisar — em vez de sugerir e esperar confirmação).
> Insumos: resposta do usuário; código real de `julius/services/catalog.py::merge_products`, `julius/domain/models.py::MergeSuggestion`, `julius/services/curation.py::judge_duplicates`; achados desta mesma sessão (`docs/requirements/cross-store-price-comparison.md`, F4: `TOMATE TREBESCHI 250G DUO` misturado numa busca de "tomate" com tomate a granel, produtos genuinamente diferentes).
> Próximo passo: `/sc:design` → tickets em `docs/tickets/julius-v2/` (117+).

## 0. Ponto de partida — fatos verificados

| # | Fato | Evidência |
|---|---|---|
| F1 | **A premissa "se quiser desfazer, é só desfazer" não é verdade hoje.** `merge_products` reatribui SKUs e preços pro destino e depois **apaga a linha de origem** (`products.delete_product(conn, source_id)`) — sem guardar em nenhum lugar quais `(store_cnpj, product_code)` migraram, nem o `canonical_name`/tags/conteúdo que a origem tinha e não foram copiados. `fundir ORIGEM DESTINO` não tem como desfazer sozinho: `ORIGEM` não existe mais depois do merge. | `julius/services/catalog.py:33-45`. |
| F2 | **"Alta confiança" não tem número calibrado hoje.** `MergeSuggestion.confidence` é um float que a própria IA escreve sobre o próprio julgamento — nada no repositório mede isso contra pares reais conhecidos, diferente de `MATCH_SCORE_CUTOFF`/`NEAR_MISS_CUTOFF`/`TAG_MATCH_CUTOFF`/`DUPLICATE_CANDIDATE_CUTOFF`, cada um com docstring citando uma medição real. O exemplo do import de hoje: banana prata ≈ banana prata extra veio com confiança 0.80 — plausível, mas sem nenhum teste que diga se 0.80 é "alto" o suficiente pra confiar sem perguntar. | `julius/domain/models.py:105-108`; saída real do `julius importar` desta sessão. |
| F3 | **Falso positivo não é hipotético — já reconfirmado hoje.** A busca "tomate" (sessão anterior) trouxe `TOMATE TREBESCHI 250G DUO` (R$ 9,90/UN ≈ R$ 39,60/kg) junto de `TOMATE ITALIANO ... kg` (R$ 11,89–14,99/kg) — produtos genuinamente diferentes que compartilham a palavra "tomate". O próprio `CLAUDE.md` já documentava o mesmo risco com `SUCO ... UVA` vs `... LARANJA` e `PEPSI PET 2L` vs `PET 1L`. Um merge automático errado mistura essas duas séries de preço numa só, silenciosamente — e todo `highlight`/`consultar` futuro passa a calcular em cima do dado misturado, sem nenhum sinal de que aconteceu. | `docs/requirements/cross-store-price-comparison.md` F4; `CLAUDE.md`, seção "Identidade de produto e busca". |
| F4 | **Existe precedente real pro padrão pedido** — só que aplicado a uma ação bem mais barata de errar. `curation.propose`/`enrich_products` já aplica nome legível e categoria automaticamente quando há um único candidato conhecido, perguntando só quando ambíguo. A diferença: um nome errado é visível numa linha de saída e corrigido com `renomear`; um merge errado mistura dado agregado (preço) de forma que não fica visível até alguém notar um preço "estranho" no meio do histórico. | `CLAUDE.md`, seção "Camada opcional de IA" ("a IA grava o reversível, nunca o irreversível"); `julius/services/curation.py::propose`. |
| F5 | **O que o usuário descreve como "clusters que são comparados juntos" já tem, em parte, uma saída sem apagar nada.** `_highlight_and_trim` (`services/search.py:152`) já computa `lowest`/`highest` sobre tudo que um termo/tag casa, **independente de `product_id`** — Cebola/Tomate aparecem comparados hoje porque foram fundidos (catálogo), mas o cálculo de "quem é mais barato" em si não depende de fusão, depende só de aparecerem na mesma busca. | `services/search.py:152-165`; saída real de `julius consultar cebola` (sessão anterior). |

## 1. Objetivo

Tirar do usuário a tarefa manual de rodar `julius produtos fundir` par a par: quando o sistema tiver confiança suficiente de que dois produtos são o mesmo (mesma loja ou entre lojas), fundir automaticamente, avisar o que foi feito e por quê, e permitir desfazer se a fusão estiver errada. Isso estende o mesmo padrão que já existe pra nome/categoria (F4) — a diferença é o custo de errar, que é maior aqui (F3) e a ferramenta de desfazer, que hoje não existe pra merge (F1).

## 2. Requisitos funcionais

| # | Requisito |
|---|---|
| RF1 | **Pré-requisito, não detalhe**: o mecanismo de merge precisa passar a ser de fato reversível — preservar o suficiente (quais SKUs vieram de onde, o que a origem tinha) pra uma fusão errada poder ser desfeita sem SQL manual. Sem isso, RF4/RF5 abaixo não têm como ser cumpridos de verdade (F1). |
| RF2 | Um corte de confiança decide "alta confiança o suficiente pra fundir sem perguntar" — combinando, no mínimo, a similaridade de texto determinística já usada (`DUPLICATE_CANDIDATE_CUTOFF`) e o veredito da IA (`same_product`/`confidence`). O corte precisa ser medido contra pares reais antes de valer — mesmo padrão de medição que todo outro cutoff do projeto já segue (F2). |
| RF3 | Quando o corte é atingido: fundir automaticamente, dentro do fluxo normal (`importar`/`produtos revisar`) — sem perguntar. |
| RF4 | Imediatamente após fundir automaticamente: imprimir o que foi feito (quais dois produtos, qual sobreviveu, por quê — reaproveitando o `rationale` que a IA já gera) **e o comando exato pra desfazer**. |
| RF5 | Abaixo do corte: comportamento de hoje continua — imprime o `fundir` sugerido, nunca roda sozinho. |
| RF6 | O "desfazer" prometido em RF4 precisa ser um comando que realmente funciona — não uma sugestão que falha porque a origem já foi apagada (amarra direto com RF1). |

## 3. Requisitos não funcionais

- **N1** O merge automático continua "tudo ou nada" — nenhuma fusão parcial em caso de erro no meio do processo (mesma garantia que `merge_products` já tem hoje, numa transação só).
- **N2** Custo de IA continua dentro do orçamento existente (`ai_usage`/`JULIUS_AI_BUDGET_USD`) — rodar a varredura de catálogo inteiro (`cross-store-price-comparison.md`, RF1/Q5) e julgar cada par continua contando como chamada paga.
- **N3** Nenhuma mudança no comportamento de `consultar`/`search_prices` — isso é só sobre quando/como um merge acontece, não sobre como o resultado é exibido depois.

## 4. Decisões do usuário (Q&A do brainstorm)

| Questão | Decisão |
|---|---|
| Sugerir e esperar confirmação, ou agir e notificar? | **Agir e notificar** — "se tem uma alta confiança que algo tem que ser fundido, só funda e notifique o usuário". |
| Como desfazer, se a fusão automática errar? | O sistema deve sugerir o comando de desfazer junto da notificação — "se ele quiser desfazer, sugira o comando". (Achado desta sessão, ainda não visto pelo usuário: esse comando não existe de fato hoje — ver F1/RF1.) |
| Isso vale só pra duplicatas, ou pra hints em geral? | Enunciado como princípio geral pelo usuário ("os hints agora começam a ser ações inteligentes") — mas só o caso de duplicatas foi detalhado nesta rodada; ver Q4. |

## 5. Histórias de usuário

- Como usuário, depois de importar, quero que produtos claramente iguais (mesma loja ou entre lojas) já apareçam fundidos, sem eu precisar copiar/colar um comando `fundir` toda vez que a IA sugerir.
- Como usuário, se uma fusão automática estiver errada, quero um comando pronto pra desfazer — não quero editar o banco na mão.
- Como usuário, quero ver o que foi fundido automaticamente e por quê, mesmo sem ter pedido, pra poder auditar depois se alguma coisa parecer errada num `consultar`.

## 6. Questões em aberto (para `/sc:design`)

| # | Questão | Observação |
|---|---|---|
| Q1 | Como tornar o merge reversível (RF1)? Não apagar a linha de origem (soft-delete) e/ou gravar um registro do que mudou (tabela de histórico de merge, ex.: `merge_log(source_id, target_id, skus_moved, source_snapshot, ...)`)? | Bloqueante pra RF4/RF6 — sem isso, "sugira o comando de desfazer" imprime um comando que falha. |
| Q2 | Qual o corte de confiança exato (RF2), e medido contra o quê — os pares reais já vistos (banana 0.80, uva 0.80, tomate/cebola que já foram fundidos manualmente) mais alguns falsos positivos de propósito (Trebeschi, Suco Uva/Laranja hipotético)? | Mesmo exercício de medição que já produziu `MATCH_SCORE_CUTOFF=70`/`TAG_MATCH_CUTOFF=75` — precisa de dado real, não de um número escolhido de cabeça. |
| Q3 | "Clusters comparados juntos" (palavras do usuário) precisa ser uma fusão de catálogo (destrutiva, RF1) ou basta um agrupamento só pra comparação, sem apagar nada (F5 já mostra que o cálculo de mínimo/máximo não depende de fusão)? | São duas soluções bem diferentes pro mesmo pedido — uma muda o catálogo permanentemente, a outra não muda nada, só afeta o que aparece junto numa busca. Vale decidir antes do design, porque muda o resto da lista de requisitos. |
| Q4 | O princípio "hints agora são ações executadas" vale só para duplicatas (RF3) ou o usuário quer isso pra outros `HintKind` também (ex.: `SAME_CHAIN_BRANCHES`, `FIRST_IMPORT_NAME_STORES`)? | A maioria dos outros hints hoje não tem uma "ação" óbvia pra executar sem intervenção humana (dar apelido de mercado exige escolher o texto) — se o usuário quiser isso mais amplo, é uma rodada de brainstorm separada, não um detalhe deste documento. |
| Q5 | Precisa de um jeito de desligar o merge automático (flag/env var), dado que é uma mudança grande de comportamento — ou fica sempre ligado por padrão assim que configurado? | Comparar com o padrão já usado pra IA em geral (tudo opt-in via `JULIUS_AI_*`) — aqui a pergunta é se precisa de um opt-in *adicional*, específico pra merge automático, separado de "IA está configurada". |

## 7. Fora do escopo desta rodada

Aplicar "hints como ações" a qualquer `HintKind` que não seja duplicata (fica pra Q4 decidir se abre outra rodada); índice de preço por mercado e padrão por dia da semana (já cobertos em `cross-store-price-comparison.md`, sem relação direta com fusão automática); qualquer merge automático rodando **sem** o mecanismo de RF1 (reversibilidade) implementado primeiro — não é uma opção válida de entrega parcial, é a pré-condição.
