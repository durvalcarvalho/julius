# 105: Config `ai_log_path` / `ai_request_extras` e `infra/ai_log.py`

> Caminho do log JSONL derivado do banco, extras de request por variável de ambiente (exigidos pelo gate: DeepSeek precisa de `thinking: disabled`) e um escritor de log que nunca lança.

## Contexto

`docs/design/ai-v2.md` §1.1 (resultado do gate), §4.2 e §4.4. O smoke test mostrou que `deepseek-flash` raciocina por padrão e **não converge** no prompt de enriquecimento; a correção é enviar `{"thinking": {"type": "disabled"}}` no corpo — específico do provedor, logo vai por variável, não hardcode. O log é o que torna visível o silêncio de "IA não sugeriu nada" (orçamento? erro? resposta inválida?).

Sem dependências. Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/config.py`: campo `ai_request_extras: dict[str, object]` (default `{}`), leitura de `JULIUS_AI_REQUEST_EXTRAS`; property `ai_log_path`.
- `julius/infra/ai_log.py`: `append(path, record)`.
- `tests/test_config.py`, novo `tests/test_ai_log.py`.

### Fora
- Usar os extras no cliente (→ 106). Escrever o log a partir do serviço (→ 107). Rotação/leitura do log. Comando `ia status`.

## Requisitos

### Funcionais
- `Config.ai_request_extras`: `dataclasses.field(default_factory=dict)`, **último** campo (construtores existentes por keyword continuam válidos). `load`: ausente/vazio → `{}`; JSON de objeto → o dict; JSON válido que não é objeto (lista, número) ou JSON inválido → `ValueError(f"JULIUS_AI_REQUEST_EXTRAS must be a JSON object, got {raw!r}")` — mesmo estilo de `_optional_float`.
- `Config.ai_log_path` (property): `self.db_path.parent / "ai_calls.jsonl"`. Sem variável nova: o log mora ao lado do banco (`JULIUS_DB` já muda os dois juntos).
- `ai_log.append(path: Path, record: Mapping[str, object]) -> None`: `path.parent.mkdir(parents=True, exist_ok=True)`; abre em `"a"`, `encoding="utf-8"`; escreve `json.dumps(record, ensure_ascii=False, default=str) + "\n"`. Qualquer exceção (pasta inescrevível, disco cheio, objeto não serializável) → engole e retorna. Nunca lança, nunca loga o erro do log.

### Validação e erros
- Só a de `JULIUS_AI_REQUEST_EXTRAS` acima; erro sobe em `config.load()` como já acontece com preço não numérico.

## Especificação técnica

```
modificar julius/config.py
criar     julius/infra/ai_log.py
modificar tests/test_config.py
criar     tests/test_ai_log.py
```

`ai_log.py` importa só `json` e `pathlib`/`typing` (camada `infra`, sem dependência interna).

## Testes obrigatórios

1. `test_config.py::test_request_extras_default_is_empty_dict`
2. `test_request_extras_parses_json_object` — `'{"thinking":{"type":"disabled"}}'` → dict igual.
3. `test_request_extras_rejects_non_object_or_invalid_json` — parametrizado: `'[1]'`, `'42'`, `'{oops'` → `ValueError` com o nome da variável.
4. `test_ai_log_path_sits_next_to_db` — `JULIUS_DB=/x/y/prices.db` → `/x/y/ai_calls.jsonl`.
5. `test_ai_log.py::test_append_creates_parent_and_writes_one_json_line_per_call` — 2 chamadas → 2 linhas, cada uma `json.loads`-ável, acentos preservados (`ensure_ascii=False`).
6. `test_append_never_raises_when_path_is_unwritable` — `path = tmp_path / "file" / "ai_calls.jsonl"` onde `tmp_path/"file"` é um arquivo → retorna sem exceção.
7. `test_append_serializes_unknown_types_with_str` — `Path` num campo vira string.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; `tests/test_architecture.py` verde.
- [ ] `JULIUS_AI_REQUEST_EXTRAS='{"thinking":{"type":"disabled"}}' python -c 'from julius import config; print(config.load().ai_request_extras)'` imprime o dict.

## Notas para o agente
- Não crie `JULIUS_AI_LOG` nem `JULIUS_AI_THINKING`: o design fechou uma variável genérica de extras e caminho derivado.
- `Config` continua `frozen=True`; um `dict` dentro de dataclass frozen é permitido (só não é hashable — ninguém faz hash de `Config`).
