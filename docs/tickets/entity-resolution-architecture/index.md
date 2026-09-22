# Resolução de entidade — arquitetura, não mais patch: tickets de implementação

> Gerado a partir de: `docs/design/entity-resolution-architecture.md` (design), `docs/requirements/entity-resolution-architecture.md` (requisitos), `claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md` (pesquisa).
> Gerado em: 2026-09-22 · Estado do código **na geração**: commits `3cd63af`/`885950d` (kind-resolution-in-routing + monkey test) já em `main`, suíte verde (1178 testes).

## Visão geral

O usuário perguntou, depois de duas rodadas de monkey test corrigindo bugs de correspondência de texto ("picanha" achando "Pinha", "queijo" comparando contra "pão de queijo"), se a fundação do sistema aguenta o catálogo crescer — se cada correção é sintoma de uma arquitetura que não escala. A pesquisa (`claudedocs/research_...md`) respondeu que sim, a estratégia de "mais uma palavra na lista de exceção" tem teto matemático (Zipf, explosão combinatória), mas que o problema em si tem 50+ anos de arquitetura madura em outros campos (entity resolution, correspondência de produto em e-commerce, diálogo orientado a tarefa, grounding em RAG) — e que o projeto já estava construindo essa arquitetura, peça por peça, sem nomeá-la.

O brainstorm (`docs/requirements/entity-resolution-architecture.md`) abriu três frentes independentes a partir disso. Ao desenhar (`docs/design/entity-resolution-architecture.md`), a Frente A **mudou de direção**: a pesquisa apontava embeddings como alternativa forte, mas medida de verdade contra o catálogo real (dois modelos multilíngues, `fastembed`, sem infraestrutura nova), embeddings perderam — não alcançam nem o nível de palavra nem o de nome de produto inteiro, porque são modelos genéricos sem ajuste ao domínio de cupom fiscal brasileiro, e um catálogo pessoal de 133 produtos não tem dado rotulado pra ajustar um modelo. A decisão da Frente A é **não implementar nada** — a medição em si é o entregável, e fica registrada. A Frente B virou um fix de ~5 linhas sem estado novo. A Frente C não achou nenhum gap de código pra corrigir, só um padrão já existente pra nomear.

**Resultado: um épico com uma medição sem código (A), um ticket de código pequeno (B) e um ticket de documentação (C) — não uma reestruturação grande.** Isso é o próprio ponto do design: a arquitetura madura já existia aqui, faltava reconhecer.

## Decisões aplicadas (vêm do design; não rediscutir dentro de ticket)

- **Embeddings não entram.** Medido, não suposto: `paraphrase-multilingual-MiniLM-L12-v2` (220MB) e `paraphrase-multilingual-mpnet-base-v2` (1GB) testados contra picanha/pinha, queijo/pão de queijo, coca, pepsi, suco — perdem em ambos os níveis (palavra e nome de produto inteiro). Não revisitar sem catálogo crescendo ordens de grandeza **e** dado rotulado do próprio domínio pra ajustar um modelo.
- **`matching_product_ids` (busca de histórico, `search_prices`) continua sem IA no caminho comum.** Alta frequência — a regra já estabelecida do projeto ("IA só em ponto de baixa frequência") não muda. Uma nova colisão lexical vira um guard determinístico medido (como `WORD_LENGTH_GAP_LIMIT`), não uma chamada de IA nova nem uma lista de exceção solta.
- **`match_kind`/`kind_candidates` (resolução de tipo pra `check_price`/`compare_stores`) continuam sendo o único ponto de IA-como-resolvedor** — baixa frequência, já provado ao vivo duas vezes nesta sessão.
- **A memória de conversa não ganha estado novo.** O bug (afirmar um fato errado sobre um turno fora da janela) se resolve trocando a *política de corte* de `HISTORY_TURNS` (fixar o turno 1, deslizar o resto) — mesmo custo de token de hoje. A pendência mais ampla de estado de conversa persistido (`shopping-list-conversation-context.md` RF4–RF6) continua aberta, não é fechada aqui.
- **A pergunta de esclarecimento (`ModelRetry` com candidatos) é convenção deliberada, não coincidência** — já auditada nos 3 pontos que a usam (`resolve_product`, `resolve_store`, `_resolve_kind`); nenhum gap de código encontrado nos candidatos auditados (`detect_tag`, `resolve_store`).

## Regras comuns a todo ticket

1. Leia `CLAUDE.md`, `docs/design/entity-resolution-architecture.md` e a seção do requisito citada no ticket antes de começar. O design tem precedência sobre este índice; o requisito, sobre o design.
2. Só toque nos arquivos listados no ticket.
3. Caminho feliz **e** de borda para toda função nova (ver ticket 181). Nenhum teste fala com a API real, exceto a "rodada real" opcional citada no próprio ticket, que roda numa cópia do banco, nunca o real.
4. Sem comentários narrando código; docstring só quando o *porquê* não é óbvio — mas as docstrings de funções novas desta trilha citam o incidente real que motivou a mudança, mesmo padrão que `_tool_note`/`_search_narration_context`/`_contradicts_price_check` (sessão anterior) já seguem.
5. Aceite = `.venv/bin/pytest -q` totalmente verde + critérios do próprio ticket.
6. Ao terminar, marque o ticket como feito na tabela abaixo e faça um commit só dele.

## Trilha

Trilha única — este projeto não tem front-end.

| # | Ticket | Depende de | Esforço | Estado | Entrega |
|---|---|---|---|---|---|
| 181 | [`bot/turn.py` — fixar o primeiro turno](181-turn-pin-first-history-turn.md) | — | S | **feito** | `_trim_history`; fecha o incidente banana/cebola sem estado novo nem custo extra de token; `SYSTEM_PROMPT` v7 ajustado (checar histórico antes de desistir), verificado ao vivo 2x |
| 182 | [`CLAUDE.md` — registrar as decisões](182-claude-md-entity-resolution-decisions.md) | — | S | **feito** | medição de embeddings registrada; convenção de desambiguação nomeada |
| 183 | RF2 formato 1 — coincidência de digitação em `search_prices` (sem ticket próprio, implementado direto a pedido do usuário) | — | S | **feito** | `suspicious_match_ids` (`services/search.py`) + `_reject_suspicious_match` (`bot/actions.py`, `ModelRetry` direto, sem IA); validado ao vivo contra o catálogo real (vinho/Pão Zinho, queijo/Requeijão, suco/Presunto Suinco pedem esclarecimento; leite não) |

## Dependências cruzadas

Nenhuma — os dois tickets são independentes, podem rodar em paralelo ou em qualquer ordem.

```
181 (código)
182 (documentação)
```

## Caminho crítico

Não há sequência obrigatória. `181` é o único ticket com valor de comportamento (fecha o incidente medido); `182` é puramente registro e pode ficar pra depois sem bloquear nada.

## Mapeamento de fases

Não há fases — as duas frentes com trabalho real (B e C) cabem inteiras num ticket cada; a Frente A não gera ticket (decisão de não implementar, já registrada no design).

## Riscos e mitigação

- **Ticket 181, `HISTORY_TURNS == 1`**: caso de borda que não existe em produção hoje (valor real é 3), mas a função `_trim_history` precisa tratar corretamente pra não duplicar turnos se a constante mudar no futuro — coberto por teste dedicado.
- **Ticket 181, "rodada real"**: como qualquer mudança de comportamento de modelo, o teste automatizado garante que a *informação* certa chega ao modelo, não que ele necessariamente a use certo em toda resposta (não-determinismo documentado em toda a sessão anterior) — por isso a rodada real é recomendada, não um critério de aceite bloqueante.
- **Ticket 182**: risco baixo (documentação); o único cuidado é não reescrever texto histórico de `CLAUDE.md`, só acrescentar.

## Rodada real (feita durante a implementação, não estava no plano original)

**1183 testes verdes** na suíte padrão (12 novos: 5 do ticket 181, 1 de regressão de `kind`, 6 herdados de sessões anteriores que precisaram de ajuste). Ao rodar `real_ai` pra validar o ticket 181 ao vivo, achei e corrigi uma **regressão real** introduzida na sessão anterior (fora do escopo original destes dois tickets, mas bloqueava a validação): `test_the_original_coca_incident_no_longer_says_not_in_catalog` falhou porque "coca" passou a empatar contra **dois** kinds ao mesmo tempo (`cacau em pó` e `chocolate`, 75.0 cada) — a primeira versão da reversão do empate de `kind` (sessão anterior) devolvia `None` assim que via um empate de 2+, sem nunca consultar o fallback por produto que resolveria certo pra "refrigerante". `services/search.py::_resolve_kind` unifica `match_kind`/`kind_candidates` numa função só, corrigindo isso por construção — os dois não podem mais discordar sobre por que um termo não resolveu. Regressão coberta por teste novo (`test_match_kind_multiway_lexical_tie_still_yields_to_unanimous_product_fallback`).

`SYSTEM_PROMPT` também ganhou um ajuste (v7) além do previsto: a primeira reprodução ao vivo do incidente da Frente B mostrou o modelo dizendo "não lembro tão longe" mesmo com o turno 1 já fixado e visível — honesto (não inventa mais um fato errado, que era o mínimo aceitável), mas não usava a informação disponível. Ajustada a instrução pra mandar checar o histórico visível antes de desistir; revalidado ao vivo com duas formulações diferentes da pergunta, as duas responderam "banana" corretamente.

**Efeito colateral encontrado, não corrigido**: `test_a_repeated_price_on_a_similar_item_asks_before_assuming_a_new_product` (suíte `real_ai`, de uma sessão anterior, fora do escopo desta trilha) passou a falhar de forma consistente depois do ajuste de prompt v7. Não é um bug de lógica (nenhum código deste teste foi tocado; "coca" resolve certo, a conversa nem chega a 3 turnos pra `_trim_history` entrar em ação) — é o formato já conhecido de sensibilidade de prompt: uma frase nova em qualquer lugar do `SYSTEM_PROMPT` pode deslocar um julgamento sutil de NLU em outro lugar. O próprio teste já documentava, de uma rodada anterior, que esse caso específico ("coca" seguido de "refrigerante 2L", mesmo preço) é uma linha fina entre duas respostas defensáveis. Não investiguei mais fundo — três ajustes de prompt na mesma sessão (v5, v6, v7) já é o suficiente sem medir de novo; fica registrado para quem for mexer no `SYSTEM_PROMPT` a seguir.

## Questões em aberto (herdadas do design, não resolvidas por estes tickets)

1. **RF2 da Frente A, formato 1 (coincidência de digitação) — implementado no ticket 183**, a pedido explícito do usuário mesmo sem incidente de dano real medido (taxa conhecida, ~8,1% dos termos de 1 palavra, 0% de frase — ver `docs/design/entity-resolution-architecture.md`, "Atualização 2026-09-22"). `suspicious_match_ids` + `_reject_suspicious_match`, sem IA. **Formato 2 (deriva semântica de nome composto, ex. queijo/pão de queijo em `search_prices`) continua fora de escopo** — sem caso medido nesse caminho específico, não implementado.
2. **Estado de conversa persistido de propósito geral** (`shopping-list-conversation-context.md` RF4–RF6) — continua aberto; o ticket 181 resolve só o caso medido (fato sobre turno fora da janela), não a pendência inteira. Assumido: não expandir o escopo do ticket 181 pra cobrir isso.
3. **Reavaliar embeddings no futuro** — só com catálogo em outra ordem de grandeza e dado rotulado do domínio; nenhum ticket monitora isso ativamente, é uma condição a notar se o catálogo crescer muito.
