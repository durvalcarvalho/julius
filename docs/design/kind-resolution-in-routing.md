# Design: resolver item/tipo na chamada de roteamento, sem lista de exceção nem estado novo

> A partir de `docs/requirements/kind-resolution-in-routing.md` (`/sc:brainstorm`, 2026-09-21). O requisito pedia vocabulário de `kind` embutido no prompt de roteamento e, para ambiguidade, reabrir o estado de pergunta pendente que v2.10/v2.11/v2.13 adiaram três vezes. Lendo `bot/actions.py` de perto antes de desenhar, esse segundo ponto muda: o mecanismo que a ambiguidade precisa **já existe e já funciona**, sem estado novo nenhum.

## Achado que decide metade deste design

`resolve_product`/`resolve_store` (`bot/actions.py`, linhas 80–136) já resolvem exatamente este problema — nome ambíguo, múltiplos candidatos — sem nenhum estado novo em `ChatState`:

```python
if len(ids) > 1:
    found = [(product.id, product.canonical_name) for product in catalog.list_products(conn) if product.id in ids]
    raise ModelRetry(
        f"Mais de um produto combina com «{reference}»: {_candidate_list(sorted(found))}. "
        "Pergunte ao usuário qual, e chame de novo com o id."
    )
```

`ModelRetry` devolve o erro **para o modelo**, dentro da mesma chamada (`retries=2` já configurado em `build_agent`) — o modelo lê a lista de candidatos e, seguindo a instrução do próprio `SYSTEM_PROMPT` ("se a ação responder que há ambiguidade... PERGUNTE à pessoa, em texto"), termina o turno com uma pergunta em texto livre. A resposta da pessoa chega como uma mensagem nova, comum, e `HISTORY_TURNS = 3` (já existente) garante que o modelo ainda vê sua própria pergunta ao decidir a próxima ação. **Nenhuma `PendingWrite`, nenhum nonce, nenhum TTL.**

Isto não é uma leitura nova do sistema — é o mesmo mecanismo que `check_price`'s `reason="quantity_needed"` já usa (documentado em `docs/design/quantity-aware-verdict.md`, v2.13: "o loop de pergunta-resposta é inteiramente disciplina de prompt... o modelo vê sua própria pergunta anterior no `HISTORY_TURNS=3`"). A diferença é que aquele caminho ainda não tinha sido exercitado contra o modelo de verdade em produção (a v2.13 registrou isso como pendência); `resolve_product` já foi, há mais tempo, para escrita.

**Correção ao requisito RNF4**: isto não "reabre a pendência de estado explícito" — reusa um mecanismo já existente e mais maduro (`resolve_product`) para um terceiro caso (`kind`), sem construir nada novo. O gatilho que já foi documentado três vezes para construir o estado explícito continua exatamente onde estava: se o uso real no Telegram mostrar o modelo perdendo o fio (esquecendo a própria pergunta, ou insistindo sem parar), isso vale tanto para esta rodada quanto para as duas que já usam o padrão — não é uma decisão nova deste design.

## Achado que decide a outra metade: `match_kind` não tem consumidor fora do bot

```
$ grep -rn "match_kind" julius/ | grep -v services/search.py
julius/bot/actions.py:180
julius/bot/actions.py:231
```

Só dois call sites, os dois em `bot/actions.py` (`compare_stores`, `check_price`). A CLI (`julius mercados comparar`) nunca resolve item por texto — compara o catálogo inteiro ou uma lista já resolvida por `kind` explícito via `julius produtos tipo`. Isto simplifica o requisito RNF5 (CLI): não há caminho de CLI para regredir, porque a CLI nunca chamou `match_kind`. O contrato de `match_kind(conn, term) -> str | None` fica livre para ganhar uma função-irmã sem quebrar compatibilidade nenhuma fora do bot.

## Decisão 1 — vocabulário de `kind` entra por um system prompt dinâmico, não pelo docstring da ação

**Por que não no docstring de `check_price`/`compare_stores`:** PydanticAI monta o schema de cada ação (a partir do type hint + docstring) uma vez, quando `build_agent()` roda — que é uma vez por processo do `julius-bot`, não uma vez por mensagem. Um docstring estático não pode carregar um vocabulário que muda toda vez que `julius importar`/`produtos revisar` roda (processo separado, mesmo banco). `Agent.system_prompt` aceita uma função decorada que recebe `RunContext[Deps]`.

**`dynamic=True` é obrigatório, não o default — verificado, não suposto.** `Agent.system_prompt` aceita um parâmetro `dynamic: bool = False`; com o default, a função só roda na **primeira** chamada de `agent.run()` de uma conversa, e o texto que ela devolveu fica congelado dentro do primeiro `ModelRequest` do histórico. `bot/turn.py::handle_text` sempre reaproveita histórico (`message_history=state.history`), então com `dynamic=False` o vocabulário nunca atualizaria depois da primeira mensagem do chat — um `julius importar` rodando no outro processo nunca apareceria pro bot enquanto a conversa continuasse. Confirmado com `FunctionModel` (mesma ferramenta que os testes deste bot já usam), contando quantas vezes a função roda e o que cada chamada de `agent.run()` recebeu de volta ao reaproveitar `message_history`:

| | `dynamic=False` (default) | `dynamic=True` |
|---|---|---|
| função rodou (3 `run()`, histórico reaproveitado) | **1 vez** | 3 vezes |
| prompt visto no run 2 | `VOCAB-1` (congelado do run 1) | `VOCAB-2` (atual) |
| prompt visto no run 3 | `VOCAB-1` (ainda) | `VOCAB-3` (atual) |

```python
# julius/services/search.py
def known_kinds(conn: sqlite3.Connection) -> list[str]:
    """The kind vocabulary, for callers outside `repositories` reach -- same shape as
    `known_tags`."""
    return products.all_kinds(conn)

# julius/bot/agent.py
from julius.services import search as search_service

@agent.system_prompt(dynamic=True)
def kind_vocabulary(ctx: RunContext[Deps]) -> str:
    kinds = search_service.known_kinds(ctx.deps.conn)
    if not kinds:
        return ""
    return (
        "Tipos (kind) já cadastrados, para os argumentos de check_price/compare_stores: "
        + ", ".join(kinds)
        + ". Quando o pedido corresponder a um destes, use exatamente esta grafia; senão, use o "
        "texto da pessoa mesmo assim -- outra camada resolve marca e erro de digitação depois."
    )
```

**Custo medido, não estimado** (mesma disciplina de todo cutoff deste projeto): 98 `kind`s hoje = 1.178 caracteres ≈ 294 tokens, contra os 2.728 tokens de entrada já medidos no incidente que abriu esta frente — **~11% de aumento**. Isto é comparável ao custo que o bot já paga em todo turno: as 14 ações e seus docstrings já vão inteiros em toda mensagem, escolhida ou não — este vocabulário só estende esse mesmo modelo de custo (paga-se tudo, sempre), não introduz um padrão novo.

**Por que só `kind` e nunca `canonical_name`/marca:** `kind` é vocabulário curado que cresce devagar (produto novo de tipo já existente reaproveita o `kind` — 98 `kind`s para 133 produtos hoje, proporção que só tende a cair). `canonical_name` cresce SKU a SKU, sem teto. Colocar produto no prompt violaria a RNF1 do requisito (payload proporcional ao catálogo, não ao número de tipos) — e é desnecessário, porque a resolução de marca já está resolvida do lado do código (Decisão 2).

## Decisão 2 — `match_kind`/`_match_kind_via_product` não mudam de lógica, só recebem entrada melhor

O patch já em produção (`KIND_NOISE_WORDS`, `_match_kind_via_product`, override de borda no `KIND_MATCH_CUTOFF`) continua exatamente como está. RF2 do requisito ("o valor do modelo é validado contra o vocabulário") não precisa de uma checagem nova: `match_kind` **já** processa qualquer string que chega, do jeito de sempre — se o modelo mandar `"refrigerante"` (porque viu no prompt), o caminho de match exato (score 100) resolve; se mandar algo fora do vocabulário (uma marca nova, um erro do modelo), cai no mesmo fallback por produto de sempre. A IA nunca é uma fonte de verdade não verificada — ela só melhora a taxa de acerto do primeiro passo do matcher determinístico, que continua sendo quem decide.

## Decisão 3 — ambiguidade de marca (não a de vocabulário já aceita) vira `ModelRetry`

**Escopo, para não reabrir uma decisão antiga por acidente:** a ambiguidade que ganha pergunta aqui é só a que a Decisão 2 do patch (`_match_kind_via_product`) já detecta e hoje descarta em silêncio — dois ou mais produtos de nomes reais discordando de `kind` (o caso `"pepsi"` ≈ `"Cream cheese President"`, coberto por `test_match_kind_ambiguous_brand_fallback_stays_unresolved`). **Isto não mexe no empate já aceito do match direto contra o vocabulário** (`"leite"` → `"creme de leite"`, documentado e decidido em v2.10/`KIND_MATCH_CUTOFF`: "não é um bug a perseguir sem evidência de caso real errado"). Um implementador futuro não deve estender esta pergunta para cobrir aquele caso sem uma medição nova e uma decisão própria — são ambiguidades de natureza diferente (uma é o vocabulário genuinamente ambíguo; a outra é o *fallback* encontrando produtos concretos que discordam).

```python
# julius/services/search.py
def _kinds_via_product(conn: sqlite3.Connection, term_words: Sequence[str]) -> frozenset[str]:
    term = " ".join(term_words)
    if not term:
        return frozenset()
    ids = matching_product_ids(conn, term)
    return frozenset(
        product.kind for product in products.list_products(conn) if product.id in ids and product.kind is not None
    )


def _match_kind_via_product(conn: sqlite3.Connection, term_words: Sequence[str]) -> str | None:
    found = _kinds_via_product(conn, term_words)
    return next(iter(found)) if len(found) == 1 else None


def kind_candidates(conn: sqlite3.Connection, term: str) -> tuple[str, ...]:
    """O que `match_kind` sabe mas descarta quando devolve `None` por ambiguidade de marca (2+
    produtos reais discordando de kind) -- a mesma informação que `resolve_product` já expõe para
    o modelo perguntar em vez de adivinhar. Vazio sempre que `match_kind` já resolveu, ou quando a
    recusa não tem candidato nenhum para oferecer (não confundir com o empate já aceito do match
    direto contra o vocabulário -- ver KIND_MATCH_CUTOFF)."""
    term_words = _strip_kind_noise(normalize_text(term).split())
    found = _kinds_via_product(conn, term_words)
    return tuple(sorted(found)) if len(found) > 1 else ()
```

```python
# julius/bot/actions.py
def _resolve_kind(conn: sqlite3.Connection, item: str) -> str | None:
    """Como resolve_product, mas para `kind`: devolve o tipo resolvido, ou None (item
    desconhecido, comportamento de hoje), ou levanta ModelRetry quando há candidatos concretos
    discordando (marca ambígua) -- nunca escolhe por conta própria."""
    kind = search_service.match_kind(conn, item)
    if kind is not None:
        return kind
    candidates = search_service.kind_candidates(conn, item)
    if candidates:
        raise ModelRetry(
            f"Mais de um tipo combina com «{item}»: {', '.join(candidates)}. "
            "Pergunte à pessoa qual, e chame de novo com o tipo escolhido."
        )
    return None
```

`check_price` e `compare_stores` trocam a chamada direta a `search_service.match_kind(...)` por `_resolve_kind(...)`; o resto de cada função (o que fazer com `kind is None`) não muda uma linha.

**`compare_stores` é tudo-ou-nada na ambiguidade, por decisão explícita, não por efeito colateral.** Hoje o loop sobre `terms` é tolerante — um item não reconhecido vira `unmatched`, os outros seguem comparando. Com `_resolve_kind` dentro do mesmo loop, o primeiro item ambíguo levanta `ModelRetry` e aborta a chamada **inteira**: os itens já resolvidos antes dele neste turno se perdem, e o modelo tem que rechamar `compare_stores` com a lista inteira de novo, substituindo o termo ambíguo pela resposta da pessoa. Mesmo precedente de `resolve_product`, que também aborta em vez de resolver parcialmente. Alternativa (acumular ambíguos e perguntar todos de uma vez ao final do loop) foi descartada por não ter precedente nem caso real — pode ser revisitada se o uso mostrar isso incomodando com listas longas.

**O orçamento de `retries=2` (`build_agent`) é compartilhado com a guarda de honestidade (`no_unlicensed_data_claims`), não um orçamento novo.** Se o modelo, depois do `ModelRetry` de ambiguidade, tentar de novo com o **mesmo** termo ambíguo em vez de perguntar à pessoa, gasta o 2º `retry`; esgotado, a exceção sobe como `UnexpectedModelBehavior` e `bot/turn.py` já trata isso (mensagem `COULD_NOT_CONFIRM`, não `AI_UNREACHABLE` — ver `docs/design/agent-output-honesty.md`, Decisão 2). Nenhum código novo aqui, mas o caminho de exaustão precisa de teste próprio (ver seção de testes), do mesmo jeito que `agent-output-honesty.md` já testa a exaustão da sua própria guarda.

**`SYSTEM_PROMPT` ganha uma frase**, no bloco "Leitura" (não no de "Escrita", que já cobre `resolve_product`/`resolve_store`):

> Se `check_price`/`compare_stores` recusar por ambiguidade de tipo, PERGUNTE à pessoa qual das opções listadas, do mesmo jeito que já faz para produto/mercado ambíguo — nunca escolha sozinho.

## Contrato final (assinaturas)

| módulo | símbolo | mudança |
|---|---|---|
| `services/search.py` | `known_kinds(conn) -> list[str]` | novo, espelha `known_tags` |
| `services/search.py` | `kind_candidates(conn, term) -> tuple[str, ...]` | novo |
| `services/search.py` | `_kinds_via_product(conn, term_words) -> frozenset[str]` | novo, privado, extraído de `_match_kind_via_product` |
| `services/search.py` | `_match_kind_via_product` | corpo reescrito para usar `_kinds_via_product`; comportamento externo idêntico |
| `services/search.py` | `match_kind` | **sem mudança de código** |
| `bot/agent.py` | `kind_vocabulary(ctx) -> str` (`@agent.system_prompt`) | novo |
| `bot/agent.py` | `SYSTEM_PROMPT` | +1 frase no bloco "Leitura" |
| `bot/actions.py` | `_resolve_kind(conn, item) -> str \| None` | novo, mesmo formato de `resolve_product`/`resolve_store` |
| `bot/actions.py` | `check_price`, `compare_stores` | trocam `match_kind(...)` por `_resolve_kind(...)` |

Nada muda em `ChatState`, `PendingWrite`, `bot/turn.py` ou `bot/app.py`.

## Testes que a implementação precisa cobrir

- `known_kinds` devolve o mesmo que `products.all_kinds`.
- `kind_candidates` devolve `()` para os casos já cobertos (match direto resolve, ou `_match_kind_via_product` resolve único) — sem falso positivo nos testes que já existem (`coca`, `guarana`, `refrigerante de 2 litros`).
- `kind_candidates` devolve as duas marcas na fixture já escrita (`test_match_kind_ambiguous_brand_fallback_stays_unresolved` ganha uma segunda asserção, ou uma prima: `kind_candidates(conn, "pepsi") == ("refrigerante", "salgadinho")`).
- `bot/actions.py::check_price`/`compare_stores`: chamando com um item que produz candidatos, o teste espera `pytest.raises(ModelRetry)` com as duas opções na mensagem — mesmo padrão que os testes de `resolve_product` ambíguo já usam.
- **Regressão explícita**: o empate já aceito do match direto (`"leite"` → `"creme de leite"`) não levanta `ModelRetry` — continua resolvendo em silêncio, confirmando o limite da Decisão 3.
- `kind_vocabulary(ctx)` devolve string vazia com catálogo vazio (sem `kind` nenhum), e a lista correta com `kind`s cadastrados — teste de unidade direto na função, sem precisar de `agent.run()`.
- **`dynamic=True` propagado de verdade**: teste com `FunctionModel` (mesmo experimento que validou a Decisão 1) chamando `agent.run()` duas vezes com `message_history` reaproveitado e um `kind` novo cadastrado entre as duas chamadas — o segundo `run` precisa ver o `kind` novo no system prompt. Sem este teste, um `dynamic=True` removido por engano num refactor futuro volta a congelar o vocabulário sem que nenhum outro teste perceba (a suíte de roteamento de hoje usa `FunctionModel` de resposta única, nunca reaproveita histórico entre duas chamadas reais).
- **`compare_stores` tudo-ou-nada**: um item ambíguo no meio da lista aborta a chamada inteira (`ModelRetry`), mesmo com itens anteriores já resolvidos — nenhum resultado parcial é devolvido neste turno.
- **Exaustão do `ModelRetry` de ambiguidade**: um `FunctionModel` que insiste no mesmo termo ambíguo nas duas tentativas permitidas por `retries=2` deve terminar em `UnexpectedModelBehavior`, capturado por `bot/turn.py` como `COULD_NOT_CONFIRM` — nunca a lista de candidatos vazando pro usuário como texto cru, nem confundido com `AI_UNREACHABLE`. Mesmo padrão de teste que `docs/design/agent-output-honesty.md` já tem para a exaustão da guarda de honestidade.
- Suíte `real_ai` (`tests/test_real_ai.py`, `make test-ia`): **o caso novo tem que testar o que a Decisão 1 realmente resolve.** "Devo comprar uma coca por 12 reais?" já resolve certo hoje, só com o patch determinístico (`_match_kind_via_product`) — sem o vocabulário no prompt. Não serve como prova da Decisão 1, porque passaria mesmo revertendo-a. O caso que mede a Decisão 1 é de variação de **categoria**, não de marca: um termo cuja grafia exata só existe registrada no `kind` (ex. pessoa diz "biscoito", o `kind` cadastrado é "biscoito recheado") — a Decisão 1 é o que aumenta a chance do modelo já devolver "biscoito recheado" por ter visto a grafia certa no prompt, em vez de depender só do fuzzy match. Se der para montar um catálogo de teste com ambiguidade real de marca, um segundo caso cobre a Decisão 3 (texto de pergunta em vez de ação). Toda rodada anterior deste bot (v2.7 a v2.13) fechou com uma "rodada real" medida contra o modelo de verdade antes de considerar o design pronto — esta não é exceção.

## Fora de escopo desta rodada (registrado, não decidido aqui)

- **Reabrir o empate já aceito do match direto de `kind`** (`"leite"` → `"creme de leite"`, v2.10) — decisão separada, precisa de caso real medido antes de mexer, mesma disciplina de sempre.
- **Vocabulário de produto/marca no prompt** — permanece fora por RNF1; a resolução de marca continua 100% código (`_match_kind_via_product`).
- **`consultar`/`search_prices`** — este design cobre só os dois consumidores de `match_kind` (RF5 do requisito). `consultar` já tem seu próprio fallback de IA (`match_products`, pós-resultado-vazio); unificar os dois mecanismos é a questão em aberto 5 do requisito, não decidida aqui.
- **Estado explícito de pergunta pendente** — não construído. O gatilho para construí-lo (uso real mostrando o modelo perder o fio) continua o mesmo já documentado três vezes; esta rodada não o antecipa nem o descarta.
- **Reavaliar o formato "vocabulário inteiro no prompt" se `all_kinds()` crescer uma ordem de grandeza** (RNF1) — não implementado agora (98 `kind`s não justificam), só o gatilho fica escrito.

## Próximo passo

`/sc:implement`, com o roteiro de testes acima. Fechar com uma rodada real (`make test-ia`) medindo: (a) os casos do incidente original resolvendo certo através do prompt mais o patch já em produção, (b) o caso de ambiguidade de marca virando pergunta em vez de recusa, e (c) o tamanho real do prompt de roteamento depois da mudança — mesma exigência de medição contra o modelo de verdade que fechou cada rodada anterior deste bot.

## Rodada real (implementado, 2026-09-21, `make test-ia` contra cópia do banco de produção)

**1158 testes verdes na suíte padrão** (`.venv/bin/pytest -q`; 11 pulados são só a suíte `real_ai`, que cresceu de 9 para 11 com os dois casos novos). `test_kind_candidates_stays_empty_for_the_pre_existing_accepted_tie` pegou um bug real antes de qualquer chamada de IA: `kind_candidates("leite")` devolvia as duas marcas de "leite condensado"/"creme de leite" porque a função nunca checava se `match_kind` já tinha resolvido por outro caminho — corrigido fazendo `kind_candidates` chamar `match_kind` primeiro, tornando o limite de escopo da Decisão 3 verdadeiro por construção, não só por convenção no único chamador que hoje o respeita.

**`dynamic=True` confirmado como bloqueante antes de qualquer chamada real** (achado do `advisor`, não suposição): reproduzido com `FunctionModel` que a função do vocabulário só roda 1 de 3 vezes com o default (`dynamic=False`), reaproveitando histórico — e travando o vocabulário na primeira mensagem do chat. Um segundo achado no caminho: a mesma função, síncrona, é despachada pro thread pool do `anyio` pelo `pydantic_ai`, e `sqlite3.Connection` recusa ser tocada fora da própria thread — o mesmo defeito que `narrate()` já teve em v2.7, agora num ponto novo. As duas correções (`dynamic=True` e `async def`) estão testadas: `test_kind_vocabulary_stays_current_across_turns_sharing_history` prova a primeira, a suíte inteira rodando sem `ProgrammingError` prova a segunda.

**9 testes, 19 chamadas, US$ 0,0264, roteamento 7/7 (100%)** — sem degradação com o prompt ~13% maior (medido: 1.427 caracteres de vocabulário, 98 `kind`s, contra os 2.728 tokens de entrada do incidente original). Os dois casos que fecham o incidente, com o modelo de verdade:

- *"Devo comprar uma coca por 12 reais?"* → `PriceCheck`, resposta real: *"Você viu R$ 12,00 o litro; o mais barato já registrado foi R$ 3,33 o litro, em Costa Atacadao ADE Aguas Claras, sábado passada. Quantos litros você vai comprar?"* — nunca mais "não tá no catálogo".
- *"a pepsi tá 8 reais o litro, tá bom?"* → texto livre, resposta real: *"Achei mais de um tipo que combina com "pepsi": **cream cheese** e **refrigerante**. Qual dos dois é?"* — a ambiguidade de marca (medida ao vivo contra o catálogo de produção antes de escrever o teste, não fabricada) virou pergunta, nunca um veredito adivinhado.

**Achado de revisão (`advisor`) corrigido antes de fechar, não observado em produção ainda**: o override de borda (score exatamente em `KIND_MATCH_CUTOFF`) e a ambiguidade de marca podiam colidir sem que ninguém percebesse — se o fallback por produto encontrasse 2+ kinds discordando NESSA banda exata, `match_kind` devolvia a coincidência direta (ex. "cacau em pó") em vez de `None`, e `kind_candidates` nunca chegava a ser consultado (`_resolve_kind` só chama quando `match_kind` já se recusou). Reproduzido com uma fixture sintética de 3 produtos antes de decidir se era alcançável: era. Corrigido fazendo o override distinguir "fallback unânime" (1 kind — continua substituindo a coincidência) de "fallback ambíguo" (2+ kinds — devolve `None`, cede a vez pra `kind_candidates`). Não muda nenhum resultado medido contra o catálogo de produção (confirmado de novo depois da correção: `coca`/`pepsi`/`guarana`/`leite` idênticos) — o caso só existe na fixture sintética que o provou, `test_match_kind_borderline_coincidence_yields_to_real_brand_ambiguity`.

**O que esta rodada não cobre**: o segundo turno do loop de ambiguidade (pessoa responde "refrigerante", o modelo rechama `check_price` com o tipo escolhido) — nenhum caso de `ROUTING_CASES`/teste dedicado ainda simula a resposta à pergunta, só a pergunta em si. Mesma lacuna que o loop de `quantity_needed` já tinha antes desta rodada (v2.13): confirma que o mecanismo pergunta certo, não que a conversa de duas mensagens fecha sozinha — isso é o próximo gatilho de medição se o uso real no Telegram não fechar o loop sozinho.
