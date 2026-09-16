# Julius v2.1 — `consultar` em texto livre + log de consultas: requisitos

> Brainstorm de 2026-09-16 (`/sc:brainstorm`). Saída: **requisitos e questões em aberto**, não design nem código.
> Insumos: pedido do usuário (interface mais natural, tag dentro do texto livre, log de consultas pra evoluir o sistema) e o código real de `julius/services/search.py`, `julius/repositories/products.py`, `julius/cli/receipts.py`.
> Próximo passo: `/sc:research` (bibliotecas) → `/sc:design` → tickets em `docs/tickets/julius-v2/` (115+).

## 0. Ponto de partida — fatos verificados no código

| # | Fato | Evidência |
|---|---|---|
| F1 | `julius consultar leite --tag laticinio` **já funciona como interseção** hoje — não é trabalho novo. | `services/search.py::_candidate_ids` faz `ids & tagged` |
| F2 | Tag é **match exato** (`t.name = ?`), zero tolerância a erro de digitação. | `repositories/products.py::product_ids_with_tag` |
| F3 | `julius consultar leite laticinio` (duas palavras sem aspas, sem `--tag`) **já falha hoje** — `term` é `Optional[str]`, um único argumento posicional; Typer/Click recebe dois argv pra um parâmetro só. | `cli/receipts.py::search` |
| F4 | O fallback de IA em `consultar` só liga quando `tag is None` (o parâmetro crú da CLI) — nunca dispara em busca com tag, hoje. | `cli/receipts.py::_ai_fallback`, condição `tag is None` |

## 1. Objetivo

> Tornar `julius consultar` mais natural: reconhecer uma tag dentro do texto livre sem exigir `--tag`, tolerar erro de digitação também em tag (não só em nome de produto), e registrar toda consulta pra poder recalibrar o sistema com dado real de uso — mesma disciplina que já produziu `MATCH_SCORE_CUTOFF`/`NEAR_MISS_CUTOFF` a partir dos 5 recibos reais.

## 2. Requisitos funcionais

| # | Requisito |
|---|---|
| RF1 | `julius consultar hortifruti` funciona sem `--tag`: um trecho do texto livre que bate com uma tag conhecida (acima de um corte dedicado) é tratado como filtro; o restante continua sendo termo de produto. `--tag` continua existindo, sem mudança de comportamento pra quem já usa (F1). |
| RF2 | Tag passa a tolerar erro de digitação (fat-finger), igual ao nome de produto — hoje é match exato (F2). Corte dedicado, medido contra as tags reais, não reaproveitado de `MATCH_SCORE_CUTOFF`/`NEAR_MISS_CUTOFF` por suposição. |
| RF3 | Tag detectada + termo restante = **interseção** (mesma semântica do `--tag` explícito). Se vier vazia, a busca refaz automaticamente como termo puro (ignorando a tag detectada) — "determinístico primeiro, mais permissivo depois". |
| RF4 | Flag de opt-out: força tratar o texto inteiro como termo de produto, mesmo que uma palavra bata com uma tag conhecida. |
| RF5 | Toda chamada de `consultar` grava um registro (termo, tag explícita, tag auto-detectada, nº de resultados, se caiu em fallback de IA, timestamp), pra depois entender buscas que falham e ter analytics simples de uso — as duas finalidades escolhidas pelo usuário; não é auditoria completa (não precisa das linhas de resultado inteiras). |

## 3. Requisitos não funcionais

- **N1** Zero custo de IA nesse caminho — detecção de tag é determinística (mesma família de ferramenta já usada pra nome de produto).
- **N2** Comportamento atual (`--tag` explícito, `-n`, termo puro) não muda — as regras novas são estritamente aditivas.
- **N3** Escopo só de `julius consultar`; outros comandos com tag (`produtos listar --tag` etc.) ficam de fora.
- **N4** Log nunca atrasa perceptivelmente uma consulta nem lança exceção.
- **N5** Zero dependência nova.

## 4. Decisões do usuário (Q&A do brainstorm)

| Questão | Decisão |
|---|---|
| Tag auto-detectada + termo: filtro (interseção) ou ampliador (união)? | **Interseção** — mesmo comportamento que `--tag` já tem. |
| Interseção vazia: o que a busca faz? | **Tenta de novo como termo puro**, ignorando a tag detectada, antes de desistir. |
| Log de consultas serve pra quê? | **Entender buscas que falham** (recalibrar cortes com dado real) **e analytics de uso** (produtos/tags mais consultados) — não auditoria completa das linhas de resultado. |

## 5. Histórias de usuário

- Como usuário, digito `julius consultar hortifruti` e vejo os produtos daquela categoria, sem lembrar de `--tag`.
- Como usuário, digito `julius consultar leite laticinio` (mesmo com "laticinio" no singular, ou com uma letra trocada) e recebo a interseção certa.
- Como usuário, tenho uma forma de dizer "isso é nome de produto, não tag" quando a detecção erra.
- Como usuário (dono do sistema), depois de semanas de uso, olho um log e respondo "quais das minhas buscas não acharam nada" sem precisar lembrar de nada na hora da busca.

## 6. Questões em aberto (para `/sc:design`)

| # | Questão | Recomendação |
|---|---|---|
| Q1 | Corte de detecção de tag em texto livre — precisa ser medido, não escolhido. | Medir contra as 13 tags reais + descrições reais dos fixtures antes de fixar o número. |
| Q2 | Como reabrir o fallback de IA quando a tag foi auto-detectada e descartada (RF3), sem reabrir quando `--tag` foi explícito (F4)? | Resolver no design — precisa de um sinal diferente de "tag is None" cru da CLI. |
| Q3 | Nome da flag de RF4 e formato do log (JSONL vs. tabela SQL)? | Nenhum dos dois é decisão deste documento. |
| Q4 | Tokenização de múltiplas palavras — como o texto livre chega tokenizado? | Verificar se o Typer já resolve isso de graça (ver F3) antes de escrever qualquer parser manual. |

## 7. Fora do escopo desta rodada

Comando de analytics dedicado (`julius consultas relatorio`) · tag multi-palavra · cache de respostas · novo `HintKind` de transparência (avaliar no design se realmente precisa, à luz do princípio "nunca dica em saída boa").
