# 123: `julius produtos revisar --ultimas-acoes` — o detalhe sob demanda

> Fecha a outra metade da decisão "resumo agregado, detalhe sob demanda": a tabela do que a IA aplicou, com o comando de desfazer de cada linha.

## Contexto

`docs/design/comparability-v2.2.md` §4.10. Requisito RF4 de `docs/requirements/comparability-closure.md` — o usuário escolheu explicitamente o resumo curto com o detalhe disponível quando quiser, em vez de ~107 linhas na primeira rodada.

Depende de **122**, que escreve `actions.jsonl`.

## Escopo

### Dentro
- `julius/infra/ai_log.py`: `tail(path, limit)` — leitor genérico de JSONL.
- `julius/cli/products.py`: flag `--ultimas-acoes` no comando `revisar`.
- `julius/cli/_review.py`: a linha de desfazer do resumo passa a apontar para a flag nova.
- Testes: `tests/test_infra_ai_log.py`, `tests/test_cli_review.py` (ou `tests/test_cli_products.py`, onde o comando `revisar` já é testado).

### Fora
- Executar o desfazer: a flag **imprime** o comando, quem roda é o usuário. Nenhum `--desfazer`.
- Filtro por produto, por campo ou por data; paginação — nada disso foi pedido.
- Comando de analytics sobre o log (mesma decisão que manteve `julius ia status` fora).
- Qualquer chamada de IA: com a flag, nada de rede, nada de orçamento.

## Requisitos

### Funcionais

- `ai_log.tail(path: Path, limit: int = 20) -> list[dict]`:
  - lê o arquivo, descarta linhas em branco e linhas que não são JSON válido (**nunca lança**, mesma disciplina do `append` no mesmo módulo).
  - devolve os últimos `limit` registros, **do mais recente para o mais antigo**.
  - arquivo inexistente ou ilegível → `[]`.

- `julius produtos revisar --ultimas-acoes`:
  - **não** abre conexão de IA, não chama `curation`, não aplica nada. Lê `config.load().action_log_path` via `ai_log.tail`.
  - imprime uma `rich.table.Table` com as colunas: `Quando` (data e hora curtas, `2026-09-16 18:53`), `ID`, `Campo`, `Antes`, `Depois`, `Desfazer`.
  - `Antes` vazio quando `before is None`; mesma coisa para `Depois`.
  - Log vazio ou inexistente → mensagem explícita, não tabela vazia: `Nenhuma ação automática registrada ainda.`
  - `--help`: "Mostra as últimas ações que a IA aplicou, com o comando para desfazer cada uma."
  - Combinada com `--sim`, a flag ganha: `--ultimas-acoes` só lê e sai.

- `_review`: a segunda linha do resumo passa de lista de comandos genéricos para o apontador único:
  ```
  Desfazer ou auditar: julius produtos revisar --ultimas-acoes
  ```

### Validação e erros
- Linha corrompida no meio do arquivo → ignorada, as demais aparecem (testar com uma linha truncada de propósito).
- Registro sem alguma chave esperada (`field`, `undo`…) → a célula sai vazia; não lançar `KeyError`.
- `limit` menor que 1 → trate como 1; não é caminho de usuário (a flag não expõe o número), então não precisa de mensagem.

## Especificação técnica

```
modificar julius/infra/ai_log.py        — tail
modificar julius/cli/products.py        — flag --ultimas-acoes em revisar
modificar julius/cli/_review.py         — linha de desfazer do resumo
modificar tests/test_infra_ai_log.py
modificar tests/test_cli_products.py
```

### Padrão a seguir
- `tail` fica ao lado de `append`, no mesmo módulo, e segue a mesma promessa de nunca lançar. Não crie `infra/jsonl.py`.
- A tabela segue o estilo das outras (`rich.table.Table` com cabeçalhos posicionais, como `cli/products.py` já faz em `listar`).
- Flag booleana no Typer: `Annotated[bool, typer.Option("--ultimas-acoes", help=...)] = False`, como `--sim` já é declarada no mesmo comando.

## Testes obrigatórios

1. `test_tail_returns_newest_first` — três registros escritos em ordem; `tail` devolve na ordem inversa.
2. `test_tail_respects_limit` — 5 registros, `limit=2` → 2 mais recentes.
3. `test_tail_skips_invalid_lines` — arquivo com uma linha truncada entre duas válidas → devolve as duas, sem lançar.
4. `test_tail_missing_file_returns_empty` — caminho inexistente → `[]`.
5. `test_cli_ultimas_acoes_prints_table` — depois de uma revisão que aplicou tipo e conteúdo, a saída contém o id do produto, o campo e o comando de desfazer.
6. `test_cli_ultimas_acoes_empty_log_message` — sem log, a saída contém "Nenhuma ação automática registrada" e o código de saída é 0.
7. `test_cli_ultimas_acoes_does_not_call_ai` — com um `ScriptedLlmClient` que falharia o teste se fosse chamado (ou monkeypatch que levanta), a flag roda sem tocá-lo.
8. `test_cli_ultimas_acoes_tolerates_partial_record` — registro sem a chave `undo` → linha impressa com a célula vazia, sem erro.
9. `test_review_summary_points_to_flag` — o resumo de uma revisão normal contém `julius produtos revisar --ultimas-acoes`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `julius produtos revisar --ultimas-acoes` num banco sem log nenhum sai 0 com mensagem, sem stack trace.
- [ ] `grep -n "desfazer\b" julius/cli/_review.py` mostra só o apontador novo, não a lista antiga de comandos.

## Notas para o agente
- A flag é o que torna a automação do 122 auditável — é a metade "sob demanda" da decisão do usuário. Não a transforme num comando novo (`julius produtos acoes`): a superfície escolhida foi a flag.
- Não implemente desfazer automático. O usuário copia e roda o comando; foi assim que ele descreveu o fluxo ("se ele quiser desfazer é só desfazer").
