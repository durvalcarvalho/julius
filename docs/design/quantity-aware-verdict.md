# Design: veredito de preço ao vivo pesa quantidade, em reais — não em percentual isolado

> A partir de `docs/requirements/quantity-aware-verdict.md`. Medido contra a cópia do banco de produção real (133 produtos, `services/comparison.py`/`bot/actions.py` como estão hoje) — cada número citado onde usado. Aguardando aprovação antes de qualquer `/sc:implement`, mesmo protocolo dos designs anteriores.

## Achado que decide o design inteiro

**O corte não pode ser percentual — dois casos reais do próprio catálogo têm a mesma faixa de diferença e vereditos opostos.** Medido contra os 17 `kind` com preço em 2+ mercados:

| `kind` | diferença | gap em R$ (mais caro − mais barato) | importa? |
|---|---|---|---|
| `sacola reutilizável` | 10,0% | R$ 0,02 | não, óbvio |
| `sorvete` | 20,0% | R$ 5,00 | pode importar |
| `acém` (exemplo do usuário) | ~14% | R$ 5,00/kg | depende da quantidade |

10% de diferença na sacola é R$0,02 — nunca vale perguntar quantidade, a resposta é sempre "sim, pode levar", **mesmo comprando 20 sacolas**. 14% de diferença no acém é R$5,00/kg — pode ou não valer, dependendo de comprar 1kg ou 14kg. **A mesma faixa percentual (10–20%) produz as duas respostas** porque o que decide não é a fração, é o valor absoluto em jogo. Isso mata a ideia original (herdada do brainstorm) de usar duas faixas percentuais para decidir quando pular a pergunta — RF3 já dizia "o corte é sobre reais, não percentual isolado", e a medição confirma que **nem o gatilho de quando perguntar** pode ser percentual, só o valor final.

**Substitui `LIVE_PRICE_TOLERANCE_PCT` (15%) inteiramente, não empilha em cima dele.** Manter os dois cortes (um percentual pra decidir se pergunta, outro em reais pra decidir o veredito) seria duas fontes de verdade competindo — o próprio achado acima mostra que o percentual não serve nem para a primeira decisão. `diff_pct` continua existindo só como dado informativo na resposta ("14% de diferença"), nunca mais como critério.

## Decisão 1 — o gate por reais: dois pontos de referência, não um por vez

`check_price` (`services/comparison.py:196`) já calcula `reference_value` (o menor preço já registrado, na base certa — `unit_price` ou `price_per_content`, conforme `comparison_basis`). O gap é direto, sem passar por percentual:

```python
gap = price - reference_value   # nunca via diff_pct × reference — evita erro de arredondamento
```

Três constantes novas, isoladas como `LIVE_PRICE_TOLERANCE_PCT` já era — **chute conservador com um único ponto real de referência** (a conversa que abriu esta sessão de brainstorm: R$5–10 de diferença numa compra pequena não compensa, R$70 numa compra de 14kg compensa), não uma distribuição:

```python
WORTH_IT_THRESHOLD_REAIS = 15.0
"""Acima disto (gap em R$ × quantidade), vale trocar de mercado. Só 1 ponto real (a conversa que
abriu docs/requirements/quantity-aware-verdict.md: R$5-10 numa compra pequena "não vale", R$70 numa
compra de 14kg "vale") -- recalibrar com um segundo caso real assim que existir, mesma disciplina de
LIVE_PRICE_TOLERANCE_PCT antes desta rodada."""

PLAUSIBLE_QTY_MIN = 0.2   # menor quantidade plausível de uma compra (kg, L ou unidades -- sem
PLAUSIBLE_QTY_MAX = 20.0  # distinguir por unidade; ver "Limite aceito" abaixo)
```

Com essas três constantes, `check_price` decide **sem perguntar nada**, antes de saber a quantidade:

```python
if gap <= 0:
    verdict = True                                    # já é igual ou mais barato que o histórico
elif gap * PLAUSIBLE_QTY_MAX <= WORTH_IT_THRESHOLD_REAIS:
    verdict = True                                    # nem comprando muito isso vira dinheiro real
elif gap * PLAUSIBLE_QTY_MIN >= WORTH_IT_THRESHOLD_REAIS:
    verdict = False                                   # já é dinheiro real mesmo comprando pouco
else:
    verdict = None                                    # depende — pergunta quantidade
```

Reproduz a tabela acima: `sacola` (gap R$0,02) cai no primeiro `elif` (0,02 × 20 = 0,40, nunca vira R$15) — sempre "sim", nunca pergunta. `acém` (gap R$5,00) não cai em nenhum dos dois extremos (5 × 0,2 = 1,00 abaixo do corte; 5 × 20 = 100 acima) — cai no meio, pergunta quantidade.

Quando a quantidade chega (segunda chamada, ver Decisão 4), a mesma constante decide de novo, agora sem intervalo:

```python
verdict = (gap * quantity) <= WORTH_IT_THRESHOLD_REAIS if gap > 0 else True
```

Confere com o exemplo do usuário: acém, gap R$5,00 (R$40 visto contra R$35 de referência — **não** 14% × 35 = R$4,90, a diferença exata evita o arredondamento do percentual). A 1kg: R$5,00 ≤ R$15 → "não vale". A 14kg: R$70,00 > R$15 → "vale". O ponto de virada fica entre 3–4kg — plausível para "só esse corte" vs. "compra do mês", sem ter sido ajustado à mão para bater esse número.

**Limite aceito, registrado de propósito**: `PLAUSIBLE_QTY_MIN`/`MAX` não distinguem KG de L de UN — 20 é generoso para carne (bate com o "compra do mês" do usuário) mas otimista para óleo de cozinha (20L é implausível numa casa). Isso só empurra mais casos para "pergunta" em vez de "sim" precocemente (direção seguro), nunca o oposto. Recalibrar por unidade quando um caso real mostrar que isso incomoda — mesma disciplina de todo cutoff deste projeto.

**Reversão que precisa ficar registrada, não escondida.** O par de exemplos original que calibrou `LIVE_PRICE_TOLERANCE_PCT` (ovos: R$0,53 → R$0,59, "não importa"; → R$0,75, "bem mais caro", ~42%) **se inverte sob este novo modelo**: gap de R$0,22 × 20 (mesmo comprando muito) = R$4,40, abaixo de R$15 — o novo gate diria "sim, pode levar" para o caso que o usuário original chamou de "bem mais caro". **Isto é intencional, não uma regressão não vista**: RF5 dos requisitos desta rodada diz explicitamente "diferença pequena (poucos centavos) não muda a resposta", e R$0,22 é centavos mesmo comprando uma dúzia inteira de ovos várias vezes. Se o uso real mostrar que isso soa errado para itens de valor baixo comprados em embalagem fixa (ovos, temperos em sachê), o ajuste é um piso por tipo de embalagem, não reabrir o corte percentual — anotado como próximo gatilho de recalibração.

## Decisão 2 — a pergunta não pode apagar os fatos que já tem

`render.py::price_check_facts`/`price_check_fallback_line` hoje tratam **qualquer** `reason` preenchido como "sem dado, frase genérica" (`_PRICE_CHECK_REASON_LINES[reason]`, `price_check_facts` linha 280-281) — um `PriceCheck` com `verdict=None` e `reason="quantity_needed"` perderia `reference_price`/`reference_store`/`reference_at`, e a persona não teria como escrever a frase que o próprio usuário deu como exemplo: *"bem, você já conseguiu comprar por R$35,00; você vai comprar quantos kg?"*.

`"quantity_needed"` entra em `PriceCheckReason` (`domain/models.py`), mas as duas funções de fato precisam de um ramo próprio — não o genérico:

```python
def price_check_facts(check: PriceCheck, *, today: date | None = None) -> str:
    if check.reason is not None and check.reason != "quantity_needed":
        return _PRICE_CHECK_REASON_LINES[check.reason]
    unit_word = _UNIT_PHRASES.get(check.reference_unit or "", "a unidade")
    lines = [
        f"preço informado: {money(check.informed_price)} {unit_word}",
        f"mais barato já registrado: {money(check.reference_price)} {unit_word} "
        f"({weekday_phrase(check.reference_at, today=today)}, {check.reference_store})",
        f"diferença sobre o mais barato: {check.diff_pct:.0f}%",
    ]
    if check.reason == "quantity_needed":
        lines.append(f"pergunte quantos {_CONTENT_WORDS.get(check.reference_unit or '', 'unidades')} a pessoa vai comprar antes do veredito final")
    else:
        lines.insert(0, f"veredito: {'sim' if check.verdict else 'não'}")
    return "\n".join(lines)
```

`price_check_fallback_line` (sem IA) ganha o mesmo ramo, com a frase fixa que **é literalmente** o exemplo do usuário:

```python
if check.reason == "quantity_needed":
    return (
        f"Você viu {money(check.informed_price)} {unit_word}; o mais barato já registrado foi "
        f"{money(check.reference_price)} {unit_word}, em {check.reference_store}, "
        f"{weekday_phrase(check.reference_at, today=today)}. Quantos {word} você vai comprar?"
    )
```

Nenhuma mudança de forma em `PriceCheck` — o campo `reason` já existe, só ganha um valor que os dois renderizadores tratam como "meio caminho", não como "sem dado".

## Decisão 3 — a quantidade tem que estar na mesma base do preço, sempre

`reference_unit` já carrega `"UN"`/`"KG"`/`"L"` (inclusive quando a base é `price_per_content`, ver `check_price` linha 239) — a pergunta **nomeia** essa unidade ("quantos quilos você vai comprar?"), nunca "quanto". Isto não é estético: multiplicar um gap de R$/litro por uma quantidade em garrafas dá um número plausível e errado, exatamente a classe de erro que `ambiguous_unit`/`no_comparable_basis` já existem para evitar em outro lugar deste mesmo fluxo. A ação (`bot/actions.py::check_price`) e o serviço recebem `quantity: float | None`, sempre entendida como "nesta mesma unidade que o `reference_unit` da resposta anterior já disse" — o modelo é quem traduz "vou levar umas 3 garrafas" em litros antes de rechamar a ação, porque ele já viu `reference_unit` nos fatos da chamada anterior (mesma disciplina de extrair `price`/`item` do texto livre que `check_price` já pede hoje).

## Decisão 4 — sem estado novo: o loop de pergunta é disciplina de prompt, reaproveitando `HISTORY_TURNS`

**A decisão mais cara desta rodada, e a que este design rejeita.** A alternativa óbvia — um `PendingQuestion` irmão de `PendingWrite` em `ChatState.pending`, com contagem de tentativas e TTL — foi cogitada e descartada pelo mesmo motivo que already existe registrado em `docs/design/shopping-verdict-shape.md` (RF4/RF5 daquele design) e em `docs/design/shopping-list-conversation-context.md` (Decisão 4): **este projeto mede o que o histórico de 3 turnos já resolve antes de construir estado novo**, e as duas rodadas anteriores que enfrentaram exatamente este tipo de problema (religar "sim" à pergunta anterior, acumular itens em várias mensagens) resolveram só com prompt — sem nunca precisar do estado explícito que ficou "registrado, não implementado" desde a v2.10.

`check_price` (ação, `bot/actions.py`) ganha um parâmetro opcional:

```python
async def check_price(ctx: RunContext[Deps], item: str, price: float, quantity: float | None = None) -> PriceCheck:
    """...
    Args:
        quantity: quanto a pessoa pretende comprar, na mesma unidade que a resposta anterior já
            informou (reference_unit). Só informe quando ela já disse isso, ou quando ela responder
            à pergunta que uma chamada anterior (reason="quantity_needed") devolveu. Se a pessoa não
            responder de forma útil depois de perguntar de novo uma vez, chame de novo com uma
            quantidade pequena (ex.: 1) em vez de insistir -- nunca deixe a conversa travada numa
            pergunta sem resposta.
    """
```

O mecanismo é o mesmo que já resolve "sim" sem contexto hoje: `HISTORY_TURNS = 3` (`bot/turn.py:44`) reenvia os últimos 3 turnos inteiros — inclusive a chamada de ferramenta anterior e o `PriceCheck(reason="quantity_needed", reference_price=..., ...)` que ela devolveu. Quando a pessoa responde "1kg" ou "vou levar uns 14 quilos, é a compra do mês", o modelo já tem, na própria história, o `item`/`price`/`reference_unit` da pergunta que ele mesmo fez — e rechama `check_price` com os três de novo mais `quantity`. Nenhum código novo guarda "o que foi perguntado": é o mesmo dado que já viaja no `message_history` do PydanticAI.

**A tensão com RF5, registrada em vez de escondida.** RF5 dos requisitos diz "a IA... nunca decide sozinha se pergunta ou não". A disciplina de loop acima (perguntar de novo uma vez, depois assumir quantidade pequena) **é** o modelo decidindo quando desistir — um estreitamento deliberado da regra original, do mesmo tipo que a v2.3 já registrou para "categoria conhecida" (`docs/requirements/... — a primeira candidata que já existe no vocabulário`, não a primeira sugestão literal). O que RF5 continua garantindo, sem exceção: **a aritmética** (`gap × quantidade`, a comparação com `WORTH_IT_THRESHOLD_REAIS`) é sempre código, nunca a IA somando ou decidindo o valor do veredito — só a decisão de "já tentei perguntar o suficiente, sigo com um palpite conservador" fica com o modelo, dentro de um limite que o prompt define.

**Gatilho de reabertura, escrito para quando (não se) isto falhar**: se o uso real no Telegram mostrar o modelo perguntando quantidade repetidamente sem parar, ou "esquecendo" a pergunta ao trocar de assunto, esse é exatamente o sinal que as duas rodadas anteriores também esperavam antes de construir `PendingQuestion` — e a essa altura já existem três casos reais (este, RF4/RF5 de v2.10, RF4 de shopping-verdict-shape.md) pedindo o mesmo mecanismo, argumento forte o suficiente para finalmente construí-lo.

## Decisão 5 — a lista de compras ganha economia estimada, não uma pergunta nova (revisão de RF2)

**Isto reduz o que foi decidido no brainstorm** ("os dois fluxos" ganham a pergunta de quantidade) — registrado aqui como decisão de design, com o motivo medido, não como descuido.

Perguntar quantidade por item numa lista de 20 itens não é a mesma conversa que perguntar uma vez num preço só: os 17 `kind` medidos vão de 3,8% a 167% de diferença — uma única quantidade "aplicada a todos" (a ideia original de `total_quantity_kg`) produziria um número sem sentido, porque soma coisas em bases diferentes (kg de carne com unidade de refrigerante) sob uma quantidade que não é real para nenhum dos dois. Perguntar item a item resolveria a base errada, mas trocaria "veredito de lista" (que já existe e funciona desde a v2.10/v2.11) por uma sequência de perguntas — o oposto do que a v2.11 acabou de conquistar (a resposta abre com a decisão).

**O que RF2 realmente precisa — dar à pessoa o número para julgar, sem perguntar nada — já está disponível sem código novo em `services/`.** `KindComparison.entries` já vem ordenado do mais barato ao mais caro (`compare_stores`, docstring: "cheapest first") — a mesma diferença que `comparison_facts` já calcula por grupo (`entries[0].price` vs `entries[-1].price`) só precisa ser somada sobre os `kind` que entraram no veredito vencedor:

```python
def _estimated_savings(shopping: ShoppingComparison) -> float:
    """Soma a diferença mais-barato-menos-mais-caro dos kinds vencedores, assumindo 1 unidade/kg/L
    de cada -- um piso de economia, não uma previsão exata (a pessoa pode comprar mais ou menos de
    cada item). Dado que já existe em KindComparison.entries; nenhum campo novo, nenhum serviço
    tocado."""
    if shopping.verdict is None:
        return 0.0
    won = set(shopping.verdict.won_kinds)
    return sum(
        group.entries[-1].price - group.entries[0].price
        for group in shopping.comparison.comparisons
        if group.kind in won
    )
```

`_verdict_lines`/`shopping_verdict_line` (`bot/render.py`) ganham uma linha quando a soma é maior que zero: *"economia mínima estimada, comprando 1 de cada: R$X"* — mesmo espírito de "mostra o dado, deixa a pessoa decidir" que o resto do projeto já segue (nunca "vá lá, vale muito a pena", só o número). Isso responde à motivação real por trás do pedido original ("várias diferenças pequenas por item podem somar uma economia que compensa a viagem") sem inventar pergunta, estado ou algoritmo novo — puramente formatação sobre dado que `compare_stores` já produz.

**Consequência aceita**: isto não resolve o caso "14kg de um corte só" dentro do fluxo de lista — para esse caso específico, a pessoa continua usando `check_price` (Decisões 1-4), que é exatamente o exemplo original do usuário ("o kg do acém... tá barato?", uma pergunta de item único, não uma lista). Perguntar quantidade dentro de `compare_stores` fica registrado como possível rodada futura, sem caso real medido ainda que justifique o custo.

## O que muda, arquivo por arquivo (especificação, não implementação)

| Arquivo | Mudança |
|---|---|
| `julius/domain/models.py` | `PriceCheckReason` ganha `"quantity_needed"`. `PriceCheck`/`ShoppingVerdict` sem mudança de forma. |
| `julius/services/comparison.py` | `check_price` ganha parâmetro `quantity: float | None`; `LIVE_PRICE_TOLERANCE_PCT` sai, entram `WORTH_IT_THRESHOLD_REAIS`/`PLAUSIBLE_QTY_MIN`/`PLAUSIBLE_QTY_MAX` e o gate de 3 ramos (Decisão 1). |
| `julius/bot/actions.py` | `check_price` (ação) ganha `quantity: float | None = None`, repassa ao serviço; docstring ganha a instrução de loop (Decisão 4). |
| `julius/bot/render.py` | `price_check_facts`/`price_check_fallback_line` ganham o ramo `reason == "quantity_needed"` com fatos completos (Decisão 2). `_verdict_lines`/`shopping_verdict_line` ganham a linha de economia estimada (Decisão 5), via `_estimated_savings` nova, função pura sobre dado já existente. |
| `julius/bot/agent.py` | `SYSTEM_PROMPT`: instrução de quando `check_price` pode voltar pedindo quantidade, como reagir à resposta, e o limite de 1 nova tentativa antes do palpite conservador (Decisão 4) — exemplo de entrada/saída novo, mesma disciplina que fixou comportamento em rodadas anteriores ("só a instrução em prosa não bastou"). `PROMPT_VERSIONS`/`BOT_PROMPT_VERSION` sobem. |
| `julius/services/suggestions.py` | Nenhuma mudança de contrato — `narrate` já recebe `context`/`facts` prontos; o contexto "conferência de preço ao vivo" já existe (v2.11), reaproveitado sem mudança. |

Nenhuma migração de banco. Nenhuma dependência nova. Nenhum campo novo em `ChatState`.

## Precondição de medição — antes de confiar no loop de 2 turnos

**`check_price` nunca foi exercitado em nenhuma rodada `real_ai`** (CLAUDE.md, v2.11: "RF4 não foi exercitado nesta rodada — nenhum caso de `ROUTING_CASES` cobre 'preço visto ao vivo' ainda"). Antes de medir se o loop de pergunta-e-resposta funciona de verdade contra o modelo, o roteamento básico ("os ovos tão a 14 reais, tá bom?" → chama `check_price`, não `search_prices`) precisa de pelo menos um caso em `tests/test_real_ai.py::ROUTING_CASES`. Sem essa base, uma falha do loop de quantidade não seria distinguível de uma falha de roteamento mais simples e anterior.

## O que NÃO está sendo decidido aqui

- **Perguntar quantidade dentro de `compare_stores`** (lista de compras) — substituído por economia estimada (Decisão 5); fica para uma rodada futura se um caso real mostrar que "1 de cada" não é informação suficiente.
- **`PendingQuestion`/estado explícito de pergunta pendente** — deliberadamente não construído (Decisão 4); o gatilho de quando reconsiderar está escrito ali, não é "nunca", é "ainda não".
- **`PLAUSIBLE_QTY_MIN`/`MAX` por tipo de unidade** (KG vs. L vs. UN) — hoje uma faixa só; ajustar quando um caso real (provavelmente óleo/bebida, onde 20 é implausível) mostrar que isso importa.
- **Recalibrar `WORTH_IT_THRESHOLD_REAIS` com mais de um ponto real** — 15 é o melhor palpite com um caso só (a própria conversa desta sessão), não uma distribuição.
- **A redação exata da pergunta de quantidade e do limite de tentativas do prompt** — fica para `/sc:implement`, mesmo padrão de sempre; a Decisão 4 especifica o comportamento, não o texto.
- **Revisitar o exemplo dos ovos (v2.11) manualmente** — a reversão está documentada (Decisão 1); não é necessário "corrigir" o exemplo antigo, só saber que ele mudaria de resposta hoje.

## Próximo passo

`/sc:implement` (ou `/sc:workflow` para tickets), na ordem: Decisão 1+2 juntas (o gate e a preservação dos fatos são a mesma mudança de comportamento em `check_price`, testável com fixtures sintéticas dos casos da tabela acima) — Decisão 3 é uma checagem dentro da mesma mudança, não um passo separado — Decisão 5 pode entrar em paralelo, é isolada em `render.py` — Decisão 4 (prompt) por último, e só faz sentido medir contra `real_ai` depois que a precondição de roteamento básico (seção acima) estiver coberta.
