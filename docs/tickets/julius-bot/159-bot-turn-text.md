# 159: `bot/turn.py` — o turno de texto: orçamento, agente, resposta ou pendência

<!-- status:done implemented:2026-09-17 commit:2a03260 -->
<!-- adjustments: result.usage é propriedade no pydantic-ai 2.44, não result.usage() -->

> A função que os testes exercitam sem Telegram: recebe deps e o texto, devolve o que responder. É aqui que o princípio "o código responde, o modelo só roteia" vira código.

## Contexto

`docs/design/telegram-bot.md` §4.1, §4.2, §4.4 (estado em memória) e §5.1 (orçamento e logs). Uma mensagem autorizada passa por: pendência viva → cancela; orçamento → checa; agente → roda **uma** vez; saída → renderiza ou vira pendência; tokens → cobra e loga pelos mesmos `ai_usage`/`ai_calls.jsonl` da curadoria (ticket 152); consulta → `query_log.jsonl`.

Depende de **152** (`record_usage`), **154** (render), **158** (agente). 160 acrescenta o turno do tap ao mesmo módulo.

## Escopo

### Dentro
- `julius/bot/turn.py`: `HISTORY_TURNS`, `ChatState`, `Reply`, `handle_text`, `_render_output` (despacho por tipo), `_log_query`.
- `tests/test_bot_turn.py` (160 acrescenta).

### Fora
- `handle_tap`, expiração de pendência (→ 160). Aqui a pendência só é **criada** e, se já existia, **cancelada** por um texto novo.
- Qualquer objeto do `python-telegram-bot` — o turno não sabe o que é um `Update`.
- Dicas (`guidance`), fallback de IA do `consultar` (a IA já está no caminho).

## Requisitos

### Funcionais

```python
HISTORY_TURNS = 3

@dataclass
class ChatState:
    runs: list[list[ModelMessage]] = field(default_factory=list)   # um item por turno concluído; só os últimos HISTORY_TURNS
    pending: PendingWrite | None = None

    @property
    def history(self) -> list[ModelMessage]: ...   # runs achatados, na ordem

@dataclass(frozen=True)
class Reply:
    text: str                           # HTML do Telegram, já passado por render/fit
    pending: PendingWrite | None = None # quando o app deve anexar os botões

async def handle_text(agent: BotAgent, state: ChatState, deps: Deps, text: str) -> Reply
```

Passos de `handle_text`, nesta ordem:

1. **Pendência viva** (`state.pending is not None`): `state.pending = None`; a resposta final ganha o prefixo `"Ação anterior cancelada.\n\n"`. (Expirada ou não — o 160 refina para cancelar em silêncio a expirada.)
2. **Orçamento**: `if not suggestions.is_available(deps.conn, deps.config)`: chama `record_usage(conn, config, "bot_turn", attempt=0, user_prompt=text, raw_response=None, parsed_ok=False, input_tokens=0, output_tokens=0, latency_ms=0, error="budget_exhausted", prompt_version=BOT_PROMPT_VERSION)` e devolve `Reply(f"Orçamento de IA do mês esgotado (US$ {gasto:.2f} de US$ {teto:.2f}). O bot volta no mês que vem; a CLI continua funcionando.")` com `spent_this_month`/`config.ai_budget_usd` — **sem** chamar o agente.
3. **Agente**: `started = time.monotonic()`; `result = await agent.run(text, deps=deps, message_history=state.history)`. Exceção de qualquer tipo → `record_usage(..., attempt=1, error=f"agent raised {type(exc).__name__}", tokens 0, latency medida)` e `Reply("Não consegui falar com a IA agora. Tente de novo em instantes.")` — o turno **nunca** propaga.
4. **Cobrança**: `usage = result.usage()`; `record_usage(conn, config, "bot_turn", attempt=1, user_prompt=text, raw_response=_output_kind(result.output), parsed_ok=True, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, latency_ms=…, error=None, prompt_version=BOT_PROMPT_VERSION)`. `_output_kind` → `"text"`, `"SearchOutcome"`, `"StoreComparison"`, `"ProductListing"`, `"StoreListing"`, `"PendingWrite:{action}"`.
5. **Histórico**: `state.runs.append(result.new_messages())`; corta para os últimos `HISTORY_TURNS`. Turnos inteiros, nunca mensagens soltas — cortar no meio deixaria uma chamada de ferramenta sem retorno na história, e a API recusa.
6. **Despacho** (`_render_output`):
   - `str` → `escape(texto)` — o **único** caso em que prosa do modelo chega ao usuário;
   - `SearchOutcome` → `render_records(outcome.records)` **e** `_log_query(config, outcome)`;
   - `StoreComparison` → `render_comparison`;
   - `ProductListing` → `render_products(listing.products)`; `StoreListing` → `render_stores(listing.stores)`;
   - `PendingWrite` → `state.pending = output`; `Reply(render_pending(output), pending=output)`.
7. Prefixo do passo 1, se houver, vai antes do texto.

`_log_query(config, outcome)` — `ai_log.append(config.query_log_path, {...})` com as **mesmas chaves** de `cli/receipts.py::search` (`ts` UTC, `words`, `tag_explicit`, `detected_tag`, `term_used`, `tag_used`, `result_count`, `ai_fallback`) mais `"channel": "bot"`. `words` = `outcome.term.split()` se houver termo, senão `[]`; `tag_explicit` = `None` (o bot não distingue tag digitada de detectada — a IA preencheu); `ai_fallback` = `False`.

### Validação e erros
- Fora do orçamento → **zero** chamadas ao modelo (o `FunctionModel` do teste conta).
- Uma resposta de leitura nunca contém texto gerado pelo modelo (a saída foi de uma ação; o modelo não teve a palavra).
- `handle_text` nunca lança; toda falha vira `Reply` e uma linha em `ai_calls.jsonl` com `error`.

## Especificação técnica

```
criar julius/bot/turn.py
criar tests/test_bot_turn.py
```

Imports: `pydantic_ai.messages` (`ModelMessage`), `julius.services.suggestions` (`is_available`, `spent_this_month`, `record_usage`), `julius.infra.ai_log`, `julius.bot.{actions, agent, render}`, `julius.domain.models`.

### Padrão a seguir
- Rodar o turno nos testes: `asyncio.run(handle_text(agent, state, deps, "…"))` — sem `pytest-asyncio`.
- `Config` de teste: `config.load({"JULIUS_DB": str(tmp_path/"prices.db"), "JULIUS_AI_API_KEY": "k", "JULIUS_AI_BASE_URL": "https://x/v1", "JULIUS_AI_MODEL": "m", "JULIUS_AI_INPUT_PRICE_USD_PER_1M": "0.30", "JULIUS_AI_OUTPUT_PRICE_USD_PER_1M": "1.20", "JULIUS_AI_BUDGET_USD": "5"})` — os logs caem em `tmp_path`.
- `FunctionModel` como em 155; para simular tokens, o `FunctionModel` já reporta uso (>0) — o teste afirma `> 0`, não um número.

## Testes obrigatórios

1. `test_budget_exhausted_answers_without_calling_the_model` — `ai_usage.add_spent(conn, mês, 5.0)` antes; resposta contém "esgotado" e "US$ 5,00"/"5.00"; contador do modelo == 0; linha em `ai_calls.jsonl` com `error == "budget_exhausted"`.
2. `test_read_reply_is_rendered_from_the_database` — modelo chama `search_prices(words="picanha")`; texto contém `Preços por KG` e o preço real da fixture; **não** contém o texto que o `FunctionModel` devolveria como prosa (não há prosa).
3. `test_read_turn_charges_and_logs` — `ai_usage.spent_in_month > 0`; última linha de `ai_calls.jsonl` tem `call_kind == "bot_turn"`, `prompt_version == "1"`, `raw_response == "SearchOutcome"`; `query_log.jsonl` tem uma linha com `channel == "bot"` e `result_count`.
4. `test_write_turn_creates_pending_and_writes_nothing` — `rename_product` → `reply.pending is not None`, `state.pending is reply.pending`, texto começa com "⚠️", `canonical_name` inalterado.
5. `test_text_while_pending_cancels_it` — estado com pendência; novo texto (modelo devolve prosa) → `state.pending is None`, texto começa com "Ação anterior cancelada.".
6. `test_plain_text_output_is_escaped_and_returned` — modelo devolve `"Oi <você>"` → `"Oi &lt;você&gt;"`.
7. `test_agent_exception_is_a_reply_not_a_crash` — `FunctionModel` que lança → `Reply` com "Não consegui falar com a IA"; `ai_calls.jsonl` com `error` começando por "agent raised".
8. `test_history_keeps_only_the_last_three_turns_whole` — quatro turnos → `len(state.runs) == 3` e `state.history` começa numa mensagem do 2º turno.
9. `test_empty_listing_renders_the_empty_message` — catálogo vazio, `list_products` → "Nenhum produto importado ainda."

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; `tests/test_architecture.py` verde (`turn.py` importa `domain`, `infra`, `services`, `bot`).
- [ ] `grep -n "import telegram\|from telegram" julius/bot/turn.py` **vazio**.
- [ ] `grep -n "repositories" julius/bot/turn.py` **vazio** (cobrança via `suggestions.record_usage`).

## Notas para o agente

- `result.output` é o retorno **real** da ação; nunca leia `result.all_messages()` para "descobrir o que o modelo quis dizer".
- O texto do orçamento usa `money`? Não — orçamento é em dólar; formate `US$ {x:.2f}` direto (ponto decimal, como o `produtos comparar` já imprime).
- Não introduza `HISTORY_MESSAGES` (contagem de mensagens): a unidade é o turno, pelo motivo do passo 5.
