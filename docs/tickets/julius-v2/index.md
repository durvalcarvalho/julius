# Julius v2 — IA na prática: tickets de implementação

> Gerado a partir de: `docs/design/ai-v2.md` (design), `docs/requirements/ai-v2.md` (requisitos), `claudedocs/handoff_smoke_test_deepseek_20260915.md` (resultado do gate)
> Gerado em: 2026-09-15 · Estado do código: commit `d7a57ef` + docs não versionados, 253 testes verdes

## Visão geral

A v1.1 deixou a camada de IA pronta mas ociosa: um só chamador (`produtos comparar`), nenhuma chamada real, e um catálogo com 70 produtos sem nenhuma tag nem nome legível depois de 5 notas. A v2 põe a IA para fazer a curadoria que o usuário não faz — nome legível, categoria, conteúdo da embalagem, duplicatas — de forma **reversível por comando e auditável em log**, e dá ao usuário o que ele pediu para decidir onde comprar: o **endereço** de cada mercado na consulta.

Abordagem: nada de framework. `urllib` com JSON mode e `max_tokens`; um `LlmResponse` que nunca é `None` (falha vira `error`); um `_ask` com um retry, custo cobrado por tentativa e uma linha JSONL por tentativa; prompts como constantes versionadas com few-shot (um negativo sempre); um serviço `curation` que decide "aplica" × "pergunta" sem olhar `confidence`; uma tela `_review` compartilhada por `importar` e `produtos revisar`; fallback de IA em `consultar` **só** quando o determinístico veio vazio. Endereço vem do parser, vive em `stores.address` (migração 0002, a primeira real), aparece em `mercados listar`, embaixo do apelido em `consultar` e no CSV.

Trilha única (o projeto não tem frontend). A numeração continua a da v1 (101–114) e a ordem já respeita as dependências.

## Decisões aplicadas (vêm do design e do gate; não rediscutir dentro de ticket)

- **Gate passou com uma ressalva**: `deepseek-flash` raciocina por padrão e **não converge** no prompt de enriquecimento (gasta 1200/3000/8000 tokens e devolve `content` vazio). Solução: `JULIUS_AI_REQUEST_EXTRAS='{"thinking":{"type":"disabled"}}'`, mesclado no corpo pelo cliente (105/106). Resposta truncada (`finish_reason != stop`) é erro **com custo** contabilizado.
- Preços de pico (`0.30`/`1.20`) recomendados nas variáveis para o teto de US$5 nunca subestimar.
- `LlmResponse.error` em vez de `None`: o log precisa da causa. JSON mode + `json.loads` direto; sem regex de extração.
- Categorias = tabela `tags`, semeada com 13 corredores na migração 0002; a IA prefere a lista, o usuário estende. Uma categoria automática por produto; dúvida = 2–3 tags, nunca `confidence`.
- IA grava o **reversível** (nome legível, tag) e nunca o irreversível (fusão, preços). Pré-requisito: `tag --remover` (104/111). Nome legível só para produto nunca renomeado à mão (`has_raw_name`). Conteúdo sempre confirmado.
- Duas portas, um fluxo: `importar` revisa os produtos novos (TTY ou `--sim`); `produtos revisar` cobre pendentes e os 70 atuais. Mesmo módulo `cli/_review.py`.
- Duplicatas: `token_set_ratio >= 75` pré-filtra (medido no catálogo real: pega as 3 verdadeiras, 15 pares no total), a IA julga, o CLI só imprime `fundir`.
- `consultar` chama IA só em resultado vazio, sem `--tag`; a solução durável é corrigir o dado (nome/tag), não cachear.
- Filial = mesmo `cnpj[:8]`; nunca fundir mercados; dica com endereço. Endereço inteiro guardado como texto, sem heurística de bairro.
- Separador de `details` nas dicas: `" · "` (endereços têm vírgula).
- Identificadores em inglês; comandos, `--help`, mensagens e prompts em português. Sem dependência nova. `tests/test_architecture.py` intocável.

## Regras comuns a todo ticket

1. Leia `CLAUDE.md` e o design da fase do ticket antes de começar; as seções citadas em cada ticket são o mínimo. Design por fase: 101–114 → `docs/design/ai-v2.md`; 115–116 → `docs/design/consultar-v2.1.md`; 117–130 → `docs/design/comparability-v2.2.md` (e `docs/requirements/comparability-closure.md`, que tem precedência sobre os outros requisitos da mesma data); 131–136 → `docs/design/review-scope-v2.3.md` (e `docs/requirements/review-scope-v2.3.md`).
2. Só toque nos arquivos listados no ticket. Se precisar de algo de outra camada que não existe, **pare e anote** — não crie fora do escopo.
3. `tests/test_architecture.py` é a fonte da verdade da DAG. Se ele falhar, o desenho está errado, não o teste.
4. Teste de caminho feliz **e** triste para cada função pública. SQLite real em `tmp_path`; rede **sempre** substituída por `tests/_fakes.py::ScriptedLlmClient`; nenhum teste toca a API real.
5. Toda função de IA nunca lança; toda gravação automática tem comando de desfazer já existente.
6. Sem comentários narrando código; docstring só quando o *porquê* não é óbvio.
7. Aceite = `.venv/bin/pytest -q` totalmente verde (suíte inteira) + `grep -rn NotImplementedError julius` vazio + critérios do ticket.
8. Ao terminar, marque o ticket como `feito` na tabela abaixo e faça um commit só dele (mensagem em inglês, como os anteriores).

## Trilha

| # | Ticket | Depende de | Esforço | Estado | Entrega |
|---|---|---|---|---|---|
| 101 | [Parser — endereço](101-parser-store-address.md) | — | S | feito | `Receipt.store_address`, `_ADDRESS` |
| 102 | [Migração 0002 + stores](102-migration-store-address-seed-tags.md) | 101 | M | feito | `stores.address`, 13 tags semeadas, upsert em `ensure_store`, `importing` passa endereço |
| 103 | [Endereço em prices/CSV](103-prices-export-store-address.md) | 102 | S | feito | `PriceRecord.store_address`, coluna `store_address` no export |
| 104 | [products: untag/pendentes/nome cru](104-products-repo-untag-pending.md) | — | S | feito | `remove_tag`, `untagged_product_ids`, `has_raw_name`, `catalog.untag_product` |
| 105 | [Config + ai_log](105-config-ai-log.md) | — | S | feito | `ai_log_path`, `JULIUS_AI_REQUEST_EXTRAS`, `infra/ai_log.py` |
| 106 | [Cliente LLM JSON mode](106-llm-client-json-mode.md) | 105 | M | feito | `LlmResponse.error`, `max_tokens`, `response_format`, extras, `tests/_fakes.py` |
| 107 | [suggestions núcleo + merges](107-suggestions-core-merge.md) | 105, 106 | M | feito | `_ask` (retry, custo, log), `suggest_merges`, `spent_this_month`; remove funções antigas |
| 108 | [suggestions enrich + match](108-suggestions-enrich-match.md) | 107 | M | feito | `enrich_products` (lotes de 25), `match_products`, `ProductEnrichment` |
| 109 | [Serviço curation](109-service-curation.md) | 104, 108 | M | feito | `propose`, `apply`, `duplicate_candidates`, `judge_duplicates` |
| 110 | [search/guidance/hints](110-search-guidance-hints.md) | 103 | M | feito | `records_for_products`, `catalog_for_matching`, 3 `HintKind`, `after_import(reviewed)`, textos |
| 111 | [CLI leitura](111-cli-read-side.md) | 104, 108, 110 | M | feito | endereço em `mercados listar`/`consultar`, fallback IA, `comparar` 3 motivos, `tag --remover` |
| 112 | [CLI review + revisar](112-cli-review-and-revisar.md) | 109, 110 | M | feito | `cli/_review.py`, `julius produtos revisar [--sim]` |
| 113 | [CLI importar + revisão](113-cli-importar-review.md) | 112 | S | feito | `importar [--sim]` revisa produtos novos; `reviewed` nas dicas |
| 114 | [e2e, docs, backfill](114-e2e-docs-backfill.md) | 101–113 | M | feito (código); backfill real pendente do usuário | `test_e2e.py` v2, `CLAUDE.md`, `README.md`, reimport dos HTMLs reais |
| 115 | [search: tag em texto livre](115-search-free-text.md) | — | M | feito | `domain.SearchOutcome`, `search.TAG_MATCH_CUTOFF`/`detect_tag`/`search_free_text` |
| 116 | [CLI: consultar natural + log](116-cli-consultar-natural-query-log.md) | 115 | M | feito | `consultar` com várias palavras, `--sem-tag`, `Config.query_log_path`, `query_log.jsonl` |
| 117 | [Migração 0003 + `products.kind`](117-product-kind-column.md) | — | S | feito | coluna `kind`, `set_kind` (regra de grafia), `all_kinds`, `clear_content` |
| 118 | [Comandos de desfazer](118-kind-content-undo-commands.md) | 117 | M | feito | `produtos tipo [--remover]`, `definir-conteudo --remover`, coluna "Tipo" |
| 119 | [Base de comparação](119-comparison-basis.md) | — | M | feito | `domain/comparison_basis.py`, `_highlight_and_trim` corrigido |
| 120 | [Prompt enrich v2 + `kind`](120-suggestions-enrich-kind.md) | 117 | M | feito | `ProductEnrichment.kind`, `PROMPT_VERSIONS["enrich"]="2"`, `known_kinds` |
| 121 | [curation: tipo + `AppliedAction`](121-curation-kind-applied-actions.md) | 118, 120 | M | feito | `propose` com tipo (não sobrescreve humano), `apply` devolve o que mudou |
| 122 | [review aplica + log de ações](122-review-auto-apply-action-log.md) | 118, 121 | M | feito | conteúdo e tipo automáticos, `actions.jsonl`, resumo agregado |
| 123 | [`revisar --ultimas-acoes`](123-review-last-actions.md) | 122 | S | feito | `ai_log.tail`, tabela de ações com comando de desfazer |
| 124 | [comparison: entre mercados](124-comparison-compare-stores.md) | 117, 119 | M | feito | `compare_stores`, `KindComparison`, `StoreComparison` |
| 125 | [CLI `mercados comparar`](125-cli-mercados-comparar.md) | 124 | M | feito | tabela por grupo, contagem derivada, rodapé com `n` e período |
| 126 | [comparison: extremos novos](126-comparison-new-extremes.md) | 119, 124 | M | feito | `new_extremes`, `PriceExtreme`, escopo de grupo |
| 127 | [CLI: sinal no importar + dia](127-cli-import-signal-weekday.md) | 122, 126 | M | feito | "Nesta compra:" (máx. 5 linhas), coluna "Dia" no `consultar` |
| 128 | [infra de arquivamento](128-receipt-files-infra.md) | — | M | feito | `infra/receipt_files.py`, `Config.inbox_path`/`archive_path`, `ImportResult.access_key` |
| 129 | [CLI: entrada e arquivamento](129-cli-inbox-archive.md) | 128 | M | feito (sem `discard_sidecar` — veto pendente) | `importar` sem argumento, arquiva e descarta sidecar, `make inbox`, `.gitignore` |
| 130 | [e2e + docs v2.2](130-e2e-docs-sync.md) | 117–129 | M | feito | `test_e2e` do ciclo novo, `CLAUDE.md`/`README.md` (inclui a reversão do conteúdo confirmado) |
| 131 | [Repositório: pendência por campo](131-products-incomplete-queries.md) | — | S | aberto | `incomplete_product_ids`, `sold_by_unit_ids`, `receipt_descriptions` |
| 132 | [curation: proposta completa](132-curation-proposal-reshape.md) | 131 | M | aberto | `ProductProposal.tag`/`receipt_description`/`sold_by_unit`; fim de `auto_tag` |
| 133 | [suggestions: intuição de embalagem](133-suggestions-packaging.md) | — | M | aberto | `PackagingHint`, prompt `packaging` v1, marcador no fake |
| 134 | [review: tabela honesta + categoria auto](134-review-table-and-auto-category.md) | 132 | M | aberto | colunas com valor atual em `dim`, cupom de verdade, fim do laço de categoria |
| 135 | [review: pergunta de conteúdo](135-review-content-question.md) | 133, 134 | M | aberto | `_ask_content`, `_FORM_LABELS`, `--sim` redefinido |
| 136 | [e2e + docs v2.3](136-e2e-docs-v23.md) | 131–135 | M | aberto | `test_e2e` do ciclo, rodada real, `CLAUDE.md`/`README.md` |

Esforço: S ≈ até 1h, M ≈ 1–3h de trabalho humano equivalente. Nenhum ticket L: o que ficaria L foi dividido (suggestions em 107/108; CLI em 111/112/113; na v2.2, serviço e CLI sempre em tickets separados — 124/125 e 126/127 — e a infra de arquivamento separada da CLI que a usa, 128/129).

## DAG

```
101 parser ──► 102 migração+stores ──► 103 prices/csv ──► 110 search/guidance/hints ──┐
                                                                                       ├──► 111 cli-leitura ──┐
104 products-repo ─────────────────────────────┐                                       │                      │
                                               ├──► 109 curation ──► 112 review+revisar ┘──► 113 importar ──► 114 e2e/docs
105 config+ai_log ──► 106 llm-client ──► 107 suggestions-merge ──► 108 enrich/match ──┘

115 search-free-text ──► 116 cli-consultar-natural+log

                 ┌─► 118 desfazer ──┐
117 kind ────────┼─► 120 enrich+kind ┴─► 121 curation ──► 122 review aplica+log ─┬─► 123 --ultimas-acoes
                 └─► 124 compare_stores ──► 125 mercados comparar                └─► 127 sinal + dia
119 base de comparação ──┴──────────────► 126 new_extremes ──────────────────────────┘

128 receipt_files ──► 129 importar sem argumento + arquivamento

117–129 ──► 130 e2e + docs

131 repo ──► 132 curation ──► 134 review/tabela ──┐
                                                  ├──► 135 pergunta de conteúdo ──► 136 e2e + docs
133 packaging ────────────────────────────────────┘
```

Paralelizável desde o início: {101, 104, 105}. Depois: 102 e 106 em paralelo; 103 e 107; 110 e 108; 109 após 108; 111 e 112 em paralelo após 110 (111 precisa de 108; 112 de 109). 115/116 são independentes de todo o resto (não tocam IA, endereço nem curadoria) — podem rodar em paralelo com qualquer fase.

Na v2.2, paralelizável desde o início: **{117, 119, 128}** — 119 não depende de `kind` (a base de comparação olha unidade, produto e conteúdo) e 128 é infra de arquivo, independente de tudo. Depois: 118 e 120 em paralelo após 117; 124 após 117+119; 125 e 126 em paralelo após 124.

## Caminho crítico

105 → 106 → 107 → 108 → 109 → 112 → 113 → 114 (a IA de verdade fazendo curadoria no `importar`). A trilha do endereço (101 → 102 → 103 → 110 → 111) é mais curta e independente até 110. 115 → 116 é uma trilha curta e independente, à parte.

v2.2: **117 → 118 → 121 → 122 → 127 → 130** (a curadoria automática chegando até o sinal de preço no import). A trilha de comparação entre mercados (117/119 → 124 → 125) é mais curta e entrega valor sozinha; a trilha de arquivamento (128 → 129) é independente do resto e pode ser feita primeiro se a fricção de arquivo incomodar antes.

**Restrição de ordem que não é técnica, é de princípio:** 118 antes de 122. A automação só pode aplicar o que já tem comando de desfazer (`docs/requirements/comparability-closure.md` §4, condição 1). Um agente que inverter isso entrega um sistema que grava sozinho algo que o usuário não consegue desfazer.

## Fases

- **A — dados**: 101, 102, 103, 104 (endereço de ponta a ponta na camada de dados; desfazer tag).
- **B — IA robusta**: 105, 106, 107, 108 (JSON mode, log, retry, prompts v2, lote).
- **C — decisão**: 109, 110 (curadoria determinística; dicas novas).
- **D — CLI**: 111, 112, 113.
- **E — integração**: 114.
- **v2.1 — consultar em texto livre + log de consultas** (`docs/design/consultar-v2.1.md`): 115 → 116.
- **v2.2 — comparabilidade** (`docs/design/comparability-v2.2.md`): três trilhas que se juntam no 130.
  - **F — grupo de comparação**: 117, 118, 120, 121, 122, 123 (a IA nomeia o tipo; tipo e conteúdo passam a ser aplicados sozinhos, com log e desfazer).
  - **G — comparar de verdade**: 119, 124, 125, 126, 127 (a base de comparação correta, a comparação entre mercados e o sinal de preço no import).
  - **H — arquivamento**: 128, 129 (`entrada/` como symlink, `importar` sem argumento, arquiva e limpa).
  - **I — fechamento**: 130.

- **v2.3 — escopo da revisão e HITL de conteúdo** (`docs/design/review-scope-v2.3.md`): 131 → 132 → 134 → 135 → 136, com 133 em paralelo desde o início.
  - **J — dado**: 131, 132 (pendência por campo faltando; proposta completa).
  - **K — IA**: 133 (a segunda chamada, isolada, que ninguém consome até o 135).
  - **L — tela**: 134, 135 (a tabela deixa de mentir; a pergunta muda de campo).
  - **M — fechamento**: 136, com rodada real obrigatória contra cópia do banco.

  **Restrição de ordem que é de princípio, não técnica:** 134 antes de 135. O 134 tira a pergunta de categoria e o 135 põe a de conteúdo; invertidos, existe um estado em que a revisão pergunta **as duas coisas** — mais atrito do que hoje, que é o problema que a fase existe para resolver.

  Depois de **F**, vale um teste real intermediário: `julius produtos revisar` contra uma cópia do banco, conferindo `actions.jsonl` e a coluna "Tipo" em `produtos listar` — é a primeira vez que a IA grava algo que não é nome nem categoria.

Depois de **B**, vale um teste real intermediário: `julius produtos comparar 63 69` com a chave configurada — a primeira chamada de produção do projeto — e conferir `~/.local/share/julius/ai_calls.jsonl`.

## Riscos e mitigações

- **Thinking mode volta a ser default ou o nome do parâmetro muda** → `enrich` para de responder (`finish_reason length`). O log mostra `error` e tokens gastos; a correção é editar `JULIUS_AI_REQUEST_EXTRAS`, sem código.
- **Primeira migração real perde dado** → backup `prices.db.bak-v1` automático (mecanismo já testado); 102 exige rodar contra uma cópia do banco real antes do commit.
- **IA expande abreviação errado** (`AC MASC F TER ES`) → nome legível é reversível (`renomear`), o cupom cru fica em `prices.description`, o prompt tem exemplo explícito de "na dúvida, mantenha".
- **Vocabulário de tags fragmenta** → lista semeada + "prefira a lista"; tag desconhecida nunca é automática (pede confirmação ou `--sim`).
- **Duplicata falsa sugerida** → nunca executa; imprime o `fundir` com `rationale` para o humano ler.
- **Latência no `importar`** → uma passada só no fim, lotes de 25, spinner; `--sim` para scripts. Sem TTY, nada pergunta.
- **`sys.stdin.isatty()` em teste** → encapsulado em `_review._is_interactive`, substituído por monkeypatch.
- **Agente "conserta" arquitetura para passar** → regra 3.
- **`TAG_MATCH_CUTOFF` colidir com uma tag futura** (115) → medido só contra as 13 tags semeadas; uma tag nova parecida com uma palavra comum de produto pode reabrir falso positivo. Mitigação: constante isolada e documentada com a medição, fácil de re-testar; não é regressão, é o mesmo compromisso que `MATCH_SCORE_CUTOFF` já aceita.
- **v2.2 — a IA escolher o tipo na granularidade errada** (120) → `Leite` juntando UHT com condensado é o caso medido. Mitigação: as duas metades da instrução do prompt vêm de grupos reais; o tipo é reversível (118) e visível em `produtos listar`; tipo errado num grupo de um produto só é inerte.
- **v2.2 — tipos fragmentarem por singular/plural** (117) → `tomate`/`tomates` viram dois grupos silenciosamente. A regra de grafia do repositório resolve caixa e acento, não plural. Mitigação deliberada: nenhum corte fuzzy novo (seria um terceiro cutoff a medir sem evidência); detecção por `SELECT kind, count(*) ... GROUP BY kind`, correção por um `UPDATE`.
- **v2.2 — mudança de comportamento no `highlight`** (119) → o mínimo/máximo passa a sair de grupos UN heterogêneos sem conteúdo. É correção de um erro medido (500ml marcada como mais barata que 1,5L), não regressão; os dois testes existentes de highlight continuam passando pelo ramo "mesmo `product_id`".
- **v2.2 — reversão de "conteúdo sempre confirmado"** (122) → um agente futuro pode "restaurar" a confirmação achando que foi regressão. Mitigação: o 130 exige que o `CLAUDE.md` registre o **porquê** da reversão, não só o novo comportamento.
- **v2.3 — a segunda chamada contaminar o `enrich`** (133) → o valor do arranjo todo está na recusa honesta do prompt de produção (`null` certo em 6 de 6). Mitigação: prompts, versões e validadores separados; `PROMPT_VERSIONS["enrich"]` não muda e o teste que prova o `null` continua verde.
- **v2.3 — a intuição de varejo errar se dizendo certa** (133/135) → medido: `Filme PVC 30m x 28cm` virou `30 UN` com o campo de certeza marcado. Mitigação estrutural, não de prompt: a intuição nunca grava, só alimenta opções, e o humano pula. Conteúdo errado é o único campo cujo erro **não** aparece na saída normal — vira um R$/UN plausível.
- **v2.3 — vocabulário de tags parar de crescer sozinho** (132) → efeito colateral desejado do "primeira categoria **conhecida**", que protege a medição de `TAG_MATCH_CUTOFF`. Custo zero na amostra (25 de 25 já eram conhecidas); quando acontecer, o produto fica pendente e reaparece.
- **v2.3 — a primeira rodada ser grande** (136) → ~86 produtos contra 4 pelo critério antigo, ~4 chamadas, ~US$ 0,02. Decidido nos requisitos: roda inteira, sem teto e sem confirmação.
- **v2.2 — apagar o `_files/` é a única operação destrutiva do sistema** (128) → três guardas exigidas por teste: nome derivado exato, precisa ser diretório real, nunca symlink. Pendente de veto do usuário; vetado, a função existe e não é chamada.

## Questões assumidas nos tickets (mudariam pouco se a resposta fosse outra)

- Preços de pico nas variáveis: **recomendação**, não código; o usuário decide o valor exportado.
- Uma categoria automática por produto; várias só à mão. Se o usuário quiser 2 automáticas, muda só `curation.propose`/`apply` (uma linha cada).
- `mercados listar` não agrupa por rede além da ordenação por CNPJ que já existe (filiais saem adjacentes).
- `julius ia status` **não** entra (Q8 dos requisitos): `tail -n 5 ai_calls.jsonl` e `SELECT * FROM ai_usage` cobrem; `comparar` já distingue os três motivos.
- Cache de respostas de IA fora: o caminho durável é corrigir o dado.
- O smoke script do scratchpad não entra no repositório; o resultado está registrado em `docs/design/ai-v2.md` §1.1.
- **115/116**: nenhum comando de analytics sobre `query_log.jsonl` (jq/`Counter` cobrem, mesma decisão de não criar `julius ia status`); nenhuma tag multi-palavra (nenhuma das 13 tags precisa); nenhum `HintKind` novo pra "tag detectada" (auto-detecção bem-sucedida não é gatilho de dica — ver `docs/design/consultar-v2.1.md` §3). Se qualquer uma dessas premissas mudar, revisitar o design antes de estender os tickets.
- **117–130 (v2.2)**, todas registradas em `docs/design/comparability-v2.2.md` §9:
  - **Grupo em coluna, não em `tags`** — um produto pertence a no máximo um grupo, e coluna faz disso regra do banco. Reaproveitar `tags` também invalidaria a medição de `TAG_MATCH_CUTOFF` (115). Se um dia um produto precisar estar em dois grupos, o desenho muda, não o ticket.
  - **`consultar --tipo` não entra**: `rapidfuzz` já acha o grupo quando o termo é o próprio tipo (`consultar tomate` acha os dois tomates hoje).
  - **Estreitar `duplicate_candidates` por tipo não entra**, embora mataria o falso positivo `Alho` ↔ `Pão de Alho` de graça. Nenhum requisito pediu; vira trivial depois do 117 se incomodar.
  - **Representante da loja num grupo é o menor preço**, não a média nem o mais recente: a pergunta é "o que eu pagaria lá". Se o usuário quiser o mais recente, muda uma função em `comparison.compare_stores`.
  - **Contagem por grupo, não índice**: nenhum número único de carestia por mercado, e nenhuma média de razões entre grupos de preços muito diferentes.
  - **Dia da semana só como coluna**: as 6 notas reais caem em 6 dias diferentes, zero repetição — qualquer afirmação seria invenção. Gatilho para reabrir não foi definido de propósito.
  - **Fusão automática de produto está rejeitada por medição**, não por cautela (19 pares acima do corte, no máximo 2 defensáveis, pior falso positivo com nota 1,00). Reabrir exige dado novo, e exigiria antes construir a reversibilidade que `merge_products` não tem.
