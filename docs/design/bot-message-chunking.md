# Design: várias mensagens curtas (bot), a partir de `docs/requirements/bot-message-chunking.md`

> Aguardando aprovação do usuário antes de qualquer `/sc:implement` — mesmo protocolo do `telegram-bot.md`.

## Achado que decide o design inteiro

O prompt `persona` (v3, `services/suggestions.py::SYSTEM_PROMPTS["persona"]`) **já** devolve a resposta em blocos separados por linha em branco — informação, comentário, veredito — desde a v2.7. O exemplo real do próprio arquivo:

```
"Compra no Costa Atacadao. R$ 7,89 o quilo.\n\nNo Dona de Casa tava R$ 9,99 — R$ 2,10 a mais, sem motivo nenhum, cebola é cebola.\n\nNão compra lá."
```

Três pensamentos distintos, já separados por `\n\n` pelo próprio modelo. O bug não é o modelo escrever demais — é `bot/app.py::_send` (linha 107) mandar essa string inteira como **uma** chamada a `message.reply_text()`. O Telegram trata `\n\n` como quebra de parágrafo dentro da mesma bolha, não como mensagens novas.

Isso muda o centro de gravidade do design: a correção de raiz (ponytail: causa raiz, não sintoma — ver CLAUDE.md "Convenções de código") mora na **camada de envio**, um lugar só, não espalhada pelos quatro branches de `_render_output`. Toda resposta que já é narrada pela IA — busca, comparação, listagem, confirmação de escrita — ganha a divisão em mensagens de graça, sem tocar em `render.py` nem em `suggestions.py` para isso.

## Decisão 1 — divisor genérico na camada de envio

`bot/app.py` ganha uma função que substitui a chamada direta a `message.reply_text` dentro de `_send`:

```python
def _chunks(text: str) -> list[str]:
    """Um pensamento por bolha: o próprio '\n\n' que a persona já produz é o separador."""
    return [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]

async def _send(update, text, keyboard=None) -> None:
    parts = _chunks(text)
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        await _send_one(update, part, keyboard if is_last else None)
```

`_send_one` é o corpo atual de `_send` (o `try`/`except BadRequest` que recua para texto sem HTML) — cada bolha recua para texto puro **independente** das outras, então uma bolha com HTML exótico não derruba as demais. O teclado de confirmação (`_keyboard`) só vai na última bolha, porque é ela que carrega a pergunta.

**Isso sozinho já fecha, sem mexer em mais nada**: resposta de produto único (info + comentário + veredito), confirmação de escrita (comentário + preview/resultado) e o comentário de listagem (`remark\n\nbase`) — tudo isso já é gerado com `\n\n` hoje. Vira 2–3 bolhas automaticamente. Fecha a questão em aberto nº4 do documento de requisitos ("resposta de item único também fatia?") sem precisar de nenhum caso especial.

## Decisão 2 — a tabela crua deixa de ser o caminho padrão para "muitos itens"

Hoje, `bot/turn.py::_render_output` decide por contagem (`NARRATE_FULL_MAX_RECORDS`/`GROUPS`, ambos 6): até o corte, a narração **substitui** a tabela (Modo A); acima, um comentário curto é colado **em cima** da tabela crua inteira (Modo B) — é exatamente o textão do screenshot original.

Nova regra: a narração é sempre tentada, para qualquer contagem (dentro do teto de sanidade da Decisão 3). Se `narrate()` devolveu algo, a resposta é **só** os blocos dela — nunca mais colada com a tabela. A tabela crua (`render_records`/`render_comparison`, sem mudança nenhuma nelas) só aparece quando não há remark **nenhum** — sem cliente configurado, orçamento estourado, ou a chamada falhando. Fecha a questão em aberto nº3: a tabela não desaparece do código (renderizá-la bonita continua fora de escopo, por decisão sua no brainstorm), só vira fallback de caso raro, igual já é hoje para 0 registros ou IA não configurada.

**Um limite existente não pode ser reaproveitado aqui, e por quê.** `search_fallback_line` (o fallback sem IA para poucos registros) assume que todos os registros são do **mesmo produto** — a frase final cita `records[0].canonical_name`. Isso já é impreciso hoje para uma busca por tag que junta produtos diferentes dentro do corte de 6, mas nunca foi um problema prático porque o caso comum de poucos registros é buscar um produto específico. Estender esse fallback para conjuntos maiores e multi-produto (o caso das "carnes") pioraria esse defeito, não corrigiria — por isso o fallback sem IA para contagem grande continua sendo a tabela crua, não uma frase única. (Achado adjacente, fora de escopo: vale um ticket próprio para `search_fallback_line` checar se todos os registros são do mesmo `canonical_name` antes de citar um nome só — não é deste design.)

## Decisão 3 — a persona agrupa, o Python não inventa um algoritmo de agrupamento novo

Fecha a questão em aberto nº1 (critério de "agrupamento inteligente"). A alternativa considerada — escrever uma função Python que decide grupos por `products.kind`, por lote de tamanho fixo, ou por extremos — foi descartada: `kind` já é praticamente um-por-produto no caso das carnes (não reduz o número de bolhas), lote de tamanho fixo corta no meio de um raciocínio sem critério nenhum, e a própria persona **já demonstrou**, sem ser instruída para isso, a habilidade de agrupar por resultado compartilhado — o exemplo real da v2.7.1: *"Compra no Assai Atacadista... pra banana, cebola, tomate e vinho. Compra no Assai Atacadista... pra uva."* — um veredito só para quatro produtos com o mesmo resultado. É a mesma tarefa, só que aplicada de propósito ao invés de emergir por acaso.

Mudança de prompt (persona v4, rascunho — a redação final e os números abaixo são para medir em `/sc:implement`, mesma disciplina de todo cutoff deste projeto):

- O prompt ganha uma frase nova dizendo que os fatos podem trazer **vários produtos diferentes de uma vez** (hoje ele só foi calibrado/exemplificado com "um produto" e "um grupo de comparação"), e uma instrução de orçamento de blocos: poucos produtos (a maioria dos casos reais, medido em v2.7: 96% das buscas ficam ≤6 registros) continuam um bloco de informação + comentário por item, como hoje; quando os fatos trazem muitos produtos, o Julius **agrupa por resultado igual** (mesmo mercado mais barato, mesma faixa de preço) em vez de repetir a estrutura por item, e o teto de blocos na resposta fica pequeno (proposta inicial: até 4–5 blocos, a medir).
- A guarda de dinheiro (nenhum `R$ X,XX` fora dos fatos) não muda uma linha — continua valendo bloco a bloco, inclusive dentro de um bloco que agrupa vários produtos.
- `records_facts`/`comparison_facts` não mudam de formato — continuam uma linha por registro/grupo; é só o prompt que aprende a comprimir isso na saída quando a entrada é grande.

## Decisão 4 — teto de sanidade antes de gastar a chamada

`NARRATE_FULL_MAX_RECORDS`/`NARRATE_FULL_MAX_GROUPS` (hoje 6/6) deixam de ser o corte "narra tudo vs. cola tabela" (isso vira comportamento sempre-narra, Decisão 2) e passam a ser só **o ponto em que o prompt passa a pedir agrupamento** em vez de um bloco por item (Decisão 3). Mas precisa continuar existindo um teto **duro**, acima do qual nem se tenta narrar — um `consultar` com `limit=50` ou um `produtos listar` de catálogo grande não pode virar um prompt de centenas de linhas por acidente (custo e truncamento — o `max_tokens=260` já truncou uma vez com só 6 grupos, ticket 172). Acima desse teto duro: direto para a tabela crua, sem gastar a chamada de IA. Valor proposto para medir: o próprio `limit` já existente nos serviços de busca (hoje 20) provavelmente já é um teto seguro — confirmar contra o catálogo real antes de fixar em código, não chutar.

## Decisão 5 — sem atraso artificial entre as bolhas

`_show_typing` continua chamado **uma vez por turno**, antes da chamada de IA (onde já está hoje) — não uma vez por bolha. Adicionar "digitando..." entre mensagens que chegam em sequência rápida pareceria um bot reagindo a cada linha que a pessoa já está lendo, não uma pessoa mandando uma sequência de mensagens (o padrão real de chat é mandar tudo e a outra pessoa ler no próprio ritmo). Fica para o roteiro de teste manual real (`docs/como-testar-o-bot.md`) confirmar se isso incomoda — mesma disciplina da v2.7.1, que também deixou o "digitando..." para validação no Telegram de verdade.

## Decisão 6 — escopo

A Decisão 1 (divisor de envio) é genérica e pega **toda** resposta do bot de graça — busca, comparação, listagem, confirmação de escrita, preview de pendência. As Decisões 2–4 (retirar a tabela do caminho padrão, ensinar a persona a agrupar, teto de sanidade) só têm efeito prático em `SearchOutcome` e `StoreComparison` dentro de `_render_output` — são os dois únicos branches que hoje têm um corte Modo A/Modo B. `ProductListing`/`StoreListing` e o fluxo de escrita já sempre narram (sem corte por contagem) — não precisam de mudança própria, só herdam a Decisão 1.

## O que muda, arquivo por arquivo (especificação, não implementação)

| Arquivo | Mudança |
|---|---|
| `julius/bot/app.py` | `_send` passa a fatiar `text` em `\n{2,}` e mandar uma `reply_text` por pedaço; teclado só no último pedaço; o recuo para texto sem HTML (`BadRequest`) continua por pedaço. |
| `julius/bot/turn.py` | `_render_output` para `SearchOutcome`/`StoreComparison`: remove o `if len(records) <= NARRATE_FULL_MAX_RECORDS` como decisor de "colar com a tabela"; a tabela só entra quando `remark` é `None`. Constantes `NARRATE_FULL_MAX_RECORDS`/`GROUPS` renomeiam de sentido (viram o gatilho de "peça agrupamento" para o prompt) e ganham um teto duro novo acima do qual `_narrate` nem é chamado. |
| `julius/services/suggestions.py` | `SYSTEM_PROMPTS["persona"]` ganha a instrução de orçamento de blocos e um exemplo de entrada/saída com **múltiplos produtos** (hoje só tem exemplo de um produto/um grupo) — `PROMPT_VERSIONS["persona"]` sobe pra `"4"`. |
| `julius/bot/render.py` | Sem mudança de contrato. `render_records`/`render_comparison` continuam existindo, exatamente como estão, só chamadas com menos frequência. |

Nenhuma migração de banco, nenhuma dependência nova.

## Medido de verdade (rodada real, 19/09/2026, contra cópia do banco de produção)

O que a seção anterior deixou em aberto foi medido nesta mesma sessão, antes de fechar a implementação — mesma disciplina de toda constante deste projeto.

**Primeira tentativa falhou, e o motivo é o achado real.** Com o prompt v4 só dizendo "agrupe por resultado igual, até uns 4-5 blocos" e `max_tokens=500` (herdado da v3), a tag `hortifruti` (29 registros reais, produtos sem nenhum resultado compartilhado — cada um com preço e loja diferentes) truncou: `finish_reason: length`, resposta vazia, exatamente a assinatura de truncamento já conhecida do ticket 172. O modelo tentava listar cada produto agrupado por LOJA, e cada bloco virava uma frase gigante enumerando 6-14 produtos — tecnicamente poucos blocos, mas cada um era o textão original disfarçado.

**Causa raiz: "agrupar por resultado igual" só funciona quando existe um resultado compartilhado de verdade.** Uma comparação entre mercados (`comparison_facts`) quase sempre tem isso (um mercado ganha na maioria dos grupos). Uma busca ampla por categoria (`records_facts` de uma tag como "hortifruti" ou "carnes") não tem — são produtos diferentes, sem "vencedor" em comum. O prompt precisava de uma segunda regra para esse caso, não só uma.

**Correção**: o prompt v4 final distingue duas situações (texto em `SYSTEM_PROMPTS["persona"]`, `julius/services/suggestions.py`) — (1) produtos com resultado em comum → agrupa e cita os nomes; (2) produtos sem padrão → cita só o mais barato e o mais caro do conjunto, com preço e loja, e diz quantos outros ficaram de fora, sem listar nome de cada um. Um segundo exemplo de entrada/saída no prompt (o caso "sem resultado em comum") foi o que fixou o comportamento — só a instrução em prosa não bastou nas rodadas anteriores.

**Resultado depois da correção, no catálogo real:**

| Cenário real | Registros/grupos | Blocos | Tokens de saída | Custo |
|---|---|---|---|---|
| busca "hortifruti" (sem padrão) | 29 registros | 3 | 147 | US$ 0,0010 |
| busca "carnes" (sem padrão, é o caso do screenshot original) | 8 registros | 3 | ~100 | US$ 0,0008 |
| `compare_stores` real inteiro (com padrão: Costa Atacadao ganha 4 de 6) | 6 grupos | 3 | ~120 | US$ 0,0007 |

O caso "carnes" (o mesmo do screenshot que abriu esta rodada) agora responde:

> Filé de peito de frango Seara, bandeja de 1kg, R$ 15,99 a unidade no Costa Atacadao, quarta-feira. É o mais barato da lista.
>
> Do outro lado, JERK TRAS FRIB 500G a R$ 34,50 a unidade no Assai Atacadista, sexta-feira passada. R$ 24,00 de diferença entre os dois — sabe quanto tempo de luz isso paga?
>
> Os outros seis ficam no meio, sem nada que grite mais alto que isso.

Três mensagens curtas no Telegram, em vez do parágrafo único + duas tabelas do screenshot original.

**Números fechados** (`julius/bot/turn.py`, `julius/services/suggestions.py`):
- `FALLBACK_LINE_MAX_RECORDS`/`FALLBACK_LINE_MAX_GROUPS = 6` — mantido o valor original (era `NARRATE_FULL_MAX_RECORDS`/`GROUPS`), agora só decidindo o fallback sem IA.
- `NARRATE_MAX_RECORDS = 40` / `NARRATE_MAX_GROUPS = 20` — teto de sanidade antes de sequer chamar a IA; **ainda é placeholder**, nenhum caso real do catálogo chega perto (o maior visto foi 29).
- `max_tokens=900` em `narrate()` (subiu de 500) — headroom puro: nenhuma resposta medida passou de 150 tokens de saída depois da correção do prompt, mas 900 protege contra um caso ainda pior não visto, sem custo extra (cobra por token realmente gerado, não pelo teto).
- `PROMPT_VERSIONS["persona"] = "4"`.

Rodada completa de regressão com IA de verdade (`pytest tests/test_real_ai.py --real-ai`, inclui um teste novo, `test_narration_of_many_dissimilar_products_stays_short`, que fixa este achado): **8 testes, 14 chamadas, US$ 0,01205**. Roteamento 5/5.

## O que NÃO está sendo decidido aqui (fora de escopo, por pedido explícito no brainstorm)

- Renderizar a tabela como imagem.
- Cortar o comentário do Julius a ponto de virar resposta só-fato.
- Corrigir o defeito adjacente de `search_fallback_line` assumir um produto só (achado nesta sessão, não pedido).

## Próximo passo

Este documento propõe **onde** a divisão acontece (camada de envio, genérica) e **como** o agrupamento é resolvido (o prompt, não um algoritmo Python novo) — as duas perguntas que ficaram em aberto no requisito. Aprovando, `/sc:workflow` ou `/sc:implement` traduz isto em tickets (padrão do projeto: um commit por ticket, teste de caminho feliz e triste, rodada real contra cópia do banco de produção antes de fechar os números da seção anterior).
