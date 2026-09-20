# Design: escrita só para quem já é confiável, e por que isso não precisa de lista nova

> A partir de `docs/requirements/bot-read-only-tier.md` (`/sc:brainstorm`, 2026-09-20). As duas perguntas que ficaram em aberto lá — onde interceptar, e se a recusa custa uma chamada de IA — foram resolvidas nesta sessão com um experimento real contra o `pydantic-ai==2.45.0` instalado, não só lidas na documentação (mesma disciplina de `docs/design/agent-output-honesty.md`).

## O achado que decide o mecanismo inteiro

A pergunta central era: dá pra deixar o `output_validator` que já existe (`no_unlicensed_data_claims`, a guarda de honestidade da v2.12) trocar o **tipo de saída** de uma ação de escrita (`PendingWrite`) por uma string fixa, sem gastar uma segunda chamada de modelo e sem quebrar o mecanismo de "output function encerra o run"? A assinatura de `OutputValidatorFunc` no `pydantic_ai` instalado é genérica sobre o tipo de saída **do agente inteiro** (`BotOutput`), não sobre o tipo específico que uma chamada de ferramenta produziu — nada no código força o validador a devolver o mesmo tipo que recebeu.

Testado diretamente contra a biblioteca real (script isolado, não parte da suíte — está em `/tmp`, não é um teste do projeto):

```python
@agent.output_validator
def block_writes(ctx: RunContext[Deps], data: BotOutput) -> BotOutput:
    if isinstance(data, dict) and not ctx.deps.can_write:   # dict no lugar de PendingWrite no probe
        return "recusado: sem permissão"
    return data

result = agent.run("renomeia a loja", deps=Deps(can_write=False))
# output type: <class 'str'>
# output value: recusado: sem permissão

result2 = agent.run("renomeia a loja", deps=Deps(can_write=True))
# allowed output type: <class 'dict'>
# allowed output value: {'action': 'rename_store', 'nickname': 'X'}
```

**Uma chamada de modelo em cada caso, nenhum retry.** O modelo escolheu a ferramenta de escrita normalmente (é o roteamento de sempre, sem mudança de prompt); o validador interceptou o **resultado** da ferramenta já executada e devolveu texto no lugar, sem pedir ao modelo pra tentar de novo. Isso resolve as duas questões em aberto da especificação ao mesmo tempo:

- **Onde interceptar (questão 2 do requisito)**: depois de a ação computar o preview (ela só lê o banco pra montar "vai virar X" — nenhum `execute()` roda antes do toque), mas **antes** de `bot/turn.py::_render_output` decidir se mostra o teclado de confirmar. Isso fecha exatamente onde o RF2 pedia, sem precisar tocar em `bot/turn.py`, `bot/actions.py` nem no prompt do agente.
- **Custo da recusa (questão 3)**: zero chamadas extras de IA. A troca de tipo acontece depois que a resposta do modelo já chegou — é o mesmo request que já ia acontecer de qualquer forma, só que o **validador**, não o modelo, decide a última palavra.

## Por que não as duas alternativas cogitadas no requisito

**Dois agentes (um só-leitura, outro completo), escolhidos por `chat_id` em `app.py`.** Rejeitada: o `SYSTEM_PROMPT` de hoje descreve escrita incondicionalmente ("Escrita (renomear, marcar, tipo, conteúdo, fundir, desfundir): ..."), então um agente sem essas ferramentas registradas exigiria um **segundo prompt**, mantido em paralelo e recalibrado a cada mudança do primeiro (o projeto já tem histórico de quanto custa manter um prompt calibrado — três versões de `persona`, duas de `SYSTEM_PROMPT`). Dois `Agent(...)` também dobra o objeto guardado em `bot_data`, com a mesma configuração de modelo repetida duas vezes. Mais peça móvel pelo mesmo resultado.

**`ModelRetry` pedindo ao modelo pra reformular em texto** (o mecanismo que a guarda de honestidade já usa). Rejeitada depois do experimento provar que não é necessária: `ModelRetry` custaria uma chamada HTTP a mais por recusa — exatamente o tipo de gasto que o RNF4 do requisito queria evitar, e que só faria sentido se a troca direta de tipo não funcionasse.

## Mecanismo

Tudo cabe em `julius/bot/agent.py`, mais dois campos novos em `Deps` (`julius/bot/actions.py`) e uma linha em `julius/bot/app.py`. Nada muda em `bot/turn.py`: `_render_output` já despacha por `isinstance` (`PendingWrite` primeiro, `str` por último — "o único caminho onde as palavras do próprio modelo chegam ao usuário"), e uma vez que o validador troca o tipo, a saída cai sozinha nesse último ramo — sem teclado, sem `state.pending` setado, porque nunca chega a ser um `PendingWrite` para quem lê o resultado.

### `Deps` ganha o papel do chat, não a lista que o calcula

```python
@dataclass(frozen=True)
class Deps:
    conn: sqlite3.Connection
    config: Config
    client: LlmClient | None = None
    can_write: bool = True
    chat_id: int | None = None
```

Defaults preservam todo teste existente que constrói `Deps(conn=..., config=...)` sem essas duas colunas — nenhum dos testes de ação/agente hoje precisa saber de permissão, e por padrão continuam testando o caminho "dono". `can_write` é um booleano, não a lista `unlimited_chat_ids` nem uma enum de papéis: a camada de ações não precisa saber *como* a confiança foi decidida (isso é responsabilidade de `app.py`), só *se* pode escrever — a mesma separação de responsabilidade que já existe entre `bot/app.py` (conhece `Update`/Telegram) e as camadas de baixo.

### `app.py` já tem a resposta pronta — `_unlimited`

```python
deps = Deps(
    conn=conn,
    config=settings,
    client=context.bot_data.get("client"),
    can_write=_unlimited(update, settings),
    chat_id=chat.id,
)
```

`chat` não pode ser `None` neste ponto: `_gate` já retornou `True` antes de chegar aqui, e `_gate` retorna `False` cedo quando `update.effective_chat is None`. `_unlimited` é a mesma função que a sessão anterior escreveu pra decidir quem não tem cota de mensagens — reaproveitada aqui exatamente como o requisito decidiu (RF1: mesma lista decide as duas coisas).

`on_tap` **não precisa dessas duas colunas**. Uma consequência que vale registrar porque não era óbvia antes de olhar o código: como o validador intercepta *antes* de `state.pending` ser setado, um chat só-leitura nunca chega a ter uma escrita pendente pra confirmar — não existe um `PendingWrite` de escrita real esperando toque para esse chat. Somado ao nonce já verificado contra `state.pending.nonce` (v2.6), não há caminho, nem por um toque com nonce forjado, para uma pessoa só-leitura executar uma escrita.

### O validador novo, em `bot/agent.py`

```python
import logging

log = logging.getLogger("julius.bot")

@agent.output_validator
def no_write_without_permission(ctx: RunContext[Deps], data: BotOutput) -> BotOutput:
    """Fecha o RF2/RF3 do requisito: quem não é confiável nunca vê o teclado de confirmar --
    a ação de escrita já rodou (só leu o banco para montar o preview, nada foi gravado) e
    esta troca de tipo acontece antes de bot/turn.py decidir se mostra o botão."""
    if isinstance(data, PendingWrite) and not ctx.deps.can_write:
        log.info("chat_id=%s tentou escrever sem permissão: %s", ctx.deps.chat_id, data.action)
        return WRITE_REFUSED_LINE
    return data
```

Registrado depois de `no_unlicensed_data_claims`, mas a ordem não importa na prática: a guarda de honestidade só examina `str` quando **nenhuma** `ToolCallPart` rodou nesta rodada, e uma ação de escrita interceptada aqui sempre teve uma `ToolCallPart` (a ferramenta foi chamada de verdade) — então, seja qual for a ordem de registro, a guarda de honestidade nunca inspeciona `WRITE_REFUSED_LINE` em busca de frases banidas.

### A recusa, na voz do Julius, sem custo de IA — em `bot/render.py`

Mesma família de `search_fallback_line`/`compare_fallback_line`/`price_check_fallback_line`: texto escrito à mão, sem modelo, sempre disponível. Diferente delas, não varia por dado nenhum (nenhum registro, nenhuma comparação) — não precisa ser função:

```python
WRITE_REFUSED_LINE = (
    "Essa parte eu não abro pra qualquer um — por aqui você só consulta. Se quiser mexer em nome "
    "de mercado, categoria ou fusão de produto, peça pra quem te chamou te colocar na lista de "
    "confiança."
)
```

(Texto de exemplo; a redação final é liberdade do `/sc:implement`, contanto que não use nenhuma das frases de `_UNLICENSED_DATA_CLAIMS` — o que este exemplo já respeita.)

## O que NÃO muda

- **`bot/actions.py`**: nenhuma das 15 funções de ação é tocada. `READ_ACTIONS`/`WRITE_ACTIONS` já existem e já são exatamente a categorização que este design precisa — nasceram antes deste requisito, por outro motivo, e encaixam sem alteração.
- **`bot/turn.py`**: `_render_output` já despacha por tipo; a saída trocada cai no ramo que já existe para texto livre do modelo.
- **`SYSTEM_PROMPT`**: nenhuma menção a papel/permissão precisa entrar no prompt. O modelo continua vendo as 15 ferramentas e escolhendo livremente — só não controla mais se o resultado chega ao usuário como convite pra confirmar.
- **`on_tap`**: sem mudança (ver acima — a situação que ele trataria nunca acontece).
- **Custo de IA**: nenhuma chamada nova, nenhum `retries` a mais consumido.

## Testes a escrever (`/sc:implement`)

Mesma disciplina de `tests/test_bot_agent.py` (que já usa `FunctionModel` roteando pra uma ação real do catálogo de teste):

1. `Deps(can_write=False)` + modelo roteando pra qualquer uma das 10 `WRITE_ACTIONS` → `agent.run(...).output` é `str`, igual a `WRITE_REFUSED_LINE`, nunca `PendingWrite`.
2. Mesmo cenário com `Deps(can_write=True)` (ou o default) → comportamento idêntico ao de hoje, `PendingWrite` chega intacto.
3. `Deps(can_write=False)` + modelo roteando pra qualquer uma das 5 `READ_ACTIONS` → resultado passa direto, sem interferência do validador novo.
4. A recusa é logada: capturar o log e checar `chat_id` + nome da ação (`data.action`) na linha.
5. Nível `bot/turn.py::handle_text`: com a saída trocada, `Reply.pending` é `None` e o texto da resposta é a recusa — teste de integração fino que fecha o RF2 na camada que a pessoa efetivamente recebe (o teclado nunca é montado porque `state.pending` nunca é setado).
6. Regressão: nenhum teste existente de `test_bot_agent.py`/`test_bot_turn.py` que já constrói `Deps(conn=..., config=...)` sem os dois campos novos deveria quebrar — os defaults (`can_write=True`, `chat_id=None`) preservam o comportamento anterior por construção.
7. `test_bot_app.py`: `on_text` passa `can_write=_unlimited(...)` e `chat_id=chat.id` ao construir `Deps` — um teste de integração leve (com `FunctionModel`) cobrindo que um `chat_id` fora de `unlimited_chat_ids` recebe a recusa de ponta a ponta, via `Update` fake.

## Questões que seguem em aberto (fora do escopo desta especificação)

As mesmas do requisito — nenhuma nova surgiu aqui:

- Papel e cota continuam sendo a mesma lista (`unlimited_chat_ids`) por decisão explícita; separar as duas checagens só se justifica quando um caso real pedir (`Deps.can_write` já é um campo próprio, então separar no futuro é trocar quem o calcula em `app.py`, não mexer em `agent.py`/`actions.py` de novo).
- A rede de preços compartilhada continua fora de escopo, registrada em `docs/requirements/bot-read-only-tier.md`.

## Próximo passo

`/sc:implement` a partir daqui: os dois campos em `Deps`, a linha em `app.py`, o validador e a constante em `render.py`, mais os testes listados acima. Nada foi implementado nesta sessão de design.
