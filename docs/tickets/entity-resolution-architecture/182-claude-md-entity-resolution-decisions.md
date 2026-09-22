# 182: `CLAUDE.md` — registrar a medição de embeddings e a convenção de desambiguação

> Dois parágrafos de documentação, sem código: atualiza a rejeição de busca semântica (já existia, sem número por trás) com a medição real desta rodada, e nomeia como convenção deliberada o padrão de "pergunta em vez de escolhe sozinho" que já existe em 3 lugares do bot.

## Contexto

`docs/design/entity-resolution-architecture.md`, Frentes A e C. As duas mudanças são só documentação porque as duas frentes concluíram, medidas, que **não há código pra escrever**:

- **Frente A**: embeddings foram testados de verdade (dois modelos multilíngues, nível de palavra e de nome de produto inteiro) contra os casos reais desta sessão (picanha/pinha, queijo/pão de queijo, coca, pepsi, suco) e perderam pra IA-como-resolvedor, que já está em produção. A rejeição de busca semântica já existia em `CLAUDE.md` (linhas 450 e 761) desde a v1 — mas como suposição ("desproporcional"), nunca como medição. Isto fecha essa lacuna.
- **Frente C**: auditados os dois candidatos do requisito (`detect_tag`, `resolve_store`) — nenhum tinha ambiguidade sem tratamento; `resolve_store` já pergunta via `ModelRetry` desde que foi escrito. Não sobrou nada pra corrigir, só pra nomear.

Não depende do ticket 181 (pode ser feito em paralelo ou antes).

## Escopo

### Dentro
- `CLAUDE.md` linha ~450 (dentro de "Identidade de produto e busca"): estender o parágrafo "Rejeitado explicitamente: busca semântica..." com a medição real (modelos testados, números de cosseno, por que perde).
- `CLAUDE.md` linha ~761 (lista "Fora de escopo v1/v2/...", item "busca semântica/embeddings"): atualizar a justificativa entre parênteses de "desproporcional pro tamanho do catálogo" (suposição) para citar a medição real.
- Um parágrafo novo em `CLAUDE.md`, na seção "Identidade de produto e busca" (perto de onde `resolve_product`/`ModelRetry` já são descritos) ou em `julius/bot/actions.py` como docstring de módulo — nomeando a convenção de desambiguação por pergunta.

### Fora
- Qualquer mudança em código (`julius/`) — nenhuma das duas frentes gera função nova, teste novo, ou comportamento novo.
- A frente A, item RF2 do requisito (detectar heterogeneidade de `kind`/tag numa busca e oferecer desambiguação) — o design deixou isso explicitamente para quando houver um segundo caso medido do formato picanha/pinha; não implementar nem documentar como decidido, só citar como frente aberta se ainda não estiver.
- Renumerar ou reescrever seções inteiras de `CLAUDE.md` — só os dois pontos citados acima e o parágrafo novo.

## Requisitos

### Funcionais — texto a inserir

**No parágrafo de "Rejeitado explicitamente: busca semântica" (~linha 450):** acrescentar, sem apagar o texto existente, algo como:

> **Medido de verdade em 2026-09-22** (`claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md`, `docs/design/entity-resolution-architecture.md`): testados `fastembed` com `paraphrase-multilingual-MiniLM-L12-v2` (220MB) e `paraphrase-multilingual-mpnet-base-v2` (1GB) contra os casos reais desta sessão. No nível de palavra, nenhum corte de cosseno separa os falsos positivos dos matches necessários (`TOMATEE`/`TOMATE`, que precisa bater, mede 0,766; `SUCO`/`SUINCO`, falso positivo, mede 0,818 — mais parecido que o match de verdade). No nível de nome de produto inteiro, foi pior: pedindo "picanha", "coca", "pepsi" ou "suco", o produto certo nem aparece no top 5 dos dois modelos. A IA que já resolve `kind` (`kind_candidates`) acerta esses mesmos casos porque tem conhecimento de mundo que um modelo de frase genérico, sem ajuste ao domínio de cupom fiscal brasileiro, não tem. Reforça a rejeição original (que era suposição, "desproporcional") com número — e fecha, por ora, a hipótese de trocar por embeddings.

**No item da lista "Fora de escopo" (~linha 761):** trocar `**busca semântica/embeddings** (desproporcional pro tamanho do catálogo)` por algo como `**busca semântica/embeddings** (v1, suposição; medido e reconfirmado em 2026-09-22 — dois modelos multilíngues testados contra os casos reais da sessão, nenhum supera a IA já em produção; ver "Identidade de produto e busca")`.

**Parágrafo novo — convenção de desambiguação (local a escolher pelo agente: `CLAUDE.md` ou docstring de topo de `julius/bot/actions.py`, mas não os dois):**

> **Convenção (2026-09-22): toda resolução de entidade em `bot/actions.py` que encontra 2+ candidatos plausíveis, sem vencedor claro, levanta `ModelRetry` listando as opções — nunca escolhe sozinha.** Já é assim em `resolve_product`, `resolve_store` e `_resolve_kind` desde que cada um foi escrito; auditados nesta rodada os dois candidatos a gap (`detect_tag`: sem ambiguidade observável nas 13 tags reais; `resolve_store`: já perguntava). Uma resolução de entidade nova que não seguir este formato é a exceção que precisa de justificativa, não o padrão — é a peça de "desambiguação por sub-diálogo" que sistemas de diálogo orientados a tarefa usam há 30+ anos (`claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md`), não uma solução pontual de bug.

### Validação
- Não reescrever nenhuma frase já existente além do texto explicitamente indicado acima — este projeto trata `CLAUDE.md` como registro histórico (ver como v2.2/v2.3/v2.4 etc. nunca apagam o texto de rodadas anteriores, só acrescentam).

## Especificação técnica

```
modificar CLAUDE.md — 2 pontos (linha ~450, linha ~761) + 1 parágrafo novo
```

Nenhum arquivo de `julius/` ou `tests/` é tocado por este ticket.

## Testes obrigatórios

Nenhum — é um ticket de documentação. Critério de aceite é revisão de texto, não suíte automatizada.

## Critérios de aceite
- [ ] Os dois pontos existentes de `CLAUDE.md` (rejeição de busca semântica) citam a medição real de 2026-09-22, sem apagar o texto anterior.
- [ ] Existe, em algum lugar (`CLAUDE.md` ou `bot/actions.py`), um parágrafo nomeando a convenção de desambiguação por `ModelRetry` como decisão deliberada, não coincidência de 3 correções separadas.
- [ ] `.venv/bin/pytest -q` continua verde (nenhum código tocado, mas confirma que a edição de `CLAUDE.md` não quebrou nada por acidente — improvável, mas é o critério padrão deste projeto).

## Notas para o agente

- Não invente números que não estão no design (`docs/design/entity-resolution-architecture.md`) — os valores de cosseno, nomes de modelo e tamanhos citados acima já são os medidos; copie exatamente, não arredonde nem aproxime.
- Se decidir colocar o parágrafo da convenção em `bot/actions.py` em vez de `CLAUDE.md`, ainda assim deixe uma referência de uma linha em `CLAUDE.md` apontando pra lá — é onde quem lê o histórico do projeto vai procurar primeiro.
- Este ticket não fecha `docs/requirements/entity-resolution-architecture.md` RF2 (heterogeneidade em `search_prices`) nem a pendência de "lista de compras conversacional" — não marque essas questões como resolvidas em nenhum texto novo.
