# 122: `_review` aplica tipo e conteúdo sozinho, grava `actions.jsonl` e imprime resumo agregado

> Inverte o padrão da revisão: em vez de sugerir e esperar confirmação, aplica e registra. **Reverte uma decisão explícita da v2** ("conteúdo sempre confirmado") — leia as notas antes de começar.

## Contexto

`docs/design/comparability-v2.2.md` §4.9 (`Config.action_log_path`), §4.10 (`_review`). Requisitos RF3/RF4 de `docs/requirements/comparability-closure.md`; o formato do aviso é a decisão do usuário registrada em §5 ("resumo agregado, detalhe sob demanda"), e a autorização para aplicar sozinho é o teste de duas condições de §4 (reversível por comando existente **e** erro visível na saída normal).

Depende de **118** (os comandos de desfazer existem) e **121** (`apply` devolve `AppliedAction`).

⚠️ **Reversão de decisão registrada.** O `CLAUDE.md` afirma hoje, em "Camada opcional de IA": "conteúdo de embalagem **nunca** é gravado sem confirmação explícita, mesmo com `--sim`". O fechamento do brainstorm reverteu isso deliberadamente: conteúdo passa o teste de §4 (desfazer existe desde o 118, e o valor errado aparece na coluna "Por KG/L" de `consultar`), e a medição mostrou que **32 dos 79 produtos-UN não têm conteúdo** justamente porque a confirmação virou fricção — o import de 16/09 imprimiu 26 comandos `definir-conteudo` que ninguém rodou. A sincronização do `CLAUDE.md` é o ticket 130.

## Escopo

### Dentro
- `julius/config.py`: `action_log_path`.
- `julius/cli/_review.py`: aplica conteúdo e tipo automaticamente; grava uma linha por `AppliedAction`; troca as linhas por item pelo resumo agregado; coluna "Tipo" na tabela de propostas.
- Testes: `tests/test_config.py`, `tests/test_cli_review.py`.

### Fora
- `produtos revisar --ultimas-acoes` e o leitor do log (→ 123). O resumo deste ticket **não** cita essa flag, porque ela ainda não existe — cita os comandos diretos.
- `curation.apply`/`propose` (fechados no 121).
- O laço de pergunta de **categoria** ambígua: continua exatamente como está (categoria em dúvida ainda pergunta — `comparability-closure.md` §4 só autoriza automático para candidato único conhecido).
- O bloco de duplicatas (`judge_duplicates`): continua só imprimindo `fundir`.
- Qualquer mudança em `importar`/`consultar` (→ 127).

## Requisitos

### Funcionais

- `Config.action_log_path -> Path` — `self.db_path.parent / "actions.jsonl"`, uma linha, no mesmo formato de `ai_log_path`/`query_log_path` (`config.py:27-33`).

- `_table` ganha a coluna "Tipo" (entre "Categoria" e "Conteúdo"), com `proposal.kind or ""`.

- `review_products` passa a aplicar, na passada automática que hoje só aplica nome e categoria:
  ```python
  actions = curation.apply(conn, proposal, tag=proposal.auto_tag, content=True, kind=True)
  ```
  — conteúdo e tipo entram no mesmo `apply`, sem pergunta e **independente de `--sim`/TTY**.

- **O laço de conteúdo desaparece**: tanto o ramo interativo (`_confirm_pt(... definir conteúdo ...)`) quanto o ramo que imprimia `julius produtos definir-conteudo ID QTD UNIDADE` saem do arquivo. `_confirm_pt` continua no módulo se algum outro ponto usar; se ficar sem uso, remova a função.

- Cada `AppliedAction` devolvida gera uma linha em `actions.jsonl` via `ai_log.append(settings.action_log_path, record)`:
  ```python
  {"at": "<ISO 8601 UTC>", "product_id": 71, "field": "kind",
   "before": None, "after": "uva", "undo": "julius produtos tipo 71 --remover"}
  ```
  A string `undo` é montada **aqui** (a CLI é a camada que conhece a sintaxe dos comandos — `AppliedAction` é dado puro, ver 121), por campo:
  | `field` | `undo` |
  |---|---|
  | `name` | `julius produtos renomear <id> "<before>"` |
  | `tag` | `julius produtos tag <id> <after> --remover` |
  | `content` | `julius produtos definir-conteudo <id> --remover` quando `before is None`; senão `julius produtos definir-conteudo <id> <before>` |
  | `kind` | `julius produtos tipo <id> --remover` quando `before is None`; senão `julius produtos tipo <id> "<before>"` |

- A linha "Aplicado:" passa a ser o **resumo agregado**, contando por campo a partir das ações realmente devolvidas (não do número de propostas):
  ```
  Aplicado: 38 nome(s), 30 categoria(s), 32 conteúdo(s), 75 tipo(s).
  Desfazer: julius produtos renomear · julius produtos tag --remover · julius produtos definir-conteudo --remover · julius produtos tipo --remover
  ```
  Campo com contagem zero é omitido da primeira linha. Nenhuma linha por item.

- `review_products` continua devolvendo `bool` (houve revisão), sem mudança de assinatura.

### Validação e erros
- `ai_log.append` nunca lança (já é contrato do módulo): log quebrado não pode interromper a revisão nem mudar o código de saída.
- Se `curation.apply` levantar (ex.: tag em branco), o comportamento é o de hoje — não engolir exceção nova aqui.
- Sem TTY e sem `--sim`, o comportamento de **categoria** continua o de hoje (fica pendente); conteúdo e tipo são aplicados de todo jeito.

## Especificação técnica

```
modificar julius/config.py            — action_log_path
modificar julius/cli/_review.py       — apply(content=True, kind=True), log, resumo, coluna Tipo; remove o laço de conteúdo
modificar tests/test_config.py
modificar tests/test_cli_review.py
```

### Padrão a seguir
- `ai_log.append` é genérico e já é reaproveitado assim pelo `query_log.jsonl` do 116 — não crie módulo de log novo.
- Timestamp: `datetime.now(timezone.utc).isoformat()`, como o log de consultas do 116 faz.
- `tests/test_cli_review.py` já monkeypatcha `_review._is_interactive`; reaproveite o padrão em vez de mexer em `sys.stdin`.

## Testes obrigatórios

1. `test_config_action_log_path` — fica ao lado do banco, nome `actions.jsonl`; respeita `JULIUS_DB`.
2. `test_review_applies_content_without_asking` — com `_is_interactive` verdadeiro e **sem** `--sim`, o conteúdo proposto é gravado e **nenhum prompt de conteúdo** aparece na saída.
3. `test_review_applies_kind_automatically` — tipo proposto fica gravado em `products.kind`.
4. `test_review_logs_one_line_per_action` — `actions.jsonl` tem uma linha por campo alterado, cada uma com `product_id`, `field`, `before`, `after` e `undo`.
5. `test_review_undo_command_for_kind_without_previous` — `before is None` → `undo` é `... produtos tipo <id> --remover`.
6. `test_review_undo_command_for_content_with_previous` — produto que já tinha conteúdo → `undo` repõe o valor antigo, não remove.
7. `test_review_summary_counts_by_field` — a saída contém as contagens por campo e **não** contém nenhuma linha `julius produtos definir-conteudo <id> <qtd>` (o antigo formato de sugestão).
8. `test_review_summary_omits_zero_counts` — proposta só com nome → resumo não menciona conteúdo nem tipo.
9. `test_review_still_asks_for_ambiguous_category` — categoria com 2+ candidatas continua perguntando (regressão do comportamento que **não** muda).
10. `test_review_survives_unwritable_log` — `action_log_path` apontando para caminho impossível: a revisão aplica, não lança e mantém o código de saída 0.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -n "definir-conteudo" julius/cli/_review.py` vazio (o arquivo não sugere mais o comando; ele aplica).
- [ ] `grep -n "ultimas-acoes" julius/` vazio (é do 123).
- [ ] Rodar de verdade contra uma cópia do banco: `cp ~/.local/share/julius/prices.db /tmp/x.db && JULIUS_DB=/tmp/x.db julius produtos revisar` e conferir `/tmp/actions.jsonl`… na prática `JULIUS_DB=/tmp/x.db` põe o log em `/tmp/actions.jsonl`; conferir que existe e é JSON válido linha a linha.

## Notas para o agente
- **Não reintroduza a confirmação de conteúdo** "por segurança". A reversão é deliberada e o custo dela já foi pago no 118 (existe desfazer) e no `produtos listar` (o erro é visível). Se você achar que está errado, pare e anote — não decida dentro do ticket.
- O resumo cita comandos **sem id** de propósito: são 107 ações na primeira rodada, e a lista completa é o que o 123 entrega. Não tente imprimir os ids aqui.
- Não toque no bloco de duplicatas nem no laço de categoria: os dois são comportamento existente que este ticket preserva.
