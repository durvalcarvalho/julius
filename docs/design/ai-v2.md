# Julius v2 — IA na prática: design

> `/sc:design` de 2026-09-15, a partir de `docs/requirements/ai-v2.md` e das respostas do usuário (§0). Especificação para tickets em `docs/tickets/julius-v2/`; **nenhum código foi alterado**. Identificadores em inglês; comandos, `--help` e mensagens em português (regra dura do `CLAUDE.md`).

## 0. Decisões fechadas pelo usuário

| Questão | Decisão | Consequência no design |
|---|---|---|
| Modelo/preço | `deepseek-flash`. Screenshot da DeepSeek: input US$0,15 (off-peak) / **0,30 (peak)**; output 0,60 / **1,20**. | Recomendado exportar os preços de **pico** (`0.30` / `1.20`) para o contador nunca subestimar. Off-peak é 16:30–00:30 UTC (13:30–21:30 em Brasília); o código não sabe disso e não precisa saber. |
| Endereço | "Importante aparecer quando consultar, para saber onde ir." | Parser extrai o endereço; `stores.address` (migração 0002); `consultar` e `mercados listar` mostram; dica de filiais usa o endereço em vez de heurística de bairro. |
| Tags | Lista fixa **no banco** para sugerir + livre para cadastrar novas. | A tabela `tags` já é isso: a migração 0002 **semeia** ~13 categorias-corredor; o prompt lê `all_tag_names(conn)` (semeadas + criadas pelo usuário); a IA prefere a lista, pode propor nova (nunca automática). |
| Interação | "A solução com melhor usabilidade." | **As duas portas, um só fluxo**: `importar` roda a revisão dos produtos novos logo depois de gravar (quando IA configurada e terminal interativo); `produtos revisar` cobre pendentes, catálogo antigo (os 70 atuais) e o caso sem terminal. Mesmo código (`cli/_review.py`). |
| Nome legível | Por padrão aplica o nome legível. | Aplicado sem perguntar, com tabela "cupom → nome" impressa e desfazer por `produtos renomear`. Só para produtos **nunca renomeados à mão** (ver §5.6). |
| IA na consulta + duplicatas | Agora, salvando sempre entrada e saída. | Fallback em `consultar` quando o resultado vem vazio; detecção de duplicatas na revisão. **Toda** chamada vai para `ai_calls.jsonl` com prompt e resposta crua. |
| Smoke test | "Faz o teste via curl antes de escrever código." | §1 é um **gate**: o script está pronto; três respostas dele ajustam detalhes do cliente. |

## 1. Gate — smoke test contra a API real (antes do primeiro ticket)

As variáveis `JULIUS_AI_*` estão só no shell interativo do usuário; o agente não as vê. Script pronto: `smoke_deepseek.sh` (scratchpad da sessão; ver mensagem final). Ele lê as variáveis do ambiente ou, se ausentes, de `~/.config/julius/env` (`chmod 600`, mesmas linhas `export`). Nunca imprime a chave.

| Teste | O que manda | O que olhar | Efeito no design |
|---|---|---|---|
| T1 | JSON mínimo com `response_format: {"type": "json_object"}`, `max_tokens: 50`, sem mais nada | HTTP 200? `message.content` é JSON puro? Existe `message.reasoning_content` ou `usage.completion_tokens_details.reasoning_tokens`? Latência | Se há raciocínio por padrão: o modelo está em *thinking mode* → custo/latência maiores e JSON pode vir junto de raciocínio → **T2 decide** |
| T2 | T1 + `"thinking": {"type": "disabled"}` | 200 (aceito) ou 400 (parâmetro desconhecido) | Aceito **e** T1 mostrou raciocínio → entra `JULIUS_AI_REQUEST_EXTRAS` (§4.2) com `{"thinking":{"type":"disabled"}}`. Caso contrário a variável **não é criada** (YAGNI). |
| T3 | O prompt real de enriquecimento (§6.1) com 6 descrições reais do catálogo | JSON no formato pedido, um item por id; qualidade das expansões (`LING FGO` → linguiça de frango? `AC MASC F TER ES` mantido?); `usage` | Ajusta few-shot/instruções do prompt antes de virar código; confirma `max_tokens` por lote |
| T4 | O prompt real de duplicatas (§6.2) com 3 pares reais | `rationale` antes da decisão; Aveia FINO/REGU = diferente; Sacola = igual | Idem |

Critério para começar a implementar: T1 ou T2 devolve 200 com JSON puro e `usage.prompt_tokens`/`completion_tokens` presentes.

### 1.1 Resultado do gate (2026-09-15, `claudedocs/handoff_smoke_test_deepseek_20260915.md`)

| Teste | Resultado | Decisão |
|---|---|---|
| T1 | 200, JSON puro, **`reasoning_content` presente** → `deepseek-flash` vem em *thinking mode* por padrão | — |
| T2 | 200 com `"thinking": {"type": "disabled"}` | **`JULIUS_AI_REQUEST_EXTRAS` entra** (§4.2), default `{}`; para DeepSeek: `'{"thinking":{"type":"disabled"}}'` |
| T3 | Com thinking ligado **nunca converge**: gasta todo o `max_tokens` em raciocínio (1200, 3000 e 8000 testados), `finish_reason: length`, `content` vazio. Com thinking desligado: ~2 s, 279 tokens, JSON válido e correto | Cliente trata `finish_reason != "stop"` e `content` vazio como erro (com tokens contabilizados — pagou) |
| T4 | Funciona mesmo com thinking ligado (299 tokens de raciocínio em 500) | Sem exceção: extras valem para todas as chamadas |

Bug do script (um `}` a mais no corpo do curl) corrigido na sessão do teste; não afeta o design.

## 2. Visão geral

```
julius importar a.html b.html [--sim]
  │ por arquivo: importing.import_receipt (transação; grava stores.address)
  │ ┌─ IA configurada e há produtos novos? ─────────────────────────────────────┐
  │ │ cli/_review.review_products(conn, settings, client, new_ids, ...)          │
  │ │   curation.propose ──► suggestions.enrich_products (lotes de 25, 1 chamada)│
  │ │   aplica nomes legíveis + categorias certas; pergunta as duvidosas (TTY)   │
  │ │   confirma conteúdo (TTY) ou imprime `definir-conteudo`                    │
  │ │   curation.duplicate_candidates ──► suggestions.suggest_merges ──► imprime │
  │ │   `julius produtos fundir A B` (nunca executa)                             │
  │ └────────────────────────────────────────────────────────────────────────────┘
  └ print_hints(guidance.after_import(conn, result, reviewed=…))

julius produtos revisar [--sim]      ──► mesmo review_products sobre curation.pending_product_ids
julius consultar TERMO               ──► search vazio + IA disponível ──► suggestions.match_products
                                          ──► search.records_for_products ──► tabela + dica FOUND_VIA_AI
```

Regras que continuam valendo: IA nunca lança; orçamento checado antes de toda chamada; `consultar` com resultado só chama IA quando o determinístico veio **vazio**; fusão nunca automática; `importar` grava tudo **antes** de qualquer IA (falha de IA nunca desfaz import).

## 3. Schema — migração `0002_store_address_and_seed_tags.sql`

```sql
-- Address as printed on the receipt header; NULL until a receipt of that store is (re)imported.
ALTER TABLE stores ADD COLUMN address TEXT;

-- Aisle categories the AI is asked to prefer. Users add more with `julius produtos tag`.
INSERT OR IGNORE INTO tags (name) VALUES
    ('hortifruti'), ('carnes'), ('frios'), ('laticinios'), ('padaria'), ('mercearia'),
    ('bebidas'), ('limpeza'), ('higiene'), ('congelados'), ('temperos'), ('doces'), ('utilidades');
```

- Primeira migração real do projeto: exercita o backup `prices.db.bak-v1` no banco do usuário.
- Backfill do endereço = reimportar os HTMLs de `~/.local/share/julius/entrada/` (idempotente para `prices`; `ensure_store` passa a fazer upsert só do `address`, §4.8).
- Tags semeadas sem produto aparecem em `NO_MATCH_TRY_TAGS`/`UNKNOWN_TAG` — desejável: são o vocabulário disponível.

## 4. Contratos por módulo

### 4.1 `domain/models.py`

```python
Receipt.store_address: str | None = None          # "QUADRA QE 30, 02/39, LJS 02/39, GUARA II, BRASILIA, DF"
Store.address: str | None = None
PriceRecord.store_address: str | None = None

HintKind += "SAME_CHAIN_BRANCHES", "PRODUCTS_PENDING_REVIEW", "FOUND_VIA_AI"

@dataclass(frozen=True)
class LlmResponse:
    text: str
    input_tokens: int
    output_tokens: int
    error: str | None = None      # set => text is "" and tokens are 0; e.g. "HTTP 401", "timeout", "invalid json body"

@dataclass(frozen=True)
class ProductEnrichment:          # what the model said about one product, already validated
    readable_name: str
    tags: tuple[str, ...]         # best first; len > 1 means the model was unsure
    content: ContentSuggestion | None

@dataclass(frozen=True)
class ProductProposal:            # enrichment + deterministic decisions, ready for the CLI
    product_id: int
    current_name: str
    readable_name: str | None     # None => keep current (manually renamed before, or model kept it)
    tags: tuple[str, ...]
    tag_is_known: bool            # tags[0] exists in the tags table
    content: ContentSuggestion | None
    @property
    def auto_tag(self) -> str | None:   # single known candidate => apply without asking
        return self.tags[0] if len(self.tags) == 1 and self.tag_is_known else None

@dataclass(frozen=True)
class DuplicateCandidate:
    product_a: Product
    product_b: Product
    text_similarity: float        # rapidfuzz token_set_ratio / 100
    ai: MergeSuggestion | None
```

`ContentSuggestion` perde `confidence` (nunca foi usado para decidir; a decisão é sempre do usuário). `MergeSuggestion` mantém `same_product`, `confidence`, `rationale`.

### 4.2 `config.py`

```python
Config.ai_log_path -> Path            # property: db_path.parent / "ai_calls.jsonl"; sem variável nova
Config.ai_request_extras: dict        # JULIUS_AI_REQUEST_EXTRAS (JSON) — SÓ SE o gate T2 pedir; default {}
```

`JULIUS_AI_REQUEST_EXTRAS` é a única "abstração de provedor": um JSON mesclado no corpo do request (`thinking`, `provider`, `reasoning.exclude`…). Se T1 já vier sem raciocínio, **não criar**.

### 4.3 `infra/llm_client.py`

```python
class LlmClient(Protocol):
    def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> LlmResponse: ...
```

- Nunca lança e **nunca devolve `None`**: falha vira `LlmResponse("", 0, 0, error="…")` com a causa curta (`HTTP 429`, `timeout`, `no choices`, `empty content`). É o que o log precisa para distinguir provedor quebrado de orçamento.
- Corpo: `model`, `messages`, `temperature: 0`, `max_tokens`, `response_format: {"type": "json_object"}`, `**config.ai_request_extras`.
- `HttpLlmClient.from_config(config) -> HttpLlmClient | None` continua.

### 4.4 `infra/ai_log.py` (novo)

```python
def append(path: Path, record: Mapping[str, object]) -> None
```
Uma linha `json.dumps(record, ensure_ascii=False)` em modo append; cria a pasta; **nunca lança**. Campos gravados por `suggestions._ask`: `ts` (ISO), `call_kind`, `prompt_version`, `model`, `attempt`, `user_prompt`, `raw_response`, `parsed_ok`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`, `error`. Chamada bloqueada por orçamento também gera linha (`error: "budget_exhausted"`, sem tokens) — o silêncio fica visível. `system_prompt` não é gravado: é fixo por `(call_kind, prompt_version)`.

### 4.5 `services/suggestions.py` (reescrito)

```python
PROMPT_VERSIONS = {"enrich": "1", "merge": "2", "match": "1"}
ENRICH_BATCH_SIZE = 25
MAX_ATTEMPTS = 2                       # one retry on transport error, empty or invalid JSON

def is_available(conn, config, month=None) -> bool                                   # inalterado
def enrich_products(conn, config, client, products: Sequence[Product], known_tags: Sequence[str]) -> dict[int, ProductEnrichment]
def suggest_merges(conn, config, client, pairs: Sequence[tuple[str, str]]) -> list[MergeSuggestion | None]
def match_products(conn, config, client, term: str, catalog: Sequence[tuple[int, str, tuple[str, ...]]]) -> list[int]
```

- `_ask(conn, config, client, call_kind, user_prompt, *, max_tokens)` faz: `is_available` → até `MAX_ATTEMPTS` chamadas → soma custo de **cada** tentativa em `ai_usage` (pagou, conta) → `ai_log.append` por tentativa → `json.loads` → devolve `dict | None`. Sem regex de extração: com JSON mode a resposta é o objeto inteiro; se não for, é falha.
- Validação por função (fora disso a entrada é descartada, não o lote): `readable_name` string não vazia; `tags` 1–3 strings não vazias, minúsculas, sem duplicata; `content.quantity > 0` e `unit ∈ {L, KG, UN}`; ids devolvidos ⊆ ids enviados; `same_product` bool; `confidence ∈ [0, 1]`.
- `enrich_products` corta em lotes de 25 e mescla; um lote que falha só some do resultado (os outros seguem).
- **Removidos**: `suggest_merge` (vira `suggest_merges([...])[0]` em `catalog.compare_products`), `suggest_content`, `suggest_tags` (sem chamador; substituídos por `enrich_products`). Testes correspondentes vão junto.

### 4.6 `services/curation.py` (novo)

```python
DUPLICATE_CANDIDATE_CUTOFF = 75       # token_set_ratio; measured on the real 70-product catalog (see below)
MAX_DUPLICATE_PAIRS = 20              # one merge call per review

def pending_product_ids(conn) -> list[int]                       # products with no tag, id order
def propose(conn, config, client, product_ids: Sequence[int]) -> list[ProductProposal]
def apply(conn, proposal: ProductProposal, *, tag: str | None, content: bool) -> None
def duplicate_candidates(conn, product_ids: Sequence[int] | None = None) -> list[tuple[Product, Product, float]]
def judge_duplicates(conn, config, client, candidates) -> list[DuplicateCandidate]
```

- `propose`: carrega produtos, `known = products.all_tag_names(conn)`, chama `enrich_products`, monta propostas. `readable_name` vira `None` quando (a) o modelo devolveu o nome igual ao atual, ou (b) o produto **já foi renomeado à mão** — detectado sem coluna nova: `canonical_name` não é igual a nenhuma `prices.description` daquele produto (`products.has_raw_name(conn, id)`). `content` vira `None` se o produto já tem conteúdo.
- `apply`: uma transação — `rename_product` (se `readable_name`), `add_tag` (se `tag`), `set_content` (se `content` e `content=True`).
- `duplicate_candidates`: `token_set_ratio(normalize_text(a), normalize_text(b)) ≥ 75` entre os ids dados (ou todos) e o catálogo inteiro, pares únicos, maior score primeiro, corta em 20. Roda **depois** dos renomes, com os nomes novos.
- Medição no catálogo real (70 produtos): as 3 duplicatas verdadeiras — `TOMATE ITALIANO [UNIAO] kg` (63/69), `CEBOLA [UNIAO] kg` (5/64), `SACOLA REUTILIZAVEL UND` (2/68) — pontuam **100**; em 75 entram mais 12 pares de produtos distintos (`AG CRYSTAL C/G` × `S/G` 95, `TEMP CORAL` sabores 89,8, `AVEIA FINO` × `REGU` 85,7, `PICANHA` × `FRALDINHA` 82,6…) que a IA deve rejeitar — é exatamente o julgamento que o texto sozinho não faz (decisão v1 mantida: rapidfuzz só pré-filtra). Cortar em 80 deixaria 9 pares; 75 dá margem sem estourar um lote.
- `judge_duplicates`: só devolve o que a IA marcou `same_product=True`; IA indisponível → lista vazia (**nenhuma** sugestão só por texto — mantém a rejeição v1).

### 4.7 `services/search.py` e `services/guidance.py`

```python
search.records_for_products(conn, product_ids: Sequence[int], limit: int) -> list[PriceRecord]   # extraído de search_prices; highlight por unidade
search.catalog_for_matching(conn) -> list[tuple[int, str, tuple[str, ...]]]                     # (id, canonical_name, tags) para match_products

guidance.after_import(conn, result, *, reviewed: bool) -> list[Hint]
guidance.after_ai_fallback(records) -> list[Hint]        # [Hint("FOUND_VIA_AI", ("60 · Linguiça …", …))]
```

`after_import`, nesta ordem, cortando em `MAX_HINTS = 2`:
1. `PRODUCTS_PENDING_REVIEW` — se `not reviewed` e há produto novo sem tag; details `(str(n),)`.
2. `SAME_CHAIN_BRANCHES` — ≥ 2 lojas com o mesmo `cnpj[:8]` e ao menos uma ainda com `nickname == legal_name`; details: `"{cnpj} — {address or legal_name}"` por loja (máx. 3).
3. `FIRST_IMPORT_NAME_STORES` — como hoje.
4. `PACKAGE_SIZE_IN_DESCRIPTION` — só se `not reviewed` (a revisão já cobre conteúdo).

`cli/_hints.py`: o separador de `{details}` passa de `", "` para `" · "` (endereços têm vírgula). Textos novos:

| kind | texto |
|---|---|
| `SAME_CHAIN_BRANCHES` | `Filiais da mesma rede: {details}. Dê apelidos que digam onde fica: julius mercados renomear CNPJ "Rede — Bairro"` |
| `PRODUCTS_PENDING_REVIEW` | `{details} produto(s) novo(s) sem categoria. Nome legível, categoria e conteúdo com ajuda da IA: julius produtos revisar` |
| `FOUND_VIA_AI` | `Encontrado pela IA, não pelo nome: {details}. Pra achar direto na próxima, renomeie ou marque: julius produtos renomear ID "Nome" / julius produtos tag ID TAG` |

### 4.8 Repositórios e parser

```python
stores.ensure_store(conn, cnpj, legal_name, address: str | None = None)
# INSERT ... ON CONFLICT(cnpj) DO UPDATE SET address = COALESCE(excluded.address, stores.address)  -- nickname never touched
stores.list_stores / get_store  -> include address
prices.prices_for_products      -> SELECT s.address AS store_address; export_rows gains "store_address"
products.remove_tag(conn, product_id, tag_name) -> None        # LookupError if product/tag missing; tag row stays
products.untagged_product_ids(conn) -> list[int]
products.has_raw_name(conn, product_id) -> bool                # canonical_name == some prices.description of it
```

`parsers/df.py`: `_ADDRESS = re.compile(r"CNPJ:\s*[\d./-]+\s*</div>\s*<div>(.*?)</div>", re.DOTALL)`, limpo com `_clean`. **Opcional**: sem match → `store_address=None`, o import segue (endereço é conforto, não dado de preço). Verificado nas 5 notas reais:

| nota | endereço extraído |
|---|---|
| `qrcode.html` | `A ADE CONJUNTO 31 LOTE 01 SALA 1, S /N, LOTE 01, AGUAS CLARAS, BRASILIA, DF` |
| `qrcode-2.html` | `Q. QE 15 LOTE A, 0, , GUARA II, BRASILIA, DF` |
| `qrcode-3.html` | `QUADRA QE 30, 02/39, LJS 02/39, GUARA II, BRASILIA, DF` |
| `qrcode-4.html` | `QUADRA QR 5, 05 MU 05, , CANDANGOLANDIA, BRASILIA, DF` |
| `qrcode-5.html` | `Q SMAS Trecho 03, 0, , St Complementares, Brasilia, DF` |

Guardar como está (inclusive `, ,` e caixa mista): é texto de exibição, não chave.

## 5. CLI — comandos e UX

### 5.1 `cli/_review.py` (novo, compartilhado por `importar` e `produtos revisar`)

```python
def review_products(conn, settings: Config, client: LlmClient, product_ids: Sequence[int], *, assume_yes: bool, interactive: bool) -> None
```
`interactive = not assume_yes and sys.stdin.isatty()` é decidido no comando (testável por monkeypatch).

Saída:

```
Consultando IA para 8 produtos novos…
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ ID ┃ Cupom                                        ┃ Nome                                                     ┃ Categoria            ┃ Conteúdo ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ 60 │ LING FGO RESF AURORA kg                      │ Linguiça de frango resfriada Aurora                      │ carnes               │          │
│ 57 │ CHA LEAO RELAXA CX 16G C/10UN CAMOM/MARACUJA │ Chá Leão Relaxa camomila e maracujá caixa com 10 sachês  │ ? mercearia, bebidas │          │
│ 26 │ OVO BCO GRANDE C/30                          │ Ovo branco grande com 30                                 │ ? mercearia, hortifruti │ 30 UN │
└────┴──────────────────────────────────────────────┴──────────────────────────────────────────────────────────┴──────────────────────┴──────────┘
Aplicado: 8 nomes, 6 categorias. Desfazer: julius produtos renomear ID "Nome" · julius produtos tag ID TAG --remover
57 · Chá Leão Relaxa… — categoria  [1] mercearia  [2] bebidas  [3] outra  [Enter] pular: 1
26 · Ovo branco grande com 30 — categoria  [1] mercearia  [2] hortifruti  [3] outra  [Enter] pular: 3
    nova categoria: ovos
26 · definir conteúdo 30 UN? [S/n]: s
Possíveis duplicatas (IA):
  julius produtos fundir 68 2    # Sacola reutilizável ≈ Sacola reutilizável — mesmo produto (0,95): nomes idênticos
```

Regras:
- Nomes legíveis e categorias com **um** candidato conhecido: aplicados antes de qualquer pergunta (nunca esperam o usuário).
- Categoria com dúvida (`?`): `interactive` → pergunta numerada + "outra" (digita; cria tag nova) + Enter = pular; `assume_yes` → aplica `tags[0]`, inclusive tag nova; nem um nem outro (sem TTY) → fica pendente (a dica `PRODUCTS_PENDING_REVIEW` aparece).
- Conteúdo: `interactive` → `typer.confirm` por produto (default sim); senão imprime `julius produtos definir-conteudo ID QTD UNIDADE` pronto. **Nunca** aplica sem confirmação (decisão v1).
- Duplicatas: só imprime comandos `fundir` para pares com `same_product=True`, com `rationale`. Nunca executa.
- IA indisponível no meio (orçamento/falha): imprime o motivo em uma linha e sai sem tocar em nada — o import já está gravado.

### 5.2 Comandos

| comando | mudança |
|---|---|
| `julius importar ARQUIVO... [--sim/-y]` | Depois do loop de arquivos: se `HttpLlmClient.from_config` não é `None` e há `new_product_ids` → `review_products`. Depois, `after_import(..., reviewed=…)`. Falha em arquivo continua não afetando os outros. |
| `julius produtos revisar [--sim/-y]` | `pending_product_ids` → `review_products`. Sem pendentes: "Nenhum produto pendente de revisão." IA não configurada → dica `AI_NOT_CONFIGURED`. |
| `julius produtos tag ID TAG [--remover]` | `--remover` → `catalog.untag_product`. Pré-requisito de qualquer gravação automática. |
| `julius consultar TERMO` | Se `records` vazio, `term` dado, IA configurada e `is_available`: `match_products(term, catalog_for_matching)` → ids → `records_for_products` → tabelas normais + `after_ai_fallback`. Sem ids → dicas atuais. `--tag` desconhecida não chama IA. |
| `julius mercados listar` | Coluna **Endereço**. |
| `julius produtos comparar` | Três mensagens distintas: não configurada (dica atual) / `orçamento do mês esgotado (US$ gasto / teto)` / `falha na chamada — veja ~/.local/share/julius/ai_calls.jsonl`. Decidido na CLI: `not settings.ai_configured` → 1; `not is_available` → 2; sugestão `None` → 3. |
| `julius exportar` | Coluna `store_address`. |

### 5.3 `consultar` com endereço

Célula **Mercado** em duas linhas: apelido e, embaixo em `dim`, o endereço (quando existe). Mantém a tabela com as mesmas colunas e diferencia filiais mesmo com apelido igual.

```
│ 2026-09-07 │ Tomate italiano │ Dona de Casa                                         │ R$ 8,99 │
│            │                 │ QUADRA QE 30, 02/39, LJS 02/39, GUARA II, BRASILIA, DF │         │
```

## 6. Prompts (versão inicial; texto exato vira constante em `suggestions.py`)

Comum a todos: temperatura 0, `response_format json_object`, a palavra "json" no system prompt, exemplo literal do formato, `rationale` antes da decisão quando há decisão.

### 6.1 `enrich` (v1) — `max_tokens = 120 × itens no lote + 200`

```
SYSTEM
Você organiza um catálogo pessoal de compras de supermercado no Brasil. As descrições vêm de cupons
fiscais (NFC-e): maiúsculas, sem acento, muito abreviadas. Para cada produto devolva:
- "readable_name": nome legível em português com acentos, mantendo marca, variante/sabor e tamanho
  quando aparecem. Não invente o que a abreviação não permite deduzir: na dúvida, mantenha a palavra
  abreviada como está. Não repita a unidade de venda (kg/UN) no fim.
- "tags": de 1 a 3 categorias, a mais provável primeiro, escolhidas de preferência da lista
  "categorias". Devolva UMA só quando tiver certeza; 2 ou 3 quando houver dúvida real entre elas.
  Só proponha uma categoria fora da lista se nenhuma servir.
- "content": conteúdo total da embalagem, {"quantity": número, "unit": "L"|"KG"|"UN"}, apenas quando a
  descrição deixa isso inequívoco (500G → 0.5 KG; 1.5L → 1.5 L; C/30 → 30 UN). null quando não há
  tamanho, quando é ambíguo, ou quando o produto é vendido por peso (termina em "kg").
Responda somente com um objeto json exatamente neste formato, um item por produto recebido, mesmos ids:
{"products": [{"id": 1, "readable_name": "...", "tags": ["..."], "content": {"quantity": 1, "unit": "KG"}}]}

Exemplo de entrada:
categorias: ["hortifruti", "carnes", "laticinios", "bebidas", "mercearia", "limpeza"]
produtos:
1 | LING FGO RESF AURORA kg
2 | REFRI ANT GUARANA PET 1.5L
3 | CHA LEAO RELAXA CX 16G C/10UN CAMOM/MARACUJA
4 | AC MASC F TER ES 1kg
Exemplo de saída:
{"products": [
 {"id": 1, "readable_name": "Linguiça de frango resfriada Aurora", "tags": ["carnes"], "content": null},
 {"id": 2, "readable_name": "Refrigerante Antarctica Guaraná PET 1,5L", "tags": ["bebidas"], "content": {"quantity": 1.5, "unit": "L"}},
 {"id": 3, "readable_name": "Chá Leão Relaxa camomila e maracujá caixa 16g com 10 sachês", "tags": ["mercearia", "bebidas"], "content": null},
 {"id": 4, "readable_name": "AC MASC F TER ES 1kg", "tags": ["mercearia"], "content": {"quantity": 1, "unit": "KG"}}
]}

USER
categorias: [<all_tag_names>]
produtos:
<id> | <canonical_name>
...
```

### 6.2 `merge` (v2) — `max_tokens = 80 × pares + 100`

```
SYSTEM
Você compara pares de descrições de produtos de supermercado brasileiro (maiúsculas, sem acento,
abreviadas) e decide se cada par é o MESMO produto para fins de comparar preço. Sabor, tamanho e tipo
diferentes tornam produtos diferentes mesmo com nome-base igual. Marca/fornecedor diferente em
hortifruti (tomate, cebola) não torna diferente. Responda somente com json neste formato, mesmos ids,
escrevendo o "rationale" ANTES da decisão:
{"pairs": [{"id": 1, "rationale": "até 20 palavras", "same_product": true, "confidence": 0.7}]}

Exemplo de entrada:
1 | A: TOMATE ITALIANO kg | B: TOMATE ITALIANO UNIAO kg
2 | A: REFRI PEPSI PET 2L | B: REFRI ANT GUARANA PET 1.5L
3 | A: AVEIA QUAK 450G FINO | B: AVEIA QUAK 450G REGU
Exemplo de saída:
{"pairs": [
 {"id": 1, "rationale": "mesma variedade; UNIAO é só o fornecedor", "same_product": true, "confidence": 0.7},
 {"id": 2, "rationale": "sabor e tamanho diferentes", "same_product": false, "confidence": 0.95},
 {"id": 3, "rationale": "mesma marca e peso, mas flocos finos e regulares são produtos distintos", "same_product": false, "confidence": 0.85}
]}

USER
<n> | A: <name_a> | B: <name_b>
...
```

### 6.3 `match` (v1) — `max_tokens = 200`

```
SYSTEM
O usuário digitou um termo de busca num catálogo pessoal de supermercado. Dado o catálogo (id | nome | tags),
devolva os ids dos produtos que correspondem ao termo: mesmo produto, sinônimo, abreviação, ou categoria
óbvia (ex.: "carne" → picanha, fraldinha, linguiça). Nada corresponde → lista vazia. Responda somente com
json: {"ids": [60, 61]}

USER
termo: <term>
catálogo:
<id> | <canonical_name> | <tags separadas por vírgula>
...
```

## 7. Arquitetura (DAG) — onde cada coisa mora

| camada | novo/alterado | importa |
|---|---|---|
| `domain` | `models.py` (novos dataclasses, `HintKind`) | nada |
| `config` | `ai_log_path`, (`ai_request_extras`) | nada |
| `infra` | `llm_client.py` (JSON mode, `error`), `ai_log.py`, `migrations/0002_*.sql` | `domain`, `config` |
| `parsers` | `df.py` (`_ADDRESS`) | `domain` |
| `repositories` | `stores.py`, `prices.py`, `products.py` | `domain` |
| `services` | `suggestions.py` (reescrito), `curation.py` (novo), `search.py`, `guidance.py`, `catalog.py` (`untag_product`, `compare_products`) | `domain`, `config`, `infra`, `parsers`, `repositories` |
| `cli` | `_review.py` (novo), `receipts.py`, `products.py`, `stores.py`, `_hints.py` | tudo acima |

`tests/test_architecture.py` não muda. Nenhuma dependência nova (`urllib`, `json`, `typer.prompt`, `rich`).

## 8. Testes (por módulo; rede sempre fake; JSONL em `tmp_path`)

- **parser**: endereço extraído das 5 notas bate a tabela de §4.8; HTML sem o bloco de endereço → `store_address=None` e import segue.
- **db/migração 0002**: banco v1 com dados → backup `prices.db.bak-v1`, coluna `address`, 13 tags semeadas, dados intactos; banco novo nasce direto em v2.
- **repositories**: `ensure_store` preenche `address` em loja existente sem tocar `nickname`; `remove_tag` feliz/triste; `untagged_product_ids`; `has_raw_name` falso após `rename_product`.
- **llm_client**: 200 → `LlmResponse` sem `error`; 401/timeout/JSON inválido/`choices` vazio → `error` preenchido, nunca exceção; corpo contém `response_format`, `max_tokens`, extras.
- **ai_log**: uma linha por chamada; pasta criada; caminho inescrevível não lança.
- **suggestions**: fake devolve JSON válido → parse e custo somado; inválido na 1ª e válido na 2ª → 1 retry, 2 linhas de log, custo das duas; `error` duas vezes → `None`/vazio; orçamento estourado → nenhuma chamada ao fake e linha `budget_exhausted` no log; ids fora do lote e tags inválidas descartados; lote de 60 produtos → 3 chamadas.
- **curation**: `auto_tag` só com um candidato conhecido; produto renomeado à mão não recebe `readable_name`; `duplicate_candidates` no banco dos 5 recibos contém (63,69), (5,64), (2,68) e nada abaixo de 75; `judge_duplicates` sem IA → vazio.
- **guidance**: ordem e corte das 4 dicas de import; `SAME_CHAIN_BRANCHES` dispara com os dois CNPJs do Dona de Casa e não dispara quando ambos já têm apelido; `after_ai_fallback`.
- **cli**: `importar` com fake aplica nomes/tags e imprime tabela; sem TTY não pergunta e deixa pendente; `--sim` aplica `tags[0]`; `revisar` sem pendentes; `tag --remover`; `consultar` vazio + fake com ids → tabela + `FOUND_VIA_AI`; fake sem ids → dicas antigas; `comparar` com as 3 mensagens; `mercados listar` com endereço; célula Mercado com duas linhas.
- **e2e**: importar as 5 notas com fake determinístico → `produtos listar` com nomes legíveis e tags; `consultar --tag carnes` retorna picanha/fraldinha/contra-filé/linguiça/bacon; reimportar não duplica nem repete a revisão (produtos não são novos).

## 9. Ordem sugerida de tickets (`docs/tickets/julius-v2/`)

| # | escopo | depende de |
|---|---|---|
| 101 | parser: endereço + `Receipt.store_address` | — |
| 102 | migração 0002 + repositórios (`stores` upsert/address, `prices` address/export, `products` remove_tag/untagged/has_raw_name) + models `Store`/`PriceRecord` | — |
| 103 | `config.ai_log_path` (+ extras se o gate pedir) + `llm_client` JSON mode/`error` + `ai_log` | — |
| 104 | `suggestions` reescrito (3 funções, retry, log, prompts) + `catalog.compare_products` | 103 |
| 105 | `curation` | 102, 104 |
| 106 | `search.records_for_products`/`catalog_for_matching` + `guidance` (3 dicas, `reviewed`) + `_hints` (textos, separador) | 102 |
| 107 | CLI: `mercados listar`, `consultar` (endereço + fallback), `comparar` (3 mensagens), `tag --remover`, `exportar` | 104, 106 |
| 108 | CLI: `_review.py` + `importar` integração + `produtos revisar` | 105, 106 |
| 109 | e2e + `CLAUDE.md`/README (§10) + reimport dos 5 HTMLs reais para backfill do endereço | tudo |

## 10. `CLAUDE.md` — o que atualizar ao fechar

- "Status": v2 (IA em uso real); provedor DeepSeek `deepseek-flash`; orçamento US$5; preços de pico.
- "Camada opcional de IA": cliente HTTP **existe** (não é ticket futuro); JSON mode; `LlmResponse.error`; log JSONL; funções atuais de `suggestions`; princípio revisado: "IA grava o reversível (nome, tag), nunca o irreversível (fusão, preços)".
- "Requisitos novos" item 2 (`produtos pendentes`) → resolvido por `produtos revisar`. Item 3 → coberto pela revisão.
- Pegadinha "Filiais": acrescentar a prova dos endereços (QE 30 Guará II × QR 5 Candangolândia) e que a identidade de rede é `cnpj[:8]`.
- "Identidade de produto e busca": nomes legíveis pela IA são a solução durável para abreviações; fallback de IA só em resultado vazio.
- Schema: colar a migração 0002.

## 11. Fora do escopo (inalterado)

Fallback automático entre provedores · `reasoning`/streaming/tool calling · fusão automática · veredito de preço · embeddings · cache de respostas de IA · Telegram/OCR · IA em resultado não vazio de `consultar`.
