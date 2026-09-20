# Design: veredito de compra — ordem da resposta, itens que somem em silêncio, e agrupar por mercado

> A partir de `docs/requirements/shopping-verdict-shape.md`. Medições novas feitas durante este design, contra o banco de produção real (não a cópia dos testes) — cada uma citada onde usada. Aguardando aprovação antes de qualquer `/sc:implement`, mesmo protocolo do `telegram-bot.md`/`shopping-list-conversation-context.md`.

## Achado que decide o design inteiro

Não é um bug — são cinco correções de porte bem diferente, e tratá-las como uma coisa só (ou na ordem errada) é o jeito de gastar o orçamento de IA implementando a peça errada primeiro:

| # | O quê | Porte | Já tem o quê pronto |
|---|---|---|---|
| 1 | `match_kind` escolhe o tipo errado por desempate alfabético | correção cirúrgica, 1 função | `_name_score`, catálogo real pra medir contra |
| 2 | Item que casou tipo mas não tem comparação sobe visível na resposta | reaproveita dado que já existe | `StoreComparison.kinds_single_store`/`kinds_total` já contam isso — só não aparecem no veredito de lista |
| 3 | Resposta abre com o veredito, não fecha | só prompt, sem código | nenhum |
| 4 | Checar um preço visto ao vivo, sim/não | ação nova + corte percentual | `comparison_basis`, o padrão de fato-pronto que `narrate()` já usa |
| 5 | Agrupar por categoria, no máximo 2 mercados | novo algoritmo em cima de dado que já existe | `products.tags`, já semeado e já 100% preenchido no catálogo real |

As Decisões 1–3 não têm risco nenhum de regressão (a 1 é medida contra os 98 `kind` reais, a 2 só adiciona uma linha à resposta, a 3 é prompt e só muda a ordem de um contexto específico). As Decisões 4–5 são as que valem a pena revisar com mais calma antes de implementar, porque criam comportamento novo (4) ou trocam um algoritmo (5, não é só reescrever texto — ver `docs/requirements/shopping-verdict-shape.md`, RF6).

## Decisão 1 — `match_kind`: preferir o tipo que bate exato com o termo inteiro, antes de qualquer desempate

**Medido contra o banco de produção**, rodando `match_kind` de verdade: hoje `match_kind(conn, "tomate")` devolve `"passata de tomate"` (devia devolver `"tomate"`) e `match_kind(conn, "maca")` devolve `"macarrão"` (o mais plausível é `"maçã"`). As duas ambiguidades já estavam documentadas em `services/search.py`, docstring de `KIND_MATCH_CUTOFF`, como limitação aceita "sem um caso concreto observado em uso" — os dois screenshots desta rodada são exatamente esse caso.

**A correção testada**: quando dois ou mais `kind` empatam no score mais alto, e um deles é **igual, palavra por palavra normalizada, ao termo inteiro**, esse vence — sem entrar no desempate alfabético de hoje. Simulado contra os 98 `kind` reais e os termos genéricos já documentados no código (`leite`, `pao`, `agua`, `carne`, `arroz`, `queijo`, `creme`, `suco`, `cebola`, `cenoura`, `vinho`, `banana`, `manga`, `uva`, `milho`, `ovo`, `ovos`, `sal`, `mel`, `chá`): **só `tomate` e `maca` mudam de resultado**, os outros 14 continuam idênticos ao que já é documentado como correto. Nenhuma regressão medida.

```
def match_kind(conn, term: str) -> str | None:
    ...
    tied = [kind for kind, score in scored if score == best_score]
    if len(tied) > 1:
        exact = [kind for kind in tied
                 if " ".join(normalize_text(kind).split()) == " ".join(normalize_text(term).split())]
        if exact:
            return exact[0]
    return tied[0]  # empate sem match exato: comportamento de hoje, sem mudança
```

Continua existindo ambiguidade sem solução (`"leite"` entre `leite uht`/`leite condensado`/`creme de leite`, nenhum dos três é o termo inteiro) — não é tocada, porque não tem caso concreto observado ainda e qualquer heurística de desempate secundário (tipo "menos palavras") **muda resultados sem evidência de que fica melhor** (testado: trocaria `creme de leite` por `leite condensado`, nem mais nem menos certo). Fica registrado, não resolvido.

## Decisão 2 — nenhum item pedido some sem explicação (RF1/RF2)

**Corrigido durante este design**: a primeira versão desta decisão apontava para `StoreComparison.kinds_single_store` como o dado pronto — está errado. Aquele campo é calculado sobre `wanted` (`services/comparison.py::compare_stores`, o conjunto de `kind` que **já foi resolvido** por `match_kind`), então ele conta quantos dos *kinds resolvidos* têm um mercado só — inclusive um `kind` errado por ambiguidade (o caso do tomate antes da Decisão 1: `wanted` continha `"passata de tomate"`, não `"tomate"`, e o número batia por coincidência, não porque media a coisa certa). Depois da Decisão 1 corrigir o casamento, esse número muda de novo, porque `tomate` sai do balde de mercado único (tem 3). `kinds_single_store` mede "cobertura do vocabulário de tipos", não "o que sobrou da lista da pessoa" — são coisas parecidas, não a mesma coisa, e a resposta ao usuário precisa da segunda.

**O dado certo já está disponível dentro de `compare_stores` (`bot/actions.py`), só não é capturado.** A função já tem `matched` (lista de `kind` deduplicados que `match_kind` resolveu) *antes* de chamar `comparison_service.compare_stores(conn, kinds=matched)`; depois da chamada, comparar `matched` contra `{group.kind for group in comparison.comparisons}` dá exatamente o balde que falta — sem CNPJ nem cálculo novo, só uma diferença de conjuntos:

```
compared_kinds = {group.kind for group in comparison.comparisons}
single_store_kinds = tuple(kind for kind in matched if kind not in compared_kinds)
```

`ShoppingComparison` ganha dois campos novos (não reaproveita nada de `StoreComparison`):

```
@dataclass(frozen=True)
class ShoppingComparison:
    comparison: StoreComparison
    verdict: ShoppingVerdict | None
    unmatched_terms: tuple[str, ...]        # termo não casou nenhum `kind`
    single_store_kinds: tuple[str, ...]     # NOVO — casou um `kind`, mas ele não tem 2+ mercados
    requested_count: int                    # NOVO — len(terms) originais, antes de casar
```

A frase do veredito (`_verdict_lines`, `bot/render.py`) passa a contar em **tipos**, não fingir uma correspondência 1-para-1 com os termos digitados (dois termos podem casar o mesmo `kind`; um termo pode não casar nenhum) — ex.: *"Da lista, comparei 6 tipos entre mercados; cebola, cenoura e limão saem mais em conta no Costa Atacadao. Tomate só tem preço de um mercado ainda; 8 termos não bati com nenhum tipo cadastrado."* `single_store_kinds` permite, ao contrário da primeira versão desta decisão, **nomear o tipo** que ficou de fora (não só contar quantos) — é estritamente melhor que a ideia original, porque o dado já vem por `kind`, não por contagem agregada.

**Registrar o que a ação realmente comparou, para o próximo incidente não repetir esta investigação.** Nesta sessão, descobrir a causa do tomate exigiu rodar `match_kind` manualmente contra o banco de produção — `ai_calls.jsonl` só grava o texto cru da pessoa (`bot_turn`) e os fatos já resolvidos (`persona`), nunca os `items`/`kind`s que `compare_stores` resolveu no meio do caminho. `bot/actions.py::compare_stores` passa a chamar `ai_log.append(config.query_log_path, {...})` (mesmo arquivo que `_log_query` já usa para busca, não um arquivo novo) com `{ts, channel: "bot", action: "compare_stores", items: terms, matched_kinds: matched, unmatched_terms: unmatched, single_store_kinds}` — puro log, sem custo de IA.

## Decisão 3 — a resposta do veredito de lista abre com a instrução, fecha com o porquê (RF3)

`SYSTEM_PROMPTS["persona"]` é um prompt só para todos os contextos (`context` é hoje só uma frase informativa, não muda a instrução). Ganha uma exceção, condicionada ao valor exato de `context` que `turn.py` já usa (`"veredito de lista de compras"`, linha 196 de `bot/turn.py` hoje) e ao novo contexto da Decisão 4 (`"conferência de preço ao vivo"`):

> "Quando o contexto for veredito de lista de compras ou conferência de preço ao vivo, inverta a estrutura: abra com a instrução — pra onde ir, ou sim/não — e só depois explique com os números. Nos outros contextos, a ordem de sempre continua: informação, comentário, veredito por último."

Não muda `records_facts`/`comparison_facts` nem o exemplo de "histórico de preço de um produto" — o problema medido está só em `compare_stores`, e forçar a mesma inversão numa busca de produto único quebraria um formato que, medido nos exemplos reais de v2.7.1, já funciona ("Acém bovino... R$34,99 o quilo" já É a resposta direta ali, não há veredito escondido no fim). Os dois exemplos de entrada/saída do prompt para "veredito de lista de compras" e o novo "conferência de preço ao vivo" são reescritos nessa ordem — mesma disciplina que já fixou o comportamento nas rodadas anteriores (a nota do próprio prompt: "só a instrução em prosa não bastou" na v2.8).

## Decisão 4 — conferir um preço visto ao vivo, sim ou não (RF4/RF5, escopo novo)

**Reverte, de propósito, um requisito fundador** (ver RNF2 do documento de requisitos) — só nesta forma exata: a pessoa informa um preço que ela está vendo agora, não uma nota importada.

Ação nova (`bot/actions.py`, ao lado de `search_prices`/`compare_stores`, em `READ_ACTIONS`):

```
async def check_price(ctx: RunContext[Deps], item: str, price: float) -> PriceCheck:
    """Confere se um preço que a pessoa está vendo agora no mercado é bom, comparado ao histórico.

    Use SÓ quando a pessoa informar um valor que ela mesma está vendo (ex.: "os ovos tão a 14
    reais, tá bom?", "aqui o quilo do tomate tá 9,90"). NUNCA para "está caro?" sem nenhum preço
    dito — isso continua indo para search_prices, sem veredito.
    """
```

Novo dataclass (`domain/models.py`):

```
@dataclass(frozen=True)
class PriceCheck:
    kind: str | None                       # None = item não reconhecido
    verdict: bool | None                   # True/False = sim/não; None = sem dado pra decidir
    informed_price: float
    reference_price: float | None          # mais barato já registrado, na mesma base
    reference_store: str | None
    reference_at: str | None
    diff_pct: float | None                 # (informado - referência) / referência * 100
    reason: Literal["unknown_item", "no_history", "ambiguous_unit"] | None
```

Nova função pura (`services/comparison.py`, ao lado de `shopping_verdict`):

1. `match_kind(conn, item)` resolve o tipo (já corrigido pela Decisão 1); sem match → `reason="unknown_item"`.
2. Busca todos os `PriceRecord` daquele `kind`, agrupados por `unit` como `compare_stores` já faz. **Se o `kind` tem histórico em mais de um `unit`** (achado real medido nesta sessão: `tomate` tem registros tanto em `KG` — o tomate solto — quanto em `UN` — um combo empacotado, `TOMATE TREBESCHI 250G DUO`) e a pessoa não deu unidade suficiente pra distinguir → `reason="ambiguous_unit"`, sem adivinhar (mesma disciplina de sempre: conteúdo/base nunca é inferido do texto, só perguntado).
3. Sem nenhum registro → `reason="no_history"`.
4. Caso normal: aplica `comparison_basis` no grupo, acha o menor valor já pago (`reference_price`) com sua loja/data, calcula `diff_pct`. `verdict = diff_pct <= LIVE_PRICE_TOLERANCE_PCT`.

**Corte percentual**: os dois exemplos do usuário são os únicos dados que existem — ~11% (tolerável) e ~42% (não é). **Não dá para apertar essa faixa com o caso real da cebola do screenshot 3** (R$7,89 → R$9,99, 26,6%, narrado como "não compra lá"): aquele veredito vem de `shopping_verdict`, uma comparação **entre mercados** — a regra 3 do prompt manda fechar com "compra/não compra" sempre que há 2+ mercados pro mesmo produto, **mesmo numa diferença de 3,8%** (o caso do limão, no mesmo catálogo) — não é um juízo de "26,6% é muito". Os dois mecanismos respondem perguntas diferentes (qual dos mercados que já tenho é mais barato vs. o preço que vejo agora vale a pena), e não é seguro emprestar o limiar de um pro outro. `LIVE_PRICE_TOLERANCE_PCT = 15` é um palpite conservador dentro da faixa 11–42% dada pelo usuário — não uma média nem uma faixa estatística. Constante isolada (mesmo padrão de `KIND_MATCH_CUTOFF`/`MATCH_SCORE_CUTOFF`), documentando no docstring que são só 2 pontos, para recalibrar assim que houver um terceiro caso real.

Fatos/fallback (`bot/render.py`, mesmo par `*_facts`/`*_fallback_line` de sempre):

```
def price_check_facts(check: PriceCheck) -> str: ...       # "sim"/"não" já decidido, diferença já calculada
def price_check_fallback_line(check: PriceCheck) -> str: ...  # sem IA: mesma frase, escrita à mão
```

`reason="ambiguous_unit"` vira uma pergunta de volta ("Tomate eu tenho tanto por quilo quanto por pacote registrado — é por quilo?"), não um veredito — mesmo espírito de `resolve_product` devolvendo candidatos em vez de adivinhar.

## Decisão 5 — agrupar por categoria, no máximo 2 mercados (RF6, troca de algoritmo)

**Medido antes de desenhar**: `products.tags` já cobre **98 de 98 `kind`** do catálogo real com pelo menos uma tag — nenhum precisa de categoria nova. Só **4 de 98** têm tags divergentes entre os produtos de um mesmo `kind` (`ovo`, `pão de queijo`, `queijo mussarela`, `tempero`), e em 2 desses 4 a maioria já é clara (`tempero`: 5 contra 1; `queijo mussarela`: 2 contra 1) — sobra empate real só em `ovo` e `pão de queijo`. Reaproveitar `tags` em vez de inventar uma taxonomia nova é a decisão de menor custo, e os dados confirmam que ela já resolve quase tudo sozinha.

**`ShoppingVerdict` não muda de formato** — continua `winner_stores`/`won_kinds`/`runner_up_store`/`runner_up_kinds` (o teto de 2 mercados já é exatamente essa forma: vencedor + segundo colocado). O que muda é como `shopping_verdict` decide os dois:

```
def shopping_verdict(comparison: StoreComparison, category_of: Mapping[str, str]) -> ShoppingVerdict | None:
```

1. Categoria de cada `kind` = a tag mais comum entre os produtos daquele `kind` (`products.kind_categories(conn) -> dict[str, str]`, nova função em `repositories/products.py`; empate — só 2 casos hoje — decidido por ordem alfabética da tag, mesmo critério que `comparison.py` já usa para empate de segundo colocado).
2. Dentro de cada categoria, tally de vitórias por loja (mesma conta de hoje, só escopada à categoria) → um "vencedor da categoria".
3. Soma quantos `kind` cada loja acumularia sendo vencedora de 1+ categorias. Se **no máximo 2 lojas distintas** resultam disso (o caso comum — confirmado: no `mercados comparar` real de 6 grupos, todos hortifruti, uma categoria só, o resultado é idêntico ao de hoje, Costa Atacadao vencendo 4 de 6), monta o veredito normalmente.
4. Se **mais de 2 lojas** resultam (uma terceira categoria com vencedor próprio), mantém as **duas** com mais `kind` (empate: ordem alfabética do apelido) como vencedor/segundo colocado; qualquer categoria cujo vencedor não é uma dessas duas é **realocada** para quem, entre as duas finalistas, tem o melhor preço *dentro daquela categoria* — nunca para a terceira loja, mesmo que ela fosse tecnicamente mais barata. É uma troca explícita (preço ligeiramente pior numa categoria pequena, por não pedir uma terceira parada) — exatamente o que o usuário descreveu como aceitável ("posso ir a até uns 2 mercados").

**Limite aceito nesta rodada**: o passo 4 não tem caso real observado ainda (o catálogo de hoje não tem uma lista real com 3+ categorias/vencedores distintos) — é especificado para não deixar a resposta quebrada quando aparecer, mas a régua exata de desempate fica sujeita a ajuste no primeiro caso real, mesma disciplina de todo o resto deste projeto.

## O que muda, arquivo por arquivo (especificação, não implementação)

| Arquivo | Mudança |
|---|---|
| `julius/services/search.py` | `match_kind`: desempate por igualdade exata normalizada antes do desempate alfabético (Decisão 1). |
| `julius/services/comparison.py` | `shopping_verdict` ganha parâmetro `category_of: Mapping[str, str]` e o algoritmo por categoria (Decisão 5). Nova função `check_price(conn, kind, price) -> PriceCheck` (Decisão 4). |
| `julius/repositories/products.py` | Nova função `kind_categories(conn) -> dict[str, str]` (tag majoritária por `kind`, Decisão 5). |
| `julius/domain/models.py` | Novo dataclass `PriceCheck` (Decisão 4). `ShoppingComparison` ganha `requested_count: int` (Decisão 2). `ShoppingVerdict`/`StoreComparison` sem mudança de forma. |
| `julius/bot/actions.py` | `compare_stores` passa `category_of=catalog.kind_categories(...)` para `shopping_verdict`, guarda `requested_count`, loga `items`/`matched`/`unmatched`/`single_store` (Decisão 2). Nova ação `check_price` em `READ_ACTIONS` (Decisão 4). |
| `julius/bot/agent.py` | `SYSTEM_PROMPT`: nenhuma regra nova de roteamento além de "preço informado ao vivo → `check_price`, nunca `search_prices`". `BotOutput` ganha `PriceCheck`. |
| `julius/bot/render.py` | `_verdict_lines` cita `kinds_single_store` (Decisão 2). Novo par `price_check_facts`/`price_check_fallback_line` (Decisão 4). |
| `julius/bot/turn.py` | `_render_output` ganha um branch para `PriceCheck`, mesmo formato dos existentes. |
| `julius/services/suggestions.py` | `SYSTEM_PROMPTS["persona"]`: regra de ordem condicionada a `context` (Decisão 3) + exemplo novo para "conferência de preço ao vivo" (Decisão 4). `PROMPT_VERSIONS["persona"]` sobe para `"5"`. |

Nenhuma migração de banco (tudo é leitura de dado que já existe: `products.tags`, `products.kind`, `prices`). Nenhuma dependência nova.

## Custo (RNF1/RNF2)

Decisões 1–3 e 5 têm custo de IA **zero adicional**: mudam o algoritmo em código (guarda de dinheiro intacta, RNF1) ou a ordem de um prompt que já é chamado. A Decisão 4 adiciona uma chamada de `narrate()` por pergunta desse tipo — mesmo formato e mesma faixa de custo (~US$0,0002–0,0007) das chamadas de persona já medidas em v2.7.1/v2.8; nenhuma chamada de IA nova é necessária para decidir o `verdict` em si (isso é conta em código, igual a `shopping_verdict`).

## O que NÃO está sendo decidido aqui

- Nomear, na própria resposta, qual item exato caiu em "casou tipo mas só 1 mercado" (Decisão 2, limite aceito) — fica para se um caso real pedir.
- O desempate exato do passo 4 da Decisão 5 (3+ categorias com vencedores distintos) — especificado, não testado contra caso real.
- O texto exato da pergunta de `reason="ambiguous_unit"` (Decisão 4) e o `HintKind`/frase de "só um mercado tem preço" (Decisão 2) — redação fica para `/sc:implement`, mesmo padrão de sempre.
- Recalibrar `LIVE_PRICE_TOLERANCE_PCT` com mais dados reais de uso — 15% é o melhor palpite com só 2 pontos de referência (11%, 42%), não uma distribuição.
- **A pergunta de `reason="ambiguous_unit"` depende do mesmo mecanismo não verificado que RF4/RF5 do design anterior já apostaram e deixaram sem confirmar** (`docs/como-testar-o-bot.md`, passos 21–23): `check_price` é uma ação de leitura, o run termina, e não existe um `PendingWrite`-like guardando "perguntei a unidade disto". Se a pessoa responder "por quilo" no turno seguinte, é `HISTORY_TURNS = 3` (texto cru) quem precisa religar a resposta à pergunta — não uma ação nova. Isso só se confirma testando com o bot de verdade; se falhar, é o mesmo gatilho já documentado para reabrir "estado explícito de pergunta pendente" (`docs/design/shopping-list-conversation-context.md`, Decisão 4).
- Qualquer coisa do RF6 além do que está aqui (ex.: deixar a pessoa escolher manualmente ir a 3 mercados) — fora de escopo, não pedido.

## Próximo passo

`/sc:implement` (ou `/sc:workflow` para virar tickets), na ordem de risco: Decisão 1 primeiro (correção isolada, já medida, zero efeito colateral) — depois 2 e 3 juntas (mesma área de código, `ShoppingComparison`/`_verdict_lines`/prompt) — Decisão 5 em seguida (precisa da Decisão 1 já no ar, já que agrupar por categoria não conserta um `kind` errado) — Decisão 4 por último, por ser escopo novo e a única que reabre uma regra fundadora do projeto.
