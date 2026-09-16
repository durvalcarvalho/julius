# 114: Ponta a ponta v2, documentação e backfill

> Um teste e2e que percorre importar → revisar → consultar (com fallback) → mercados listar com o cliente fake determinístico; `CLAUDE.md` e `README.md` atualizados para o que o código faz agora; reimport dos HTMLs reais para preencher o endereço.

## Contexto

Fecha a trilha. `docs/design/ai-v2.md` §8 (e2e), §10 (o que atualizar no `CLAUDE.md`), §1.1 (resultado do gate que precisa virar documentação de configuração).

Depende de todos os anteriores (101–113). Regras comuns: `index.md`.

## Escopo

### Dentro
- `tests/test_e2e.py`: novos fluxos v2 (com `ScriptedLlmClient` via stub em `julius.cli.receipts`/`julius.cli.products`).
- `CLAUDE.md` e `README.md` (seções listadas abaixo).
- `docs/tickets/julius-v2/index.md`: marcar tudo `feito`.
- Backfill: instrução e execução (pelo usuário) de `julius importar ~/.local/share/julius/entrada/*.html`.

### Fora
- Código novo em `julius/` (se um fluxo e2e revelar bug, abra ticket 115+ em vez de consertar aqui sem teste unitário).

## Requisitos

### Funcionais — e2e (`tests/test_e2e.py`)
1. `test_v2_import_review_search_by_tag` — importar 5 fixtures com IA fake (`--sim`): `produtos listar` mostra nomes legíveis e tags; `consultar --tag carnes` lista os produtos que o fake marcou como `carnes`; `consultar linguica` (nome legível já aplicado) acha sem chamar IA (`fake` sem chamada `match`).
2. `test_v2_fallback_then_permanent_fix` — banco sem revisão; `consultar carne` → fallback acha picanha + dica `FOUND_VIA_AI`; `produtos tag ID carnes`; `consultar --tag carnes` acha sem IA.
3. `test_v2_stores_show_address_and_branch_hint` — importar `qrcode-3.html` e `qrcode-4.html` → dica de filiais com os dois endereços; `mercados listar` mostra `GUARA II` e `CANDANGOLANDIA`; `consultar` de um produto do Dona de Casa mostra o endereço embaixo do apelido.
4. `test_v2_reimport_is_idempotent_and_silent` — reimportar tudo: `0 itens novos`, nenhuma chamada de IA, nenhuma tabela de revisão.
5. `test_v2_untag_and_rename_undo_ai_writes` — desfazer tag (`--remover`) e nome (`renomear`) restaura estado.
6. `test_v2_ai_log_has_one_line_per_attempt` — com `JULIUS_DB` em `tmp_path`, o `ai_calls.jsonl` ao lado tem `call_kind` em `{enrich, merge, match}` e `parsed_ok` coerente.

### Funcionais — documentação
- `README.md`:
  - Tabela "Configuração": `JULIUS_AI_REQUEST_EXTRAS` (JSON mesclado no corpo; **DeepSeek precisa** de `'{"thinking":{"type":"disabled"}}'` — sem isso o modelo gasta todo o `max_tokens` raciocinando e não responde, medido no gate); preços: recomendar os de pico (`0.30`/`1.20` para `deepseek-flash`); `JULIUS_AI_BUDGET_USD` default continua `1.0`.
  - Seção "IA opcional": reescrever a tabela — `produtos revisar`/`importar` (nome legível e categoria aplicados, conteúdo confirmado), `consultar` (fallback só em vazio), `comparar`. Remover menções a `suggest_content`/`suggest_tags`. Explicar `~/.local/share/julius/ai_calls.jsonl` e como desfazer (`renomear`, `tag --remover`).
  - Comandos novos/alterados: `produtos revisar [--sim]`, `produtos tag … --remover`, `importar --sim`, endereço em `mercados listar`/`consultar`/`exportar`.
- `CLAUDE.md` (edições cirúrgicas, mantendo o estilo do documento):
  - "Status": v2 implementada; provedor DeepSeek `deepseek-flash`, thinking desligado via extras, orçamento US$5; suíte verde com o número real de testes.
  - "Camada opcional de IA": cliente HTTP existe (não é ticket futuro); JSON mode; `LlmResponse.error`; log JSONL; funções atuais (`suggest_merges`, `enrich_products`, `match_products`); princípio revisado: "IA grava o reversível (nome, tag), nunca o irreversível (fusão, preços)"; regra de frequência atualizada (fallback só em resultado vazio).
  - "Requisitos novos": item 2 → resolvido por `produtos revisar`; item 3 → coberto pela revisão.
  - "Fatos e pegadinhas": filiais — acrescentar os endereços (QE 30 Guará II × QR 5 Candangolândia) e `cnpj[:8]` como identidade de rede; nova pegadinha: `deepseek-flash` raciocina por padrão e não converge no prompt de enriquecimento (1200/3000/8000 tokens), `thinking: disabled` obrigatório.
  - "Armazenamento": colar a migração 0002; `stores.address`; tags semeadas.
  - "Dicas de uso": os 3 kinds novos na tabela; separador `" · "`; `after_import(reviewed=)`.
  - "Identidade de produto e busca": nomes legíveis pela IA como solução durável para abreviações; `has_raw_name` protege renomes manuais.
  - "Estrutura de pacote": `services/curation.py`, `infra/ai_log.py`, `cli/_review.py`, `migrations/0002_*.sql`.
  - "Fora do escopo": manter; acrescentar "cache de respostas de IA".
- Backfill (executado pelo usuário, com IA configurada): `julius importar ~/.local/share/julius/entrada/*.html` preenche `stores.address`; como todos os produtos já existem, **não** dispara revisão — em seguida `julius produtos revisar` cuida dos 70. Registrar no `CLAUDE.md` § "Status" que isso foi feito.

### Validação e erros
- e2e usa só fixtures locais e fake; nenhuma rede.

## Especificação técnica

```
modificar tests/test_e2e.py
modificar README.md
modificar CLAUDE.md
modificar docs/tickets/julius-v2/index.md
```

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; `grep -rn NotImplementedError julius` vazio.
- [ ] `grep -n "suggest_content\|suggest_tags\|vem num ticket próprio" README.md CLAUDE.md` vazio.
- [ ] Usuário confirmou backfill: `julius mercados listar` real mostra endereço nas 5 lojas.
- [ ] `~/.local/share/julius/ai_calls.jsonl` real tem linhas de `enrich` com `parsed_ok: true` após o primeiro `revisar`.

## Notas para o agente
- Não reescreva o `CLAUDE.md` inteiro: ele é o histórico de decisões; edite as seções listadas e marque o que ficou obsoleto com "(v1; ver v2)" em vez de apagar raciocínio.
- Se o e2e mostrar divergência entre design e código, o ticket certo é novo, não um "ajuste" silencioso aqui.
