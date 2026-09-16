# Julius v2.1 — `consultar` em texto livre + log de consultas: design

> `/sc:design` de 2026-09-16, a partir de `docs/requirements/consultar-v2.1.md` e da pesquisa de bibliotecas (`claudedocs/research_v21_consultar_natural_language_20260916.md`: nenhuma dependência nova — `rapidfuzz` e `typer` já resolvem, e `infra/ai_log.py::append` já é genérico). Especificação para tickets 115/116 em `docs/tickets/julius-v2/`; **nenhum código foi alterado**.

## 0. Decisões fechadas pelo usuário (do requirements, §4)

| Questão | Decisão | Consequência no design |
|---|---|---|
| Tag detectada + termo | Interseção | `search_free_text` chama `search_prices(term=resto, tag=detectada)` — mesma função, sem branch nova em `_candidate_ids`. |
| Interseção vazia | Retry como termo puro | `search_free_text` chama `search_prices` uma segunda vez, `tag=None`, antes de devolver. |
| Log serve pra | Buscas que falham + analytics de uso | Grava por chamada, não por linha de resultado; `Counter` do usuário sobre o JSONL responde as duas perguntas, sem SQL nem comando novo. |

## 1. Medição do corte de tag (fecha Q1 do requirements)

Medido com `rapidfuzz.fuzz.ratio` sobre normalização já existente (`domain.normalization.normalize_text`): as 71 descrições reais únicas dos 6 fixtures (`tests/fixtures/*.html`, via `DFReceiptParser`) + 30 palavras comuns de mercado (leite, arroz, queijo, carne, picanha…) contra as 13 tags semeadas, e variantes de 1 edição de cada tag contra ela mesma.

| Métrica | Valor | Caso |
|---|---|---|
| Pior falso positivo real | **71.4** | `PAPRICA` vs `PADARIA` (também `TEMP`→`TEMPEROS` 66.7, `DESC`→`DOCES` 66.7 — nenhum passa de 71.4) |
| Pior erro de digitação (1 edição) que precisa entrar | **80.0** | `FIROS`/`FRISO`/`FROIS`→`FRIOS`; `AOCES`→`DOCES` |
| Caso correto por natureza (não é falso positivo) | 90.9 | `CARNE` (singular) vs `CARNES` — singular/plural deve mesmo bater |
| Confusão entre as 13 tags entre si | ≤ 55 | `PADARIA`↔`MERCEARIA` 50 — sem risco de uma tag ser confundida com outra |
| Erros de 2 edições | caem a ~60 | fora do alcance de qualquer corte razoável — mesma limitação já aceita em `MATCH_SCORE_CUTOFF` (corrige 1 letra, não reconstrói a palavra) |

Gap limpo entre 71.4 e 80.0 → **`TAG_MATCH_CUTOFF = 75`**, mesmo estilo (número redondo, margem dos dois lados) de `MATCH_SCORE_CUTOFF`/`NEAR_MISS_CUTOFF`.

## 2. Visão geral

```
julius consultar <words...> [--tag T] [--sem-tag] [-n N]
   │
   ├─ --sem-tag ou --tag T explícito ──► search_prices(join(words), T)      [caminho de hoje, intacto]
   │
   └─ senão ──► search_free_text(conn, words, tag=None, limit)
                  │  detect_tag(words) contra as 13 tags (TAG_MATCH_CUTOFF=75)
                  │
                  ├─ nada bate ──► search_prices(join(words), tag=None)
                  │
                  └─ bate "X" ──► search_prices(resto, tag=X)
                                    ├─ não-vazio ──► usa
                                    └─ vazio ──► retry: search_prices(join(words), tag=None)   [RF3]
   │
   resultado final vazio E outcome.tag is None? ──► fallback de IA, como hoje (cli/receipts.py::_ai_fallback)
   │
   sempre ──► ai_log.append(query_log.jsonl, {...})       [RF5]
   │
   renderiza tabela + hints — inalterado
```

Regras que continuam valendo: `search_prices` não muda de assinatura nem de comportamento (rede de segurança dos testes de cutoff/highlight existentes); IA nunca é chamada por `search_free_text`; `--tag` explícito nunca perde nem ganha comportamento.

## 3. Por que nenhum novo `HintKind` (fecha uma questão do requirements §7)

Detecção de tag bem-sucedida (com ou sem retry) não é erro, nem resultado vazio, nem "primeira vez" — os únicos 3 gatilhos que `guidance.py` já usa (`CLAUDE.md` § "Dicas de uso", princípio 2: "nunca em saída normal cheia — dica em cima de resultado bom vira ruído"). Auto-detecção é o caminho normal desta feature, não um fallback degradado. **Nenhuma mudança em `guidance.py`.**

Verificado no código atual (`services/guidance.py::after_search`): a lógica que decide `NO_MATCH_DID_YOU_MEAN` já testa `search_prices(conn, term=term)` sem tag pra não sugerir "você quis dizer" quando o termo bate mas a tag zerou a interseção. Por construção de `search_free_text` (retry no vazio), sempre que `outcome.records` está vazio, `outcome.tag` já é `None` — então `after_search(conn, outcome.term, outcome.tag, outcome.records)` cai exatamente no caminho "busca sem tag" que já existe, sem caso novo a tratar.

## 4. Contratos por módulo

### 4.1 `domain/models.py`

```python
@dataclass(frozen=True)
class SearchOutcome:
    """O que `consultar` fez de fato com as palavras livres: qual (se alguma) virou tag
    automaticamente, e se um resultado vazio por tag foi descartado e reexecutado como termo puro."""
    records: tuple[PriceRecord, ...]
    term: str | None
    tag: str | None
    detected_tag: str | None = None   # candidata encontrada, mesmo se descartada pelo retry
```
`retried_without_tag` não é campo — é `detected_tag is not None and tag is None`, derivável por quem consumir (ver `cli/receipts.py` no log de RF5).

### 4.2 `config.py`

```python
@property
def query_log_path(self) -> Path:
    return self.db_path.parent / "query_log.jsonl"
```
Mirror de `ai_log_path` — mesma linha, mesmo padrão (`db_path.parent / "<nome>.jsonl"`).

### 4.3 `services/search.py`

```python
TAG_MATCH_CUTOFF = 75
"""Corte mínimo de fuzz.ratio (0-100) pra uma palavra do texto livre contar como tag.
Medido: pior falso positivo real (71 descrições dos 6 fixtures + vocabulário comum de mercado)
é "PAPRICA" vs "PADARIA" = 71.4; pior erro de digitação de 1 edição que precisa entrar é 80.0
("FIROS"/"FROIS" -> "FRIOS"). 75 mantém margem dos dois lados. Erros de 2 edições (ex. "AACES"
vs "DOCES" = 60) ficam de fora, mesma limitação já aceita em MATCH_SCORE_CUTOFF."""

def detect_tag(conn: sqlite3.Connection, words: Sequence[str]) -> tuple[str | None, str | None]:
    """Testa cada palavra de `words` (já tokenizada pela CLI) contra `products.all_tag_names(conn)`
    via fuzz.ratio + TAG_MATCH_CUTOFF. Devolve (termo_restante, tag) usando a palavra de maior
    score acima do corte; (" ".join(words) or None, None) se nenhuma bater."""

def search_free_text(
    conn: sqlite3.Connection, words: Sequence[str], tag: str | None = None, limit: int = 20
) -> SearchOutcome:
    """Ponto de entrada de `consultar` pra texto livre. Se `tag` já veio explícito, detecção
    nunca roda (equivalente a search_prices(term=" ".join(words), tag=tag, limit=limit)) — zero
    mudança pra quem já usa --tag. Senão, tenta detect_tag; achando, busca com
    (termo_restante, tag_detectada); interseção vazia -> retry com (words inteiro, tag=None).
    Nunca chama IA."""
```
`search_prices` (existente) fica **inalterado**; `search_free_text` só o chama, até duas vezes.

### 4.4 `cli/receipts.py`

```python
def search(
    words: Annotated[list[str], typer.Argument(help="Nome do produto e/ou tag — várias palavras sem aspas, aceita erro de digitação.")] = None,
    tag: Annotated[Optional[str], typer.Option("--tag", ...)] = None,          # inalterado
    no_tag_detection: Annotated[bool, typer.Option("--sem-tag", help="Trata tudo como nome de produto, mesmo que uma palavra combine com uma tag conhecida.")] = False,
    limit: Annotated[int, typer.Option("--limite", "-n", ...)] = 20,           # inalterado
) -> None: ...
```

Fluxo (substitui o corpo atual):
1. Sem `words` e sem `--tag` → erro (`typer.BadParameter`, igual hoje).
2. `no_tag_detection` ou `tag is not None` → `term = " ".join(words) or None`; `records = search_prices(conn, term, tag, limit)`; `outcome = SearchOutcome(tuple(records), term, tag, detected_tag=None)`.
3. Senão → `outcome = search_free_text(conn, words, tag=None, limit=limit)`.
4. `hints = guidance.after_search(conn, outcome.term, outcome.tag, list(outcome.records))` — **sem mudança na função**, só nos argumentos passados.
5. `not outcome.records and outcome.term is not None and outcome.tag is None` → `_ai_fallback(conn, outcome.term, limit)` como hoje — **a condição troca `tag` (parâmetro crú) por `outcome.tag`** (fecha Q2 do requirements: reabre o fallback quando a tag foi auto-detectada e descartada, continua fechado quando `--tag` foi explícito, porque nesse caso `outcome.tag == tag` nunca é `None` a menos que o próprio usuário não tenha passado tag).
6. `ai_log.append(settings.query_log_path, {...})` — sempre, depois do fallback resolvido, pra incluir se ele foi usado. Ver §4.5.
7. Renderiza tabela + hints — inalterado.

`settings = config.load()` passa a ser carregado no início de `search()` (hoje só é carregado dentro de `_ai_fallback`); `_ai_fallback` continua carregando o seu próprio por conta da instanciação do `HttpLlmClient` — duplicar o `config.load()` é aceitável (idempotente, sem I/O real) e evita mudar a assinatura de `_ai_fallback`.

### 4.5 Log de consultas (`ai_log.append`, reaproveitado — fecha Q3/RF5)

```python
ai_log.append(settings.query_log_path, {
    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "words": list(words),
    "tag_explicit": tag,
    "detected_tag": outcome.detected_tag,
    "term_used": outcome.term,
    "tag_used": outcome.tag,
    "result_count": len(outcome.records),
    "ai_fallback": used_ai_fallback,   # bool, True só se _ai_fallback rodou e devolveu registros
})
```
`infra/ai_log.py::append` não muda — já é genérico (`Mapping[str, object]`, nunca lança). Zero infraestrutura nova, só o call site.

**Por que na CLI e não dentro de `search_free_text` (diferente de como `suggestions.py` loga de dentro do serviço):** o log de RF5 precisa saber se o fallback de IA rodou, e essa decisão é tomada na CLI (`_ai_fallback` é chamado por `cli/receipts.py`, não por `services/search.py`). `ai_calls.jsonl` loga tentativas de chamada de IA — um assunto intrínseco ao cliente LLM, resolvido dentro do serviço que o usa. `query_log.jsonl` loga "o que essa invocação de `consultar` fez do início ao fim" — só a CLI tem a foto completa. `cli` pode importar `infra` diretamente (regra da DAG em `CLAUDE.md` § "Estrutura de pacote"), então não há violação de camada.

## 5. Fora de escopo (herdado do requirements §7, sem mudança)

Comando de analytics dedicado (`jq`/`python -c` com `collections.Counter` sobre `query_log.jsonl` cobre, mesma decisão já tomada pra não criar `julius ia status`) · tag multi-palavra (nenhuma das 13 tags precisa) · novo `HintKind` (§3 acima) · tabela SQL pro log (JSONL já resolve com zero migração).

## 6. Arquitetura (DAG) — onde cada coisa mora

| camada | novo/alterado | importa |
|---|---|---|
| `domain` | `models.py` (`SearchOutcome`) | nada |
| `config` | `query_log_path` | nada |
| `services` | `search.py` (`TAG_MATCH_CUTOFF`, `detect_tag`, `search_free_text`) | `domain`, `repositories` (já importava) |
| `cli` | `receipts.py` (`search`: assinatura, fluxo, log) | `domain`, `config`, `infra` (`ai_log`), `services` |

`guidance.py` **não muda** (§3). `tests/test_architecture.py` não muda. Nenhuma dependência nova.

## 7. Testes (rede não entra em nenhum destes; nenhuma chamada de IA)

- `detect_tag`: cada palavra de uma lista bate a tag certa (`hortifruti`, com erro de 1 letra); nenhuma bate → `(join, None)`; duas palavras, só uma bate → só ela é consumida, resto vira termo; lista vazia → `(None, None)`.
- `search_free_text`: `tag` explícito pula detecção inteiramente (mesmo resultado que `search_prices` direto); só tag (`["hortifruti"]`) → `term=None`; termo+tag detectados com interseção não-vazia; interseção vazia → retry confirmado (resultado igual ao de `search_prices(term=join, tag=None)`); nenhuma palavra bate tag → `detected_tag is None`.
- `cli/receipts.py::search`: `julius consultar leite laticinio` (duas palavras, sem aspas) não quebra o parsing (fecha F3 do requirements); `--sem-tag` ignora uma palavra que bateria tag; `--tag` explícito inalterado (teste de regressão); log grava uma linha por chamada, inclusive em erro de disco simulado (não lança); fallback de IA dispara quando a tag foi auto-detectada e descartada (cenário novo, hoje impossível).
- `Config.query_log_path`: mirror do teste existente de `ai_log_path`.

## 8. Riscos herdados da medição (§1)

- **Erros de 2 edições não são cobertos** (ex. `AACES` vs `DOCES` = 60) — mesma limitação que o projeto já aceita para nome de produto; não é regressão, é o mesmo compromisso.
- **Vocabulário de tags crescer** pode reabrir a medição (uma tag nova poderia colidir com uma palavra de produto comum) — revisitar `TAG_MATCH_CUTOFF` se `julius produtos tag` criar tags fora do vocabulário-corredor original.
