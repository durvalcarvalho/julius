# Design: veredito por lista de compras, e o mínimo de memória de conversa que isso exige

> A partir de `docs/requirements/shopping-list-conversation-context.md`, informado por `claudedocs/research_conversation_context_management_20260919.md` e `claudedocs/research_conversation_design_telegram_deepseek_20260919.md`. Aguardando aprovação antes de qualquer `/sc:implement` — mesmo protocolo do `telegram-bot.md`/`bot-message-chunking.md`.

## Achado que decide o design inteiro

`compare_stores` (`bot/actions.py:136`) chama `comparison_service.compare_stores(conn)` **sem nenhum filtro** — a função (`services/comparison.py:18`) sempre itera todo `products.list_products` com `kind` definido, hoje 16 grupos. Não existe, em lugar nenhum do sistema, o conceito de "os itens que a pessoa quer comprar agora"; existe só "todo tipo de coisa que ela já comprou alguma vez". O textão do screenshot original não é bug de formatação — é a pergunta errada sendo respondida.

Isso muda o centro de gravidade do design: a correção principal é **dar escopo à comparação** (RF1–RF3), o que não depende de nenhuma memória de conversa nova. As duas pesquisas confirmam separadamente que RF4/RF5 (responder "sim", acumular itens em várias mensagens) já têm equivalente barato no que existe (`state.history`, `HISTORY_TURNS = 3`) e que RF6 (lembrar além da janela) não tem nenhuma evidência medida de necessidade real ainda — só um screenshot isolado. Por isso o design abaixo tem três pesos diferentes: **implementar agora** (Decisões 1–3), **reforço de prompt, custo zero de código** (Decisão 4), e **especificado mas não implementado, condicionado a medição** (Decisão 5).

## Decisão 1 — `compare_stores` passa a exigir itens; sem itens, o bot pergunta, nunca compara tudo

`comparison_service.compare_stores(conn, kinds=None)` ganha um parâmetro opcional `kinds: Sequence[str] | None`. Quando informado, filtra `typed` (linha 22) para os produtos cujo `kind` está em `kinds`, antes de agrupar — o resto da função (agrupamento, base de comparação, ordenação por preço) não muda uma linha. `kinds=None` continua sendo exatamente o comportamento de hoje: é o que `julius mercados comparar` (CLI) chama, e **não muda**.

A action do bot (`compare_stores`) passa a exigir `items: tuple[str, ...]` (mínimo 1, `ModelRetry` se vazio — mesmo padrão de `_required`/`search_prices`). Cada termo é casado contra `products.all_kinds(conn)` (repositório já existente) com o **mesmo mecanismo que `search.py::detect_tag` já usa** para casar uma palavra digitada contra um vocabulário curado (`rapidfuzz`, corte próprio a medir — `detect_tag` usa `TAG_MATCH_CUTOFF = 75`, calibrado contra as 13 tags semeadas; o vocabulário de `kind` é outro conjunto, então o corte não é reaproveitado sem checar, só o *mecanismo*). Termos sem casamento entram numa lista `unmatched` separada — nunca somem em silêncio (mesma disciplina do projeto: "sem grupo comparável, mensagem explícita").

**O prompt (`SYSTEM_PROMPT`, `bot/agent.py`) ganha a regra que fecha RF1**: "qual mercado é mais barato"/"onde eu devo ir" sem nenhum item citado (nem nesta mensagem, nem nas recentes da conversa) **não chama `compare_stores`** — responde em texto perguntando o que a pessoa quer comprar. A action nunca recebe a chance de rodar sobre o catálogo inteiro a partir do bot; `kinds=None` fica reservado para a CLI.

## Decisão 2 — veredito agregado é conta feita em código, a IA só veste a fala

Fecha RF2/RF3, na mesma disciplina da guarda de dinheiro (RNF1: nenhum `R$`/contagem que a IA não recebeu pronta). `KindComparison.entries` já vem **ordenado do mais barato pro mais caro** (`services/comparison.py:53`) — o vencedor de cada grupo já é `entries[0]`, dado que já existe, não precisa recalcular nada nem chamar IA para comparar dois números.

Nova função pura, em `services/comparison.py` (mesma camada de `compare_stores`/`new_extremes`, sem tocar em `domain/` porque nada aqui é reaproveitado por dois serviços):

```
def shopping_verdict(comparison: StoreComparison) -> ShoppingVerdict | None:
    """Conta vitórias por loja (entries[0] de cada grupo) e monta o veredito.
    None quando não há nenhum grupo comparável (comparison.comparisons vazio)."""
```

Novo dataclass (`domain/models.py`, ao lado de `StoreComparison`):

```
@dataclass(frozen=True)
class ShoppingVerdict:
    total_items: int
    winner_stores: tuple[str, ...]   # mais de um só em empate — ver Decisão 3
    won_kinds: tuple[str, ...]       # nomes dos grupos que o(s) vencedor(es) levaram
    runner_up_store: str | None      # loja mais barata entre os itens QUE SOBRARAM; None se não sobrou nenhum
    runner_up_kinds: tuple[str, ...]
```

`ShoppingVerdict` não substitui `StoreComparison` — é derivado dele, na mesma chamada. O `BotOutput` do bot ganha um novo tipo (`bot/actions.py`, ao lado de `ProductListing`/`StoreListing`):

```
@dataclass(frozen=True)
class ShoppingComparison:
    comparison: StoreComparison
    verdict: ShoppingVerdict | None
    unmatched_terms: tuple[str, ...]   # itens que não bateram com nenhum `kind` conhecido
```

`StoreComparison`/`KindComparison` continuam existindo sem mudança de contrato — só ganham um consumidor novo. Nenhuma migração de banco: tudo isto é leitura e cálculo sobre dado que já existe.

## Decisão 3 — empate entre lojas: nomear as duas, nunca escolher uma arbitrariamente

Caso não perguntado no brainstorm, decisão de design proposta aqui (a confirmar): quando duas ou mais lojas empatam no número de vitórias e nenhuma tem maioria, `winner_stores` traz **as duas**, e o texto (via persona) nomeia ambas em vez de escolher uma por critério arbitrário (alfabético, por exemplo) — mesmo espírito de `resolve_product`/`resolve_store` listando candidatos em vez de adivinhar. Vencedor por **pluralidade** (mais vitórias que qualquer outra loja, mesmo sem maioria absoluta) já é uma recomendação honesta e não precisa de empate para existir — "3 de 9 mais barato no mercado X" é uma frase válida mesmo se as outras 6 se espalham entre duas outras lojas.

## Decisão 4 — RF4/RF5 (pergunta pendente, acumular itens): reforço de prompt primeiro, sem peça nova

As duas pesquisas convergem: `state.history`/`HISTORY_TURNS = 3` já reenvia as últimas 3 trocas completas ao modelo a cada turno — a pergunta do próprio bot ("o que você quer comprar?") já está no texto que a IA recebe no turno seguinte. O caso "sim" do screenshot provavelmente não prova que a memória falha; prova que "sim" é uma resposta genuinamente ambígua para uma pergunta aberta, não um sintoma de janela curta.

**Mudança de custo zero em código**: duas frases novas no `SYSTEM_PROMPT` —
1. "Se a sua última mensagem nesta conversa foi uma pergunta, trate a próxima mensagem da pessoa como resposta a ela antes de considerar qualquer outra ação — mesmo que a resposta seja curta."
2. "Ao montar a lista de itens para `compare_stores`, junte o que a pessoa mencionou nas últimas mensagens da conversa, não só na mais recente."

Isso fecha RF4/RF5 **se a medição confirmar** — é exatamente o tipo de coisa que só se sabe testando com o bot de verdade (mesma disciplina de `docs/como-testar-o-bot.md`). Não há código novo para medir primeiro.

**Alavanca seguinte, especificada e não implementada, só se a medição do parágrafo acima mostrar que reforçar o prompt não basta**: um campo `awaiting_topic: str | None` em `ChatState` (`bot/turn.py`), preenchido quando o output de um turno é texto livre terminando em pergunta, consultado (e limpo) no início do turno seguinte para anotar explicitamente ao modelo "você tinha perguntado: `<texto>`" — mesma forma que `state.pending`/`PendingWrite` já usa para escrita, só que sem botão de confirmação. Nenhuma tabela nova: `ChatState` já é por-chat, em memória de processo, mesmo ciclo de vida de hoje.

## Decisão 5 — RF6 (lembrar além da janela): fora desta rodada, condicionado a medição real

As duas pesquisas são explícitas: nenhuma evidência real ainda de que 3 turnos não bastam (o único caso observado, "sim", é ambiguidade de pergunta aberta, não perda de contexto por janela curta), e a DeepSeek mudou o cálculo de custo desde a última vez que o projeto mediu isso — `deepseek-flash` tem hoje **1M tokens de janela** e **cache de disco por prefixo idêntico**, com desconto de uma ordem de grandeza no acerto de cache (`api-docs.deepseek.com/news/news0802`). Como `state.history` já é um prefixo estável e crescente (mesmo formato reenviado, só anexando o novo turno no fim), aumentar `HISTORY_TURNS` pode custar muito menos do que a suposição de "custo linear" sugere — mas isso **precisa ser medido contra `ai_calls.jsonl`** antes de mexer no número, mesma disciplina de toda constante deste projeto.

**Não implementar nesta rodada.** Se, depois de usar o bot de verdade com as Decisões 1–4 no ar, ainda sobrar um caso real de "esqueceu algo de mais de 3 turnos atrás", os dois próximos degraus, em ordem de custo:
1. Aumentar `HISTORY_TURNS` e medir tokens de entrada/custo real (barato de testar, `ai_calls.jsonl` já loga tudo).
2. Se não bastar: uma tabela pequena de fatos por chat (`chat_id`, 2-3 campos nomeados tipo "lista corrente"/"pergunta pendente" — não um resumo em prosa, que sofre de *summarization drift* documentado, nem busca vetorial, desproporcional para um catálogo pequeno e um usuário só), populada por uma *tool call* explícita do modelo — o mesmo mecanismo de *output functions* que `ALL_ACTIONS` já usa, aplicado a estado de conversa em vez de execução de comando. Vale checar antes se `pydantic_ai.StepPersistence(backend='sqlite')` (achado da pesquisa, presente na versão de `pydantic_ai` já usada — a confirmar) já cobre isso sem escrever repositório novo.

Nenhum dos dois é parte desta implementação — ficam documentados para não perder o raciocínio, não para construir agora.

## O que muda, arquivo por arquivo (especificação, não implementação)

| Arquivo | Mudança |
|---|---|
| `julius/services/comparison.py` | `compare_stores` ganha parâmetro opcional `kinds: Sequence[str] \| None = None`, filtra `typed` quando informado. Nova função `shopping_verdict(comparison) -> ShoppingVerdict \| None`. |
| `julius/domain/models.py` | Novo dataclass `ShoppingVerdict`. `StoreComparison`/`KindComparison` sem mudança. |
| `julius/repositories/products.py` | Sem mudança — `all_kinds` já existe e já serve. |
| `julius/bot/actions.py` | `compare_stores(ctx, items: tuple[str, ...])`: casa cada termo contra `all_kinds` (mecanismo de `detect_tag`), levanta `ModelRetry` se `items` vier vazio, monta `ShoppingComparison` (novo dataclass, ao lado de `ProductListing`/`StoreListing`) com `unmatched_terms`. |
| `julius/bot/agent.py` | `SYSTEM_PROMPT`: regra de RF1 (não comparar sem itens, perguntar em texto), regra de RF4 (resposta curta responde à pergunta anterior), regra de RF5 (somar itens das mensagens recentes). `BotOutput` ganha `ShoppingComparison`. |
| `julius/bot/render.py` | Novo par `shopping_comparison_facts`/`shopping_verdict_line`, mesmo padrão de `comparison_facts`/`compare_fallback_line` — fatos incluem a contagem N/M e os nomes de loja já calculados, nunca deixando a IA somar. `unmatched_terms`, quando não vazio, vira uma linha de fato própria ("não achei preço de X ainda"). |
| `julius/bot/turn.py` | `_render_output` ganha um branch para `ShoppingComparison`, mesmo formato dos existentes (`_narrate` com fallback pra `shopping_verdict_line` sem IA). **Não** ganha `awaiting_topic` nesta rodada (Decisão 4, alavanca seguinte). |

Nenhuma migração de banco. Nenhuma dependência nova.

## Custo (RNF2) — melhora, não piora

A chamada de comparação hoje falha exatamente por ser grande demais: o incidente medido (`ai_calls.jsonl`, 2026-09-19T17:42:52) mostra a narração de 16 grupos truncando duas vezes (`finish_reason: length`, 500 tokens cada tentativa) antes de cair no fallback cru. Comparar só os itens pedidos é estritamente mais barato: menos grupos, fatos mais curtos, sem risco de estourar `max_tokens` do jeito que o incidente mostrou. Nenhuma medição nova é necessária para saber que isto reduz custo — é subconjunto do que já rodava.

## O que NÃO está sendo decidido aqui

- Qualquer coisa envolvendo `awaiting_topic`/estado de conversa persistido (Decisão 4, alavanca seguinte) ou tabela de fatos (Decisão 5) — ficam especificadas, não implementadas, condicionadas a medição real de uso.
- Mudar `HISTORY_TURNS` — fica em 3 nesta rodada.
- `ConversationHandler`/`BasePersistence` do `python-telegram-bot` — a pesquisa aponta tensão real com o desenho "a IA roteia" já decidido (v2.6); não entram em consideração enquanto esse desenho valer.
- O corte fuzzy exato para casar item↔`kind` (equivalente ao `TAG_MATCH_CUTOFF`) — a medir em `/sc:implement` contra o vocabulário real de `kind`, mesma disciplina de todo cutoff deste projeto.

## Próximo passo

`/sc:implement` (ou `/sc:workflow` para virar tickets) para as Decisões 1–3 (escopo da comparação + veredito agregado) e a Decisão 4 (as duas frases de prompt, sem código novo) — medindo o corte de casamento item↔kind e testando os casos RF4/RF5 com o bot de verdade antes de considerar a Decisão 4 fechada ou a Decisão 5 necessária.
