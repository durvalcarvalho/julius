# 181: `bot/turn.py` — fixar o primeiro turno na rotação de histórico

> Troca `del state.runs[:-HISTORY_TURNS]` (só os últimos N turnos) por uma política que também fixa o turno 1 pra sempre, sem aumentar o número de turnos enviados por chamada.

## Contexto

`docs/design/entity-resolution-architecture.md`, Frente B. Achado real (monkey test, 2026-09-22): 5 perguntas seguidas (banana, cebola, tomate, uva, "o que eu perguntei primeiro?") — o bot respondeu "você começou perguntando de cebola", errado (foi banana). `HISTORY_TURNS = 3` já tinha descartado o turno da banana quando a 5ª pergunta chegou. Reforçar o `SYSTEM_PROMPT` (tentado na sessão anterior, `BOT_PROMPT_VERSION` 5) não mudou o comportamento numa reprodução ao vivo — o problema nunca foi o modelo ignorar uma instrução, foi o turno 1 não estar mais em lugar nenhum que ele pudesse consultar (o "grounding gap" documentado em `claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md`).

Não depende de nenhum ticket anterior desta trilha (é o único ticket de código).

## Escopo

### Dentro
- `julius/bot/turn.py`: nova função `_trim_history`, substituindo a linha `del state.runs[:-HISTORY_TURNS]` dentro de `handle_text`.
- `tests/test_bot_turn.py`: testes novos (unidade da função isolada + reprodução do incidente via `FunctionModel`).

### Fora
- Qualquer estado novo persistido, tabela nova, ou aumento de `HISTORY_TURNS` — a correção é só a política de seleção de quais turnos ficam, com o mesmo número de turnos de hoje.
- A pendência mais ampla de "lista de compras conversacional" (`docs/requirements/shopping-list-conversation-context.md`, RF4–RF6) — continua fora de escopo, não é fechada por este ticket.
- Qualquer mudança em `SYSTEM_PROMPT`/`BOT_PROMPT_VERSION` — o reforço de prompt já foi tentado e medido como insuficiente; este ticket não mexe em prompt.

## Requisitos

### Funcionais

`_trim_history(runs: list[list[ModelMessage]]) -> list[list[ModelMessage]]`:
- Se `len(runs) <= HISTORY_TURNS`: devolve `runs` sem alteração (mesmo comportamento de hoje quando a conversa ainda é curta).
- Se `len(runs) > HISTORY_TURNS`: devolve `runs[:1] + runs[-(HISTORY_TURNS - 1):]` — o primeiro turno, mais os últimos `HISTORY_TURNS - 1` turnos. Nunca mais que `HISTORY_TURNS` turnos no total (mesmo custo de token de hoje).
- `handle_text` troca a linha `del state.runs[:-HISTORY_TURNS]` por `state.runs = _trim_history(state.runs)` (ou equivalente in-place), no mesmo ponto onde já roda hoje (depois de `state.runs.append(result.new_messages())`).

### Validação
- `HISTORY_TURNS` continua sendo a única constante que controla o tamanho da janela — não introduzir uma segunda constante pro "quantos turnos recentes além do primeiro".
- Função pura, sem efeito colateral, sem tocar `conn`/`deps` — só reorganiza a lista já em memória.

### Casos de borda
- `len(runs) == 0`: devolve `[]` (não deve nunca acontecer em uso real, mas a função não pode lançar).
- `len(runs) == 1`: devolve `runs` inalterado (não há o que cortar).
- `HISTORY_TURNS == 1` (hipotético, não é o valor de hoje): `runs[:1] + runs[-0:]` — atenção ao caso `-(HISTORY_TURNS - 1)` virar `-0` quando `HISTORY_TURNS == 1`; `runs[-0:]` em Python devolve a lista inteira, não vazia — a função precisa tratar esse caso explicitamente (`if HISTORY_TURNS <= 1: devolve só o último turno`, ou equivalente) pra não duplicar turnos. Cobrir com teste mesmo não sendo o valor de produção hoje.

## Especificação técnica

```
modificar julius/bot/turn.py — nova função _trim_history; handle_text passa a usá-la
modificar tests/test_bot_turn.py — testes novos
```

### Padrão a seguir
- `_trim_history` fica perto de `_tool_note`/`_search_narration_context` (funções privadas de apoio a `handle_text`, mesmo estilo de docstring citando o incidente real que motivou a mudança — ver essas duas como exemplo de formato).
- Docstring da função precisa citar o achado real (a reprodução banana/cebola/tomate/uva) e por que reforço de prompt não bastou, mesmo padrão de justificativa que toda constante/decisão deste projeto carrega.

## Testes obrigatórios

1. `test_trim_history_short_conversation_is_unchanged` — `len(runs) <= HISTORY_TURNS` devolve a lista igual.
2. `test_trim_history_pins_the_first_turn` — sequência de 5 turnos sintéticos (`["banana"], ["cebola"], ["tomate"], ["uva"], ["quinta"]`, cada um um placeholder de lista de `ModelMessage`, não precisa ser uma mensagem real) → resultado é `[turno1, turno4, turno5]` (o mesmo padrão verificado por simulação de índice no design).
3. `test_trim_history_never_drops_the_immediately_previous_turn` — o turno imediatamente anterior ao atual está sempre presente no resultado, qualquer que seja o tamanho da conversa (garante que os loops de `quantity_needed`/`ambiguous_unit`/ambiguidade de `kind`, que dependem do turno anterior estar visível, não regridem).
4. `test_trim_history_single_turn_history_length` (`HISTORY_TURNS == 1`, via `monkeypatch` da constante se necessário) — não duplica o único turno.
5. **Reprodução do incidente real**, via `FunctionModel` (mesmo padrão de `_model`/`_turn`/`_action` já usados em `test_bot_turn.py`): script de 5 chamadas de `search_prices` (banana, cebola, tomate, uva, e uma 5ª pergunta livre sobre "o que eu perguntei primeiro"), terminando numa resposta de texto livre — o teste verifica que a *mensagem do turno 1* (o `ToolCallPart`/args de "banana") está presente em `state.history` no momento da 5ª chamada, não que o modelo "acerte" (isso a suíte automatizada não controla, é o modelo de verdade quem decide o que fazer com a informação — o teste garante que a informação **existe** pra ele usar).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde, incluindo os 5 testes acima.
- [ ] Nenhuma mudança em `HISTORY_TURNS`, `SYSTEM_PROMPT` ou `BOT_PROMPT_VERSION`.
- [ ] `_trim_history` é a única função que decide quais turnos sobrevivem — `handle_text` não tem lógica de corte inline.

## Rodada real (recomendado, não bloqueia o ticket)

Reproduzir ao vivo o roteiro banana→cebola→tomate→uva→"o que eu perguntei primeiro?" contra o modelo de verdade, numa **cópia** do banco de produção (nunca o banco real — usar o padrão já estabelecido em `tests/test_real_ai.py::settings`), e confirmar que a resposta cita banana. Neste ambiente há acesso configurado à API (`JULIUS_AI_API_KEY`/`JULIUS_AI_BASE_URL`), então isto pode ser feito pelo próprio agente implementador, não só pelo dono do produto — mas não é critério de aceite automatizado (o modelo pode variar a resposta; o que os testes automatizados garantem é que a informação certa chega até ele).

## Notas para o agente

- Não confundir com `_search_narration_context` (contexto de narração de busca) nem com `_tool_note` (nota de pedido composto) — são três achados diferentes da mesma sessão de monkey test, cada um com sua própria função; não tente unificá-los numa função só.
- `ModelMessage` (import de `pydantic_ai.messages`) já está importado em `turn.py` — não precisa de import novo pra tipar `_trim_history`.
- Não é necessário (nem correto) mexer em `PENDING_TTL_SECONDS`, `ChatState.pending` ou qualquer coisa relacionada a `PendingWrite` — este ticket é só sobre `ChatState.runs`.
