# 116: CLI — `consultar` em texto livre, `--sem-tag`, log de consultas

> Liga `search_free_text` (115) na CLI: várias palavras sem aspas, `--sem-tag` como opt-out, o fallback de IA reabre quando a tag auto-detectada foi descartada, e toda chamada grava uma linha em `query_log.jsonl`.

## Contexto

`docs/design/consultar-v2.1.md` §2 (fluxo), §4.2/§4.4/§4.5 (contratos), §4.4 (por que o log fica na CLI, não no serviço). `docs/requirements/consultar-v2.1.md` RF3–RF5.

Depende de **115** (`SearchOutcome`, `search_free_text`, `detect_tag`). Antes deste ticket, `julius consultar leite laticinio` (duas palavras sem aspas) já falha na própria CLI hoje — não é regressão introduzida por este trabalho, é um bug pré-existente que este ticket corrige como parte da mudança de assinatura.

## Escopo

### Dentro
- `julius/config.py`: `Config.query_log_path` (property).
- `julius/cli/receipts.py`: assinatura de `search` (`words: list[str]` em vez de `term: Optional[str]`; nova flag `--sem-tag`), novo fluxo usando `search_free_text`, condição do fallback de IA trocada para `outcome.tag is None`, chamada a `ai_log.append` com o registro de RF5.
- Testes: `tests/test_config.py`, `tests/test_cli_receipts.py`.

### Fora
- Qualquer mudança em `services/search.py` ou `domain/models.py` (já fechado em 115).
- `guidance.py` — não muda (decisão do design §3).
- Comando de analytics sobre o log — fora de escopo (design §5).
- `julius produtos listar --tag` ou qualquer outro comando com tag — só `consultar` muda.

## Requisitos

### Funcionais

- `Config.query_log_path -> Path`: `self.db_path.parent / "query_log.jsonl"` — mesma forma de `ai_log_path` (`config.py:28-29`), uma linha.

- `cli/receipts.py::search` — nova assinatura:
  ```python
  def search(
      words: Annotated[list[str] | None, typer.Argument(help="Nome do produto e/ou tag — várias palavras sem aspas, aceita erro de digitação.")] = None,
      tag: Annotated[Optional[str], typer.Option("--tag", help="Filtra por tag marcada em `produtos tag`.")] = None,
      no_tag_detection: Annotated[bool, typer.Option("--sem-tag", help="Trata tudo como nome de produto, mesmo que uma palavra combine com uma tag conhecida.")] = False,
      limit: Annotated[int, typer.Option("--limite", "-n", min=1, help="Linhas mais recentes por unidade.")] = 20,
  ) -> None:
  ```
  `words` vira lista (Typer/Click já suporta `list[str]` como último argumento posicional convivendo com opções nomeadas — não conflita com `--tag`/`--sem-tag`/`--limite` porque essas são opções, não posicionais).

- Fluxo (substitui o corpo atual de `search()`):
  1. `words = words or []`. Sem `words` e sem `tag` → `raise typer.BadParameter("Informe um termo de busca ou --tag.")` (igual hoje).
  2. `settings = config.load()` (movido para o início da função — hoje só existe dentro de `_ai_fallback`).
  3. `no_tag_detection or tag is not None`:
     `term = " ".join(words) or None`; `records = search_service.search_prices(conn, term=term, tag=tag, limit=limit)`; `outcome = SearchOutcome(tuple(records), term, tag, detected_tag=None)`.
  4. Senão: `outcome = search_service.search_free_text(conn, words, tag=None, limit=limit)`.
  5. `hints = guidance.after_search(conn, outcome.term, outcome.tag, list(outcome.records))` — mesma função de hoje, só os argumentos vêm de `outcome`.
  6. `used_ai_fallback = False`; se `not outcome.records and outcome.term is not None and outcome.tag is None`: `fallback_records, fallback_hints = _ai_fallback(conn, outcome.term, limit)`; se `fallback_records`: `outcome = replace(outcome, records=tuple(fallback_records))` (ou equivalente — o que a CLI renderiza é `outcome.records`/`hints`), `hints = fallback_hints`, `used_ai_fallback = True`.
  7. `ai_log.append(settings.query_log_path, {...})` — ver payload abaixo. Sempre, mesmo com resultado vazio.
  8. Renderiza tabela + hints a partir de `outcome.records`/`hints` — mesma lógica de hoje (`console.print(_table(...))` por `unit`, `print_hints`).

- Payload do log (`ai_log.append`, `julius/infra/ai_log.py::append` — não muda):
  ```python
  {
      "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
      "words": list(words),
      "tag_explicit": tag,
      "detected_tag": outcome.detected_tag,
      "term_used": outcome.term,
      "tag_used": outcome.tag,
      "result_count": len(outcome.records),
      "ai_fallback": used_ai_fallback,
  }
  ```

### Validação e erros
- Sem `words` e sem `--tag`: mesmo erro de hoje, mesma mensagem.
- `ai_log.append` nunca lança (propriedade já garantida pela função existente) — não envolva a chamada em `try/except` no CLI, seria redundante.

## Especificação técnica

```
modificar julius/config.py         — + query_log_path
modificar julius/cli/receipts.py   — assinatura de search, fluxo, import de SearchOutcome/ai_log/datetime
modificar tests/test_config.py
modificar tests/test_cli_receipts.py
```

Imports novos em `cli/receipts.py`: `from datetime import datetime, timezone`, `from julius.infra import ai_log`, `from julius.domain.models import SearchOutcome` (se precisar construir/substituir a instância no passo 6 — ok também resolver isso sem `dataclasses.replace`, só recomputando as três variáveis locais que a CLI usa pra renderizar).

## Testes obrigatórios

1. `test_config.py::test_query_log_path_mirrors_ai_log_path` — mesma pasta que `ai_log_path`, nome `query_log.jsonl`.
2. `test_cli_receipts.py::test_search_accepts_multiple_words_without_quotes` — `julius consultar leite laticinio` não lança erro de parsing do Typer (fecha F3 do requirements — hoje isso falha antes mesmo de chegar no serviço).
3. `test_search_no_tag_detection_flag_forces_plain_term` — `--sem-tag` com uma palavra que bateria uma tag real ainda busca por nome de produto.
4. `test_search_explicit_tag_unchanged` — `--tag carnes` com termo continua produzindo exatamente o resultado de hoje (teste de regressão, comparar com o comportamento pré-mudança).
5. `test_search_detected_tag_reaches_ai_fallback_when_retry_is_empty` — cenário onde uma palavra bate tag, a interseção fica vazia, o retry como termo puro também fica vazio, e o fallback de IA (fake) é chamado — comportamento novo, impossível antes deste ticket.
6. `test_search_explicit_tag_never_triggers_ai_fallback` — regressão: com `--tag` explícito e resultado vazio, IA não é chamada (mesmo com fake configurado).
7. `test_search_writes_one_log_line_per_call` — duas chamadas de `consultar` geram duas linhas em `query_log_path`; campos `words`/`tag_used`/`result_count` corretos.
8. `test_search_logs_even_with_zero_results` — busca sem resultado ainda grava linha (`result_count == 0`).
9. `test_search_logs_ai_fallback_flag` — `ai_fallback: true` só na linha em que o fallback de fato devolveu registros; `false` quando não rodou ou rodou vazio.
10. `--help` de `consultar` continua funcionando e mostra a nova flag (`test_cli.py`, se for onde os testes de `--help` já vivem — confirmar local exato no código antes de escrever).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `julius consultar hortifruti` (manual, banco com produtos tageados) funciona sem `--tag`.
- [ ] `julius consultar leite laticinio` (manual) não lança erro de parsing.
- [ ] `grep -n "term: Annotated\[Optional\[str\]" julius/cli/receipts.py` vazio (assinatura antiga não sobrou).

## Notas para o agente
- Não duplique a lógica de `_ai_fallback` — só troque a condição que decide chamá-la.
- `config.load()` já é chamado dentro de `_ai_fallback` hoje; chamar de novo no início de `search()` é aceitável (é leitura de env, sem I/O de disco) — não refatore `_ai_fallback` pra receber `settings` por parâmetro, é escopo maior que este ticket.
- O separador de detalhes em hints (`" · "`) e a lógica de `guidance.after_search` não mudam — se um teste seu quebrar por causa deles, o bug está no seu código novo, não neles.
