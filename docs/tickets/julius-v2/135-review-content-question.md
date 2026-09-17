# 135: `_review` — a pergunta de conteúdo, com candidatos de intuição

> A única pergunta que sobra na revisão: quando a IA recusou dizer o conteúdo, o humano escolhe entre os candidatos ou digita.

## Contexto

`docs/design/review-scope-v2.3.md` §5 (o laço), §7 (`--sim`), §1 questões 7 e 8. Requisitos RF5/RF6 de `docs/requirements/review-scope-v2.3.md`.

O gatilho é a **recusa da IA**, não um score: o prompt de produção acertou o `null` em 6 de 6, enquanto `confidence`, número de tags e auto-avaliação de certeza falharam. A intuição de varejo (ticket 133) sabe que brócolis é bandeja (`1 UN`) e que prato descartável é pacote de `10` ou `20` — e também transformou `Filme PVC 30m x 28cm` em `30 UN` se dizendo certa. **Por isso ela só alimenta as opções e nunca grava.**

Depende de **133** (`suggest_packaging`, `PackagingHint`) e **134** (a tela já sem a pergunta de categoria).

## Escopo

### Dentro
- `julius/cli/_review.py`: `_FORM_LABELS`, `_ask_content`, o laço de conteúdo, chamada de `suggest_packaging`, redefinição de `--sim`.
- `julius/cli/products.py`: texto do `--help` de `--sim` no comando `revisar`.
- `julius/cli/receipts.py`: texto do `--help` de `--sim` no `importar` (só o texto).
- Testes: `tests/test_cli_review.py`.

### Fora
- `suggestions.suggest_packaging` (fechado no 133) e `curation.apply` (já serve).
- Reintroduzir qualquer pergunta de categoria, nome ou tipo.
- Gravar candidato de intuição sem tecla do usuário — em qualquer variante, inclusive quando o candidato é `1 UN` (RF6).
- Marcar "esse produto não tem conteúdo" ao pular — recusado duas vezes nos requisitos.
- Insistir na pergunta após entrada inválida.
- Limite de perguntas por execução.

## Requisitos

### Funcionais

- **Quem entra no laço**: proposta com `content is None` **e** `proposal.sold_by_unit` verdadeiro **e** produto ainda sem conteúdo gravado. Produto vendido por KG nunca entra.

- **Quando a segunda chamada acontece** — só quando todas valerem:
  1. a revisão é interativa (`_is_interactive()` e não `--sim`);
  2. existe ao menos um produto no laço;
  3. `suggestions.is_available(conn, settings)`.
  Uma chamada só, com todos os produtos do laço. Indisponível ou falhou → segue sem candidatos (não é erro).

- **A pergunta**, uma linha por produto, com `typer.prompt` e escolha por número:
  ```
  31 · Brócolis Ninja — conteúdo  [1] 1 UN · unidade  [2] digitar  [Enter] pular:
  55 · Prato Redondo Descartável 21cm — conteúdo  [1] 10 UN · pacote  [2] 20 UN · pacote  [3] digitar  [Enter] pular:
  ```
  - O nome exibido é `proposal.readable_name or proposal.current_name`, como `_ask_tag` fazia.
  - `digitar` é sempre a última opção numerada; `Enter` pula.
  - **Nenhum texto livre da IA aparece na tela.** `form` vira palavra fixa por `_FORM_LABELS`: `unit → "unidade"`, `pack → "pacote"`, `volume → "volume"`, `weight → "peso"`, `unknown → ""` (sem sufixo ` · `).

- **Sem candidatos** — IA indisponível, lista vazia, **ou `form` em `weight`/`unknown`** — a pergunta sai só com `digitar` e `pular`:
  ```
  34 · Bacon Excelência tablete — conteúdo  [1] digitar  [Enter] pular:
  ```
  Suprimir candidato de `weight` é o que mantém `500 KG` de bacon fora da tela: foi exatamente aí que a intuição produziu lixo.

- **`digitar`** abre um segundo prompt (`"    quantidade e unidade (ex.: 500 G)"`) e aceita a mesma gramática do comando manual: número, espaço, unidade em `L/ML/KG/G/UN`. Converte por `normalize_content` — o mesmo caminho de `julius produtos definir-conteudo`, para não existirem duas gramáticas de conteúdo.

- **Gravação** pelo caminho que já existe, para a ação entrar no log com desfazer:
  ```python
  curation.apply(conn, replace(proposal, readable_name=None, content=chosen), tag=None, content=True, kind=False)
  ```
  e o `AppliedAction` resultante vai para `actions.jsonl` por `_log_actions`, como qualquer outro.

- **`--sim` é redefinido** para "não perguntar nada": com ele, o laço não roda, a segunda chamada não acontece e o conteúdo recusado fica pendente. `--help` do `revisar` e do `importar` passa a dizer: *"Não perguntar nada; conteúdo que a IA não soube fica pendente para a próxima revisão."*

- A contagem de pendentes do 134 passa a refletir o que sobrou **depois** do laço.

### Validação e erros
- Entrada inválida (letra, número fora da faixa, unidade desconhecida, quantidade ≤ 0): imprime o erro em uma linha e **trata como pular**. Não repete a pergunta, não interrompe o laço, não muda o código de saída.
- `normalize_content` lança `ValueError` para unidade desconhecida — capture no laço, não deixe subir.
- Sem TTY, o laço não roda: nenhum `typer.prompt` é chamado (é o que impede travar num script).

## Especificação técnica

```
modificar julius/cli/_review.py     — _FORM_LABELS, _ask_content, laço de conteúdo, suggest_packaging, --sim
modificar julius/cli/products.py    — --help de --sim
modificar julius/cli/receipts.py    — --help de --sim
modificar tests/test_cli_review.py
```

### Padrão a seguir
- `_ask_tag` (removido no 134) é o molde da pergunta: `typer.prompt(..., default="", show_default=False)`, `answer.strip()`, `isdigit()`, faixa válida, senão `None`.
- `replace(proposal, ...)` de `dataclasses` já era usado pelo laço de conteúdo da v2 (removido no ticket 122); é o mesmo padrão.
- `ScriptedLlmClient(by_kind={...})` já distingue a chamada `"packaging"` desde o 133; os testes passam `enrich`, `packaging` e `merge` no mesmo cliente.
- Ordem dentro de `review_products`: tabela → passada automática → log → **resumo** → laço de conteúdo → duplicatas → pendentes. O resumo sai **antes** do laço, para o usuário saber o que já foi feito antes de começar a responder.

## Testes obrigatórios

1. `test_content_question_offers_candidates` — IA de enrich recusa o conteúdo, `packaging` devolve `pack` com `10 UN` e `20 UN`; a saída traz `[1] 10 UN · pacote` e `[2] 20 UN · pacote`; responder `1` grava `10 UN`.
2. `test_content_question_typed_value` — escolher a opção `digitar` e responder `500 G` grava `0,5 KG` (prova o reaproveitamento de `normalize_content`).
3. `test_content_question_enter_skips_and_stays_pending` — Enter não grava nada e o produto entra na contagem de pendentes.
4. `test_content_question_invalid_input_is_treated_as_skip` — responder `xyz`, e depois `500 OZ` na opção digitar: nada gravado, código de saída 0, laço não trava.
5. `test_content_question_suppresses_candidates_for_weight_form` — `packaging` devolve `form: "weight"` com candidato `500 KG` → a saída **não** contém `500 KG`, e a pergunta sai só com `digitar`/`pular`.
6. `test_content_question_without_packaging_call_still_asks` — cliente que falha na chamada `packaging` → pergunta sem opções numeradas, sem erro.
7. `test_content_question_skipped_for_kg_product` — produto vendido por KG sem conteúdo → nenhuma pergunta.
8. `test_content_question_not_asked_without_tty` — `_is_interactive` falso → nenhuma pergunta, nenhuma chamada `packaging` (`client.calls` sem item do tipo packaging), produto pendente.
9. `test_sim_asks_nothing_and_leaves_pending` — `--sim` com TTY → nenhuma pergunta, nenhuma chamada `packaging`, conteúdo não gravado.
10. `test_content_answer_is_logged_with_undo` — depois de responder, `actions.jsonl` tem a linha `field="content"` com `undo` igual a `julius produtos definir-conteudo <id> --remover`.
11. `test_ai_refusal_is_the_only_trigger` — produto cujo enrich **devolveu** conteúdo não é perguntado, mesmo com `packaging` tendo candidatos para ele.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `test_revisar_applies_content_without_asking` (do ticket 122) **continua passando sem edição** — conteúdo lido do rótulo nunca pergunta.
- [ ] `grep -n "1 UN" julius/services julius/repositories -r` vazio — nenhum candidato de intuição é gravado fora da CLI.
- [ ] Rodar de verdade contra uma cópia do banco real, com a chave configurada: `cp ~/.local/share/julius/prices.db /tmp/r.db && JULIUS_DB=/tmp/r.db julius produtos revisar`, e conferir que a pergunta de conteúdo aparece para Brócolis/Prato/Espátula e que responder grava.
- [ ] `tests/test_architecture.py` verde sem edição.

## Notas para o agente
- **O candidato errado vai aparecer na tela** (`Filme PVC → 30 UN`). Isso é o desenho funcionando: pular é a resposta certa, e é justamente por esse caso que a intuição não grava sozinha. Não tente filtrá-lo com heurística nem mexer no prompt do 133.
- **Não** faça o Enter gravar "não tem conteúdo". Pular é pular; o produto volta na próxima rodada. Recusado duas vezes nos requisitos.
- `--sim` continua com esse nome mesmo tendo mudado de sentido. Renomear foi avaliado e recusado (design §7) — atualize só o `--help`.
- Não imprima o resumo agregado de novo depois do laço: as respostas entram no log, e o resumo já saiu.
