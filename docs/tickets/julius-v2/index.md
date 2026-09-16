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

1. Leia `CLAUDE.md` e `docs/design/ai-v2.md` antes de começar; as seções citadas em cada ticket são o mínimo.
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
| 116 | [CLI: consultar natural + log](116-cli-consultar-natural-query-log.md) | 115 | M | a fazer | `consultar` com várias palavras, `--sem-tag`, `Config.query_log_path`, `query_log.jsonl` |

Esforço: S ≈ até 1h, M ≈ 1–3h de trabalho humano equivalente. Nenhum ticket L: o que ficaria L foi dividido (suggestions em 107/108; CLI em 111/112/113).

## DAG

```
101 parser ──► 102 migração+stores ──► 103 prices/csv ──► 110 search/guidance/hints ──┐
                                                                                       ├──► 111 cli-leitura ──┐
104 products-repo ─────────────────────────────┐                                       │                      │
                                               ├──► 109 curation ──► 112 review+revisar ┘──► 113 importar ──► 114 e2e/docs
105 config+ai_log ──► 106 llm-client ──► 107 suggestions-merge ──► 108 enrich/match ──┘

115 search-free-text ──► 116 cli-consultar-natural+log
```

Paralelizável desde o início: {101, 104, 105}. Depois: 102 e 106 em paralelo; 103 e 107; 110 e 108; 109 após 108; 111 e 112 em paralelo após 110 (111 precisa de 108; 112 de 109). 115/116 são independentes de todo o resto (não tocam IA, endereço nem curadoria) — podem rodar em paralelo com qualquer fase.

## Caminho crítico

105 → 106 → 107 → 108 → 109 → 112 → 113 → 114 (a IA de verdade fazendo curadoria no `importar`). A trilha do endereço (101 → 102 → 103 → 110 → 111) é mais curta e independente até 110. 115 → 116 é uma trilha curta e independente, à parte.

## Fases

- **A — dados**: 101, 102, 103, 104 (endereço de ponta a ponta na camada de dados; desfazer tag).
- **B — IA robusta**: 105, 106, 107, 108 (JSON mode, log, retry, prompts v2, lote).
- **C — decisão**: 109, 110 (curadoria determinística; dicas novas).
- **D — CLI**: 111, 112, 113.
- **E — integração**: 114.
- **v2.1 — consultar em texto livre + log de consultas** (`docs/design/consultar-v2.1.md`): 115 → 116.

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

## Questões assumidas nos tickets (mudariam pouco se a resposta fosse outra)

- Preços de pico nas variáveis: **recomendação**, não código; o usuário decide o valor exportado.
- Uma categoria automática por produto; várias só à mão. Se o usuário quiser 2 automáticas, muda só `curation.propose`/`apply` (uma linha cada).
- `mercados listar` não agrupa por rede além da ordenação por CNPJ que já existe (filiais saem adjacentes).
- `julius ia status` **não** entra (Q8 dos requisitos): `tail -n 5 ai_calls.jsonl` e `SELECT * FROM ai_usage` cobrem; `comparar` já distingue os três motivos.
- Cache de respostas de IA fora: o caminho durável é corrigir o dado.
- O smoke script do scratchpad não entra no repositório; o resultado está registrado em `docs/design/ai-v2.md` §1.1.
- **115/116**: nenhum comando de analytics sobre `query_log.jsonl` (jq/`Counter` cobrem, mesma decisão de não criar `julius ia status`); nenhuma tag multi-palavra (nenhuma das 13 tags precisa); nenhum `HintKind` novo pra "tag detectada" (auto-detecção bem-sucedida não é gatilho de dica — ver `docs/design/consultar-v2.1.md` §3). Se qualquer uma dessas premissas mudar, revisitar o design antes de estender os tickets.
