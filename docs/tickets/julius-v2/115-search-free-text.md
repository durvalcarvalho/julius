# 115: `SearchOutcome` + `detect_tag`/`search_free_text` em `services/search.py`

> Ensina a busca a reconhecer uma tag dentro do texto livre (`"hortifruti"`, `"leite laticinio"`), com interseção e retry automático quando a tag detectada zera o resultado — sem tocar em `search_prices` nem em `guidance`.

## Contexto

`docs/design/consultar-v2.1.md` §1 (medição do corte), §4.1 e §4.3 (contratos). `docs/requirements/consultar-v2.1.md` RF1–RF3.

Hoje `--tag` já faz interseção com `term` (`_candidate_ids`, em `julius/services/search.py`) e tag é match exato (`repositories/products.py::product_ids_with_tag`). Este ticket adiciona **detecção automática** de tag dentro de uma lista de palavras — sem mudar `search_prices` nem `_candidate_ids`. Ninguém chama `search_free_text` ainda: a integração na CLI é o ticket 116, que depende deste.

## Escopo

### Dentro
- `julius/domain/models.py`: `SearchOutcome` (novo dataclass).
- `julius/services/search.py`: `TAG_MATCH_CUTOFF` (constante), `detect_tag`, `search_free_text`.
- Testes: `tests/test_services_search.py`.

### Fora
- Qualquer mudança em `cli/receipts.py`, `config.py`, `guidance.py` (→ ticket 116; `guidance.py` não muda em nenhum ticket, ver design §3).
- Log de consultas (RF5) — não é deste módulo (→ ticket 116).
- Flag `--sem-tag` — é decisão da CLI de *não chamar* `search_free_text`, não algo que este módulo precise saber (→ ticket 116).
- Mudar `search_prices`, `_candidate_ids` ou `product_ids_with_tag` — continuam exatamente como estão.

## Requisitos

### Funcionais

- `SearchOutcome` (`domain/models.py`, `@dataclass(frozen=True)`):
  ```python
  records: tuple[PriceRecord, ...]
  term: str | None
  tag: str | None
  detected_tag: str | None = None
  ```
  Sem campo `retried_without_tag` — é derivável (`detected_tag is not None and tag is None`), não grave o que já é calculável.

- `TAG_MATCH_CUTOFF = 75` (`services/search.py`, ao lado de `MATCH_SCORE_CUTOFF`/`NEAR_MISS_CUTOFF`). Docstring cita a medição real (ver design §1): pior falso positivo real 71.4 (`PAPRICA` vs `PADARIA`), pior erro de digitação de 1 edição que precisa entrar 80.0 (`FIROS`/`FROIS` vs `FRIOS`).

- `detect_tag(conn: sqlite3.Connection, words: Sequence[str]) -> tuple[str | None, str | None]`:
  - Normaliza cada palavra com `normalize_text` (já importado em `search.py`) e compara contra `products.all_tag_names(conn)` (também normalizadas) via `fuzz.ratio`.
  - Se alguma palavra tiver score `>= TAG_MATCH_CUTOFF` contra alguma tag: a palavra de **maior score entre todas as combinações palavra×tag** é a detectada. Empate: a que aparece primeiro em `words`.
  - Retorna `(" ".join(palavras restantes) or None, tag_detectada)`.
  - Nenhuma palavra bate → `(" ".join(words) or None, None)`.
  - `words` vazio → `(None, None)`.

- `search_free_text(conn: sqlite3.Connection, words: Sequence[str], tag: str | None = None, limit: int = 20) -> SearchOutcome`:
  - `tag is not None` (explícito) → **não chama `detect_tag`**. `term = " ".join(words) or None`; `records = search_prices(conn, term=term, tag=tag, limit=limit)`; devolve `SearchOutcome(tuple(records), term, tag, detected_tag=None)`.
  - `tag is None` → chama `detect_tag(conn, words)`.
    - Nenhuma tag detectada → `records = search_prices(conn, term=join(words) or None, tag=None, limit=limit)`; devolve `SearchOutcome(tuple(records), term, None, detected_tag=None)`.
    - Tag detectada (`resto`, `tag_x`) → `records = search_prices(conn, term=resto, tag=tag_x, limit=limit)`.
      - `records` não vazio → devolve `SearchOutcome(tuple(records), resto, tag_x, detected_tag=tag_x)`.
      - `records` vazio → **retry**: `records = search_prices(conn, term=join(words) or None, tag=None, limit=limit)`; devolve `SearchOutcome(tuple(records), join(words) or None, None, detected_tag=tag_x)` (nota: `detected_tag` continua preenchido mesmo descartado — é o que permite derivar "houve retry").
  - Nunca chama IA, nunca lança (segue a mesma disciplina de `search_prices`: erro de uso, ex. lista vazia sem nenhuma palavra, é o mesmo `ValueError` que `search_prices` já lança quando `term is None and tag is None`).

### Validação e erros
- `search_free_text` não introduz validação nova além da que `search_prices` já tem (`limit < 1` → `ValueError`, já testado). Não duplicar essa checagem.

## Especificação técnica

```
modificar julius/domain/models.py       — + SearchOutcome
modificar julius/services/search.py     — + TAG_MATCH_CUTOFF, detect_tag, search_free_text
modificar tests/test_services_search.py
```

### Padrão a seguir
`detect_tag` deve ler `products.all_tag_names(conn)` (já existe, `repositories/products.py:72`) e usar `rapidfuzz.fuzz` — já importado em `search.py` (`from rapidfuzz import fuzz, process`). Reaproveite `normalize_text` (já importado de `julius.domain.normalization`), o mesmo usado em `_matching_ids`/`closest_names` no mesmo arquivo. Não crie uma segunda função de normalização.

## Testes obrigatórios

1. `test_detect_tag_matches_single_word_with_typo` — `["leite", "laticinio"]` (singular, tag real é `laticinios`) → `("leite", "laticinios")`.
2. `test_detect_tag_matches_whole_query_as_pure_tag` — `["hortifruti"]` → `(None, "hortifruti")`.
3. `test_detect_tag_no_match_returns_joined_term` — `["frango", "assado"]` (nenhuma bate tag) → `("frango assado", None)`.
4. `test_detect_tag_empty_words` — `([])` → `(None, None)`.
5. `test_detect_tag_ignores_words_below_cutoff` — uma palavra com score baixo contra qualquer tag (ex. `"queijo"`) não é consumida.
6. `test_search_free_text_explicit_tag_skips_detection` — `tag="carnes"` explícito com `words=["picanha"]` dá o mesmo resultado que `search_prices(term="picanha", tag="carnes")`; `detected_tag is None` no outcome.
7. `test_search_free_text_detects_tag_and_intersects` — cenário com produtos tageados; `words=["leite", "laticinios"]` retorna só o(s) produto(s) com a tag E que casam com "leite"; `outcome.tag == "laticinios"`.
8. `test_search_free_text_empty_intersection_retries_as_pure_term` — tag detectada mas a interseção com o termo restante é vazia; o resultado final é igual a `search_prices(term=join(words), tag=None)`; `outcome.tag is None`; `outcome.detected_tag` continua preenchido.
9. `test_search_free_text_pure_tag_query` — `words=["hortifruti"]` (só a tag) retorna os produtos daquela tag, `outcome.term is None`.
10. `test_search_free_text_no_tag_detected_behaves_like_plain_term` — nenhuma palavra bate tag → resultado igual a `search_prices(term=join(words), tag=None)`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `search_prices` e `_candidate_ids` sem diff (`git diff` restrito às adições listadas).

## Notas para o agente
- Não mova nem refatore `_candidate_ids`/`search_prices` — eles são a rede de segurança dos testes de highlight/cutoff já existentes.
- `detected_tag` fica preenchido mesmo quando descartado pelo retry — é dado, não bug; o ticket 116 usa isso pro log de consultas.
- Não adicione nenhum `HintKind` nem toque em `guidance.py` — decisão já fechada no design (§3): auto-detecção bem-sucedida não é gatilho de dica.
