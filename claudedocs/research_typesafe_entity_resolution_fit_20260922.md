# Pesquisa: o TypeSafe/Jev resolveria as fragilidades de resolução de entidade?

> `/sc:research`, 2026-09-22. Pergunta do usuário: "tô curioso se o https://typesafe.ai/ não resolveria todas essas fragilidades do sistema" — referindo-se aos bugs de correspondência de texto (picanha/pinha, queijo/pão de queijo, coca/pepsi) e ao "grounding gap" de memória (banana/cebola) das duas últimas sessões. Este documento **não substitui** `claudedocs/research_typesafe_ai_20260921.md` (a pesquisa original, sobre TypeSafe aplicado à fusão de produtos) — estende ela pra uma pergunta diferente: a mesma ferramenta, aplicada ao problema de *entity resolution* que motivou `research_entity_resolution_lexical_matching_scaling_20260922.md` e `docs/design/entity-resolution-architecture.md`.

## Resposta direta

**Não resolve todas — resolve uma parte, com uma ressalva medida que é tão importante quanto a parte que resolve.** Rodei três experimentos reais contra a API do Jev (`JULIUS_TYPESAFE_API_KEY` já configurada neste ambiente, `TypeSafeDecisionClient` já existe no código desde a integração de fusão de produtos), usando exatamente os casos de colisão desta sessão:

| caso | pergunta ao Jev | resultado | avaliação |
|---|---|---|---|
| "picanha" vs "Pinha" (o falso positivo do fuzzy match) | Choice entre os 2 nomes | `picanha`, confiança **1,00** (prob. 1,0 vs 0,0) | ✅ Acerta, com clareza |
| "coca" (marca sem `kind` próprio) | Choice entre refrigerante/cacau em pó/chocolate | `refrigerante`, confiança **0,95** | ✅ Acerta — mas é redundante: o sistema já acerta isso hoje (`_resolve_kind`) |
| **"queijo" (genuinamente ambíguo, sem contexto extra)** | Choice entre 5 tipos de queijo reais | **`queijo_mussarela`, confiança 0,74** (prob. 0,79) | ❌ **Confiante e sem base** — não existe informação no enunciado que justifique escolher mussarela em vez de parmesão ou brie |

O terceiro resultado é o achado que muda a resposta. "Queijo tá caro a 25 reais?", sozinho, **não tem resposta certa** — é exatamente por isso que o sistema, depois do incidente real desta sessão, passou a perguntar "qual queijo?" em vez de escolher. O Jev, na mesma pergunta, não pediu mais contexto: devolveu uma escolha confiante. Isso é **a mesma classe de falha que o CLAUDE.md já documentou três vezes pro DeepSeek** (confiança autorrelatada que não reflete incerteza real) — só que, aqui, vestida de estatística derivada da distribuição de probabilidade em vez de um número que o modelo "disse" — e ainda assim errou pelo mesmo motivo: nada no `state` fornecido desambiguava a pergunta, e o modelo preencheu a lacuna com o que for mais comum no próprio treino (provavelmente mussarela é estatisticamente o queijo mais citado em português), não com uma inferência válida a partir do que a pessoa realmente disse.

## O que isso muda em relação à pesquisa anterior (`research_typesafe_ai_20260921.md`)

Aquela pesquisa mediu o Jev contra um problema diferente — **julgamento par a par** ("estes dois nomes são o mesmo produto?"), onde existe, quase sempre, uma resposta objetivamente certa a partir do próprio texto comparado (dois nomes ou são a mesma coisa ou não são). Ali o Jev se saiu muito bem: separou limpo os 13 negativos reais confirmados dos positivos sintéticos, inclusive acertando o caso onde o DeepSeek errou (`Alho` ↔ `Pão de Alho`, DeepSeek deu 1,00, Jev deu 0,02).

O problema desta sessão é estruturalmente diferente: **não é "estes dois são iguais?", é "a qual dos N este texto curto se refere?"** — uma pergunta que, quando genuinamente subespecificada (como "queijo" sozinho), não tem resposta objetiva nenhuma no texto disponível. A diferença entre os dois problemas é exatamente a diferença entre *matching* (par a par, tende a ter resposta certa) e *retrieval/desambiguação* (um-para-N, pode não ter) — a mesma distinção que a pesquisa de ontem (`research_entity_resolution_lexical_matching_scaling_20260922.md`) fez ao separar *entity resolution* de *slot-filling com desambiguação*. O Jev foi medido, ontem, no primeiro tipo de problema e foi bem. Hoje, medido no segundo tipo, replicou a falha que ele supostamente resolve.

## Onde o Jev genuinamente ajudaria (achado novo, com valor real)

O Jev **não substitui** a busca/desambiguação que o sistema já tem — mas pode reforçar exatamente o ponto que `docs/design/entity-resolution-architecture.md` deixou em aberto (Frente A, RF2, "fica para quando houver um segundo caso medido"): **detectar quando um resultado de busca é heterogêneo demais pra confiar (o formato picanha+pinha) e verificar antes de mostrar**. O primeiro experimento acima mostra isso funcionando: dado um *shortlist já produzido pelo casamento determinístico* (rapidfuzz já entrega "picanha" e "Pinha" como os 2 candidatos reais de hoje), o Jev discrimina os dois com uma confiança que é, por construção (estatística da distribuição, não autorrelato), mais confiável que pedir ao DeepSeek pra "dizer um número".

**O que isso não é**: um substituto para `matching_product_ids`/`_name_score`. O Jev não busca em 130 produtos — ele escolhe entre opções que alguém já enumerou e descreveu. Ele encaixaria **depois** do casamento determinístico, como uma segunda opinião sobre um shortlist pequeno e suspeito, nunca como a primeira camada. Isso é literalmente o desenho de "blocking → matching" que a pesquisa de ontem já descreveu como o padrão da indústria — o Jev seria a peça de "matching" (cara, mais confiável), o `rapidfuzz` continua sendo o "blocking" (barato, primeira passada).

## O que o Jev categoricamente não toca: a memória de conversa

O "grounding gap" (o bug banana/cebola, corrigido no ticket 181 desta sessão) está **fora do espaço de problemas que o Jev endereça, por desenho, não por limitação de calibração**. O `state` de uma chamada Jev é só o texto que você fornece *naquela chamada* — não existe conceito de sessão, histórico ou memória entre chamadas (confirmado na pesquisa de ontem: "State: o contexto que a pergunta é avaliada contra, texto livre" — um parâmetro por chamada, não um objeto persistente). O Jev nunca gera texto e nunca mantém estado — ele não é candidato a solução pra "o modelo esqueceu o que foi dito 5 mensagens atrás", porque essa é uma limitação de *quanto contexto foi passado pra ele*, não de *como ele decide dado o contexto que recebeu*. Isso já estava implícito na pesquisa anterior (que nem cogitou esse encaixe, porque o Jev nunca gera texto) — aqui fica explícito porque é exatamente a pergunta que o usuário fez.

## Resposta consolidada, por fragilidade

| fragilidade desta sessão | o Jev resolveria? | por quê |
|---|---|---|
| "picanha" → "Pinha" (falso positivo do fuzzy match) | **Parcialmente** — como camada de verificação sobre o shortlist que o `rapidfuzz` já produz, não como substituto da busca | Medido: discrimina bem quando o shortlist já está montado |
| "queijo" → "pão de queijo" (empate silencioso) | **Não** — a mesma classe de "confiança sem base" reaparece quando a pergunta é genuinamente ambígua | Medido agora: 0,74 de confiança numa escolha arbitrária, sem informação que a sustente |
| "coca"/"pepsi" (marca sem `kind` próprio) | **Redundante** — o sistema já resolve isso hoje via `_resolve_kind` | Medido: Jev acerta, mas não é um problema em aberto |
| Memória de conversa (banana/cebola) | **Não, por desenho** | Jev não tem conceito de estado entre chamadas |
| "a quantidade de bugfixes só aumenta" (a preocupação original) | **Não muda a resposta da pesquisa de ontem** | Jev não é uma camada semântica de retrieval (não substitui embeddings nem o LLM-como-resolvedor já em uso) — é uma ferramenta de *classificação com confiança calibrada* sobre um conjunto já conhecido de opções, útil como uma segunda camada de verificação, não como a arquitetura inteira |

## Recomendação (para decisão humana, não implementada aqui)

Não adotar o Jev como resposta geral às fragilidades de resolução de entidade — a pesquisa de ontem já rejeitou embeddings pelo mesmo tipo de motivo (ganho real, mas estreito, contra uma dependência/provedor novo), e o Jev tem o motivo adicional de replicar, na pergunta genuinamente ambígua, a exata falha que o projeto já gastou três medições pra evitar no DeepSeek. O único encaixe com evidência real dos dois lados (esta pesquisa e a de ontem) é **usar o Jev como segunda opinião sobre um shortlist pequeno e já produzido pelo casamento determinístico** — precisamente o RF2 que `docs/design/entity-resolution-architecture.md` já tinha deixado em aberto esperando "um segundo caso medido". Se esse RF2 for retomado, o Jev (não o DeepSeek) é a escolha mais bem fundamentada pra fazer a verificação — mas isso é uma decisão de design nova, não uma consequência automática desta pesquisa.

## Fontes

- `claudedocs/research_typesafe_ai_20260921.md` (pesquisa original, mecanismo do Jev e medição contra fusão de produtos — não refeita aqui, só referenciada)
- Experimentos ao vivo desta pesquisa: `julius.infra.decision_client.TypeSafeDecisionClient.ask_choice`, três chamadas reais, `POST /v1/systemone`, 2026-09-22
- [typesafe.ai](https://typesafe.ai/) (página inicial, lida agora — confirma o mecanismo já documentado ontem via `docs.typesafe.ai`; não menciona recuperação de informação, busca ou desambiguação como capacidade destacada)
- `docs/design/entity-resolution-architecture.md`, `claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md` (a pesquisa/design que catalogou as fragilidades avaliadas aqui)
