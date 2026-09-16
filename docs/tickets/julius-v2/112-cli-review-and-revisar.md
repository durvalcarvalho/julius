# 112: CLI — `_review.py` e `julius produtos revisar`

> A tela da curadoria: tabela "cupom → nome legível / categoria / conteúdo", aplicação automática do que é certo, pergunta numerada para o que é dúvida, confirmação de conteúdo, e a lista de possíveis duplicatas com o comando `fundir` pronto. Mais o comando que roda isso sobre os produtos pendentes.

## Contexto

`docs/design/ai-v2.md` §5.1 (fluxo, saída de exemplo, regras) e §0 (decisões: nome legível por padrão; conteúdo sempre confirmado; `--sim` para uso sem terminal). `importar` vai reaproveitar exatamente este módulo (→ 113): não duplique lógica lá.

Depende de 109 (`curation`) e 110 (textos/dicas). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/cli/_review.py` (novo): `review_products(...)`, `_is_interactive()`.
- `julius/cli/products.py`: comando `revisar`.
- `tests/test_cli_review.py` (novo).

### Fora
- Integração no `importar` e flag `--sim` dele (→ 113). Fundir automaticamente (nunca). Cores além de `dim`/tabela padrão.

## Requisitos

### Funcionais
- `review_products(conn, settings: Config, client: LlmClient, product_ids: Sequence[int], *, assume_yes: bool, interactive: bool) -> bool` — devolve `True` se houve propostas processadas, `False` se a IA não devolveu nada (indisponível ou falha). Passos:
  1. `console.status("Consultando IA para N produto(s)…")` em volta de `curation.propose`. Sem propostas: imprime **um** motivo e devolve `False`: `not suggestions.is_available(conn, settings)` → `IA indisponível: orçamento do mês esgotado.`; senão `IA não respondeu (veja {settings.ai_log_path}).`
  2. Tabela (`rich.table.Table`) colunas `ID | Cupom | Nome | Categoria | Conteúdo`: `Cupom = current_name`; `Nome = readable_name or current_name`; `Categoria = auto_tag` ou `"? " + ", ".join(tags)` quando há dúvida; `Conteúdo = f"{q:g} {unit}"` ou vazio.
  3. Aplica **antes de perguntar**: para toda proposta, `curation.apply(conn, p, tag=p.auto_tag, content=False)` (nome legível sempre; tag só a automática). Imprime `Aplicado: {n_nomes} nome(s), {n_tags} categoria(s). Desfazer: julius produtos renomear ID "Nome" · julius produtos tag ID TAG --remover`.
  4. Para cada proposta **sem** `auto_tag` (dúvida ou tag desconhecida):
     - `interactive` → prompt numerado numa linha: `{id} · {nome} — categoria  [1] a  [2] b  [3] outra  [Enter] pular: `; dígito válido → aplica a tag; opção "outra" → `typer.prompt("    nova categoria")` → aplica (cria a tag); Enter/entrada inválida → pula (fica pendente).
     - `assume_yes` → aplica `tags[0]` mesmo se desconhecida (cria).
     - nenhum dos dois → pula.
  5. Para cada proposta com `content`: `interactive` → `typer.confirm(f"{id} · {nome} — definir conteúdo {q:g} {unit}?", default=True)` → `curation.apply(conn, dataclasses.replace(p, readable_name=None), tag=None, content=True)` (o nome já foi aplicado no passo 3); senão imprime `julius produtos definir-conteudo {id} {q:g} {unit}` pronto (também com `--sim`: conteúdo **nunca** é gravado sem confirmação humana).
  6. Duplicatas: `curation.duplicate_candidates(conn, product_ids)` → `curation.judge_duplicates(...)`; se houver, cabeçalho `Possíveis duplicatas (IA):` e uma linha por par: `  julius produtos fundir {b.id} {a.id}    # {a.nome} ≈ {b.nome} — mesmo produto ({confiança:.2f}): {rationale}` (origem = maior id, destino = menor id). Nunca executa.
  7. Resumo final: `Pendentes: N produto(s) sem categoria.` quando N > 0.
- `_is_interactive() -> bool` = `sys.stdin.isatty()`; função de módulo para o teste substituir.
- `julius produtos revisar [--sim/-y]`: `settings = config.load()`; `client = HttpLlmClient.from_config(settings)`; `client is None` → `print_hints(guidance.for_compare(settings))`, exit 0; `ids = curation.pending_product_ids(conn)`; vazio → `Nenhum produto pendente de revisão.`; senão `review_products(conn, settings, client, ids, assume_yes=yes, interactive=not yes and _is_interactive())`.

### Validação e erros
- Falha de IA no meio (propostas vazias) não altera o banco. `LookupError`/`ValueError` de `apply` → `fail`.
- Prompt em stdin fechado nunca acontece: sem TTY, `interactive` é `False`.

## Especificação técnica

```
criar     julius/cli/_review.py
modificar julius/cli/products.py
criar     tests/test_cli_review.py
```

`_review.py` importa: `sys`, `typer`, `rich.table`, `julius.cli._common` (`console`), `julius.config.Config`, `julius.domain.models`, `julius.infra.llm_client.LlmClient`, `julius.services.{curation, suggestions}`.

## Testes obrigatórios (`tests/test_cli_review.py`; `CliRunner`; env `JULIUS_AI_*` setado; `HttpLlmClient` substituído por stub em `julius.cli.products`; `ScriptedLlmClient(by_kind=...)`; `monkeypatch.setattr(_review, "_is_interactive", lambda: True/False)`)

Fixture base: `qrcode.html` importado (15 produtos), fake `enrich` cobrindo alguns ids com `readable_name`, tags e `content`, fake `merge` com um par `same_product: true`.

1. `test_revisar_applies_readable_names_and_single_known_tags_without_prompt` — `produtos listar` depois mostra nome novo e tag.
2. `test_revisar_prints_table_with_cupom_and_new_name_columns`.
3. `test_revisar_prompts_for_ambiguous_tag_and_applies_choice` — `input="1\n" + "s\n"...` conforme a ordem das perguntas.
4. `test_revisar_other_option_creates_new_tag` — `"3\novos\n"` → tag `ovos` existe e está no produto.
5. `test_revisar_enter_skips_and_reports_pending`.
6. `test_revisar_content_confirmed_or_declined` — parametrizado `"s"`/`"n"` → `content_quantity` definido ou `None`.
7. `test_revisar_non_interactive_without_sim_applies_only_auto_and_prints_content_commands`.
8. `test_revisar_sim_applies_first_tag_even_if_unknown_and_never_writes_content`.
9. `test_revisar_prints_fundir_command_for_confirmed_duplicate_and_does_not_merge` — contagem de `products` inalterada.
10. `test_revisar_without_ai_shows_not_configured_hint`.
11. `test_revisar_with_nothing_pending`.
12. `test_revisar_budget_exhausted_prints_reason_and_changes_nothing` — `JULIUS_AI_BUDGET_USD=0`.
13. `test_revisar_ai_error_prints_log_path_and_changes_nothing` — fake com `error` nas duas tentativas.
14. `test_revisar_skips_rename_for_manually_renamed_product` — integra `has_raw_name`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; `tests/test_architecture.py` verde.
- [ ] `julius produtos revisar --sim` com IA configurada e um banco de **cópia** do real termina sem erro e `produtos listar` mostra nomes legíveis e tags (teste manual do usuário; registre no commit os números: quantos automáticos, quantos pendentes, tempo).

## Notas para o agente
- Nome legível é aplicado **antes** das perguntas para que uma pergunta interrompida (Ctrl-C) não deixe o produto sem o nome que já veio.
- `typer.confirm`/`typer.prompt` só quando `interactive`; nunca chame `sys.stdin.isatty()` direto fora de `_is_interactive`.
- Não persista "já perguntei": produto pulado volta a aparecer no próximo `revisar` (regra 3 do módulo de dicas, mesma filosofia).
