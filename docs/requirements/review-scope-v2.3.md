# Julius — escopo e atrito da revisão assistida: requisitos

> Brainstorm de 2026-09-16 (`/sc:brainstorm`), disparado pelo primeiro `julius produtos revisar` real depois da v2.2, no banco de produção. Duas observações do usuário: (1) "vários itens não têm conteúdo definido, mesmo tendo a quantidade no nome — por que não pegamos essa informação?"; (2) "nessa sequência de tags tudo é sempre a primeira opção, então por que não fazer isso automático?".
> Insumos: `~/.local/share/julius/prices.db` e `~/.local/share/julius/ai_calls.jsonl` reais, lidos nesta sessão; respostas do usuário às perguntas do brainstorm.
> **Segunda rodada de brainstorm, mesmo dia** (§6–§8): o usuário perguntou se o sistema teria como saber, por intuição de varejo brasileiro, que "brócolis é quase sempre bandeja, prato de plástico é pacote com N, espátula é uma unidade" — ou se isso foge demais. Resposta medida: não foge, desde que a intuição nunca grave sozinha. Emenda o RF2.
> Próximo passo: `/sc:design` → tickets (131+).

## 0. Ponto de partida — fatos medidos

Todos os números vêm do banco de produção e do log de IA, não de estimativa.

| # | Fato | Evidência |
|---|---|---|
| F1 | **Não há falha de extração de conteúdo.** Comparando a resposta crua da última chamada `enrich` com o banco, item a item: das 25 propostas, **19 traziam conteúdo e as 19 estão gravadas**. Zero perdas. | `ai_calls.jsonl` (última linha `call_kind=enrich`, `prompt_version=2`, `error=None`) × `products.content_quantity`. |
| F2 | Os 6 `null` daquela resposta estão **corretos**: Brócolis Ninja, Bacon Excelência tablete, Queijo tipo parmesão pedaço, Queijo brie pedaço, Linguiça de Frango (vendidos por peso) e Filme PVC Wyda 30m × 28cm (dimensão, não conteúdo — o caso `PRATO 21CM` que o `CLAUDE.md` já registra). | Mesma resposta crua. |
| F3 | **O que enganou foi a tabela.** A coluna "Conteúdo" da tela de revisão mostra `proposal.content` (a proposta), não o estado do produto. Em branco significa ao mesmo tempo "já está gravado, nada a propor" e "a IA não soube". Das 25 linhas, **9 em branco já tinham conteúdo no banco** e só 6 eram `null` de verdade. | `cli/_review.py::_table`; contagem cruzada com o banco. |
| F4 | A coluna "Cupom" tem o mesmo defeito: mostra `product.canonical_name`, que depois do primeiro `renomear` já **não é** o que o cupom dizia. Na tela real, "Cupom" e "Nome" saíram idênticos em todas as 25 linhas. | `cli/_review.py::_table`; saída real. |
| F5 | **O ponto cego é o critério de pendência.** `curation.pending_product_ids` = `products.untagged_product_ids`. Hoje: **4 produtos** pendentes por esse critério, e **49 produtos com tag e sem conteúdo** — invisíveis para o `revisar`, permanentemente. | `services/curation.py:19`; query em `products`/`product_tags`. |
| F6 | Desses 49, **26 são vendidos por KG** e não precisam de conteúdo: R$/kg **já é** o preço por conteúdo (ramo 1 da regra de base da v2.2). Os outros **23 são vendidos por UN**, e desses **16 têm quantidade inequívoca no nome**: Mel 450g, Vinho 750ml, Óleo de gergelim 100ml, Azeitona 350g, Sabão 900ml, Camarão 300g, Merluza 500g, as duas uvas em bandeja de 500g, entre outros. | Join `products` × `prices.unit`; `domain/comparison_basis.py`. |
| F7 | Esses 16 são **dívida da v2**: ganharam tag numa rodada em que conteúdo era apenas *impresso* como sugestão (`julius produtos definir-conteudo ID QTD UN`) e nunca aplicado. Ao ganhar a tag saíram da fila de pendentes e não têm como voltar. A v2.2 reverteu a confirmação, mas a reversão só alcança produto **novo**. | `CLAUDE.md`, "Camada opcional de IA" (registro da reversão); F5. |
| F8 | Entre os 7 produtos-UN sem conteúdo **e** sem número no nome, um é erro real da IA: **`108 Ovos Iana 30 unidades médio branco`** está sem conteúdo. É exatamente o caso que motivou a funcionalidade de preço por conteúdo ("20 ovos por R$12 vs 30 por R$16,50"). Numa rodada de teste paralela, com o nome cru `OVOS IANA 30UN MEDIO BCO`, a mesma IA respondeu `30 UN` corretamente. | Banco real × banco de teste `/tmp/julius-real`. |
| F9 | **O modelo hedge por padrão.** Na última chamada devolveu **2 categorias para 24 dos 25 produtos** e 1 categoria para um único produto. A primeira categoria já pertencia ao vocabulário conhecido em **25 de 25**. | Resposta crua × tabela `tags`. |
| F10 | Consequência de F9: a regra "categoria com um único candidato conhecido é aplicada automaticamente" disparou **1 vez em 25 (4%)**. O laço de pergunta virou o caminho normal, não a exceção. | `services/curation.py::ProductProposal.auto_tag`; saída real (`Aplicado: 1 categoria(s)`). |
| F11 | O usuário respondeu **"1" em 21 de 21 perguntas** de categoria, em sequência, sem exceção. | Transcript do uso real. |
| F12 | F9/F10 repetem, para a contagem de tags, a descoberta que já derrubou o uso de `confidence` na v2: o modelo emite um sinal de incerteza que **não** corresponde a incerteza real. | `CLAUDE.md`, "Camada opcional de IA" ("dúvida = 2–3 tags, nunca `confidence`"). |

## 1. O que **não** é problema — registrar para ninguém "consertar"

- **A extração de conteúdo funciona** (F1, F2). Não há bug a corrigir no prompt, no `_valid_content` nem no `enrich_products`. Quem ler a tela de revisão e concluir o contrário está lendo a coluna errada (F3).
- **Recusar conteúdo em produto vendido por peso é correto**, não uma lacuna (F2, F6).
- **Recusar `30m x 28cm` e `21cm` é correto**: é dimensão, e o projeto já rejeitou duas vezes extrair tamanho por regex da descrição. Isso continua rejeitado.

## 2. Requisitos funcionais

### RF1 — Pendência passa a ser por campo faltando, não por ausência de tag

Um produto é pendente de revisão quando falta **tag**, **conteúdo** ou **tipo**.

- **Conteúdo só conta como faltando para produto vendido por UN.** Produto vendido por KG nunca é pendente por conteúdo — R$/kg já é o preço por conteúdo, pela mesma regra de base que a v2.2 estabeleceu (F6). Sem essa exceção, 26 produtos ficariam pendentes para sempre sem nada a ganhar.
- A revisão **nunca sobrescreve o que já está preenchido**: nome só quando o produto ainda tem nome cru, tipo só quando é nulo, conteúdo só quando é nulo, tag só quando ainda não existe naquele produto. Essa é a garantia que torna seguro reexaminar um produto já revisado — as guardas já existem hoje e precisam continuar valendo.

**Decisão aceita:** produto cujo conteúdo a IA legitimamente não sabe responder (Sacola, Brócolis, Alface, Espátula, Prato 21cm, Filme PVC) **volta a aparecer em toda rodada**. Isso é custo aceito, não defeito: são 6 linhas, cabem num lote que já ia rodar, e é justamente reperguntar que conserta o caso dos Ovos (F8). **Nenhum marcador de "não tem conteúdo" entra no schema** — foi avaliado e recusado por congelar erro da IA.

### RF2 — Categoria deixa de perguntar: a primeira sugestão é aplicada

A primeira categoria sugerida pela IA é gravada automaticamente, sem pergunta, com ou sem terminal.

Justificativa: passa o mesmo teste de duas condições que autorizou nome, conteúdo e tipo — é reversível por comando que já existe (`julius produtos tag ID X --remover`) e um erro é visível na saída normal (`produtos listar`). A premissa que sustentava a pergunta ("2 tags significam dúvida real") está medida como falsa (F9, F10, F12), e o comportamento humano medido é unânime (F11).

Consequência aceita: `produtos revisar` e a revisão dentro de `importar` passam a **não perguntar nada**. A curadoria inteira vira uma passada não-interativa com resumo agregado e log de desfazer.

### RF3 — A tela de revisão precisa distinguir "já resolvido" de "sem resposta"

Nas colunas **Conteúdo** e **Tipo**, quando não há proposta mas o produto já tem o dado, mostrar o **valor atual em estilo apagado**. Célula vazia passa a significar uma coisa só: "a IA não respondeu".

A coluna **Cupom** deve mostrar a descrição real do cupom, não o nome canônico já renomeado (F4).

### RF4 — A primeira rodada roda inteira, sem teto e sem confirmação

Com o critério novo, a primeira execução alcança ~86 produtos (a maioria por falta de **tipo**, não de conteúdo) — cerca de 4 chamadas de IA, na casa de US$ 0,02. Roda de uma vez. Sem pergunta de confirmação, sem limite por execução. Depois dessa passada o catálogo estabiliza e as rodadas seguintes cobrem só o que entra com nota nova.

## 3. Requisitos não-funcionais e invariantes preservados

| # | Invariante |
|---|---|
| RNF1 | **Nenhum estado novo no schema.** RF1 e RF2 se resolvem com o dado que já existe (`content_quantity`, `kind`, `product_tags`, `prices.unit`). |
| RNF2 | Toda gravação automática continua **reversível por comando existente** e registrada em `actions.jsonl` com o desfazer — inclusive a categoria, que passa a entrar no log como as outras. |
| RNF3 | **Nenhuma extração de conteúdo por regex sobre descrição**, em nenhuma circunstância. Continua valendo a rejeição registrada no `CLAUDE.md`. |
| RNF4 | Fusão de produto continua 100% manual. Nada aqui a toca. |
| RNF5 | Nenhuma função de IA lança exceção; falha continua virando "sem sugestão". |
| RNF6 | A regra de base de comparação (KG direto, UN exige conteúdo) não muda — RF1 apenas **consome** essa regra para decidir pendência. |

## 4. Questões em aberto para o design

1. **O que sobra de `--sim` e do modo interativo?** Com RF2 não há mais pergunta de categoria, e a revisão fica idêntica com e sem TTY. `--sim`, `_ask_tag`, `_confirm_pt` e `_is_interactive` podem ficar sem uso. Decidir se a flag some (quebra script existente?) ou vira no-op documentado.
2. **A coluna "Categoria" ainda precisa do prefixo `?`** para 2+ candidatos, se a primeira é sempre aplicada? Ou passa a mostrar a aplicada e as alternativas de outro jeito?
3. **Pendência por tipo tem o mesmo problema dos nulos legítimos?** Existe produto para o qual a IA nunca vai propor tipo? Não medido — a última rodada tipou 25 de 25.
4. **Reexaminar produto já revisado gasta tokens com campos que não faltam.** Vale mandar ao prompt só os campos faltantes por produto, ou a economia não paga a complexidade? (Medição sugere que não paga: US$ 0,02 pela passada inteira.)
5. **O caso dos Ovos (F8) se conserta sozinho** na primeira rodada do critério novo — confirmar isso na execução real antes de considerar o assunto fechado.

## 5. Fora de escopo, decidido nesta sessão

- **Marcador "esse produto não tem conteúdo"** (coluna, sentinela ou comando `--nao-tem`): recusado. Custo em schema e risco de congelar erro da IA maiores que o incômodo de 6 linhas.
- **Heurística de nome para decidir pendência de conteúdo** (`só é pendente quem tem número no nome`): recusada. É o regex sobre descrição já rejeitado duas vezes, e `"30 unidades"` — o caso dos Ovos — escaparia dele.
- **Teto de produtos por execução** e **confirmação antes de gastar**: recusados (RF4).
- **Mexer no prompt para pedir uma categoria só**: avaliado e não escolhido. RF2 resolve o atrito sem tocar no prompt, e manter 2 candidatos preserva a informação na tabela.
- Qualquer mudança em `consultar`, `mercados comparar`, fusão ou base de comparação.


## 6. Segunda rodada — intuição de varejo e HITL para conteúdo

### 6.1 Fatos medidos

Sonda executada nesta sessão contra o provedor real (`deepseek-flash`), 9 produtos, 1 chamada, **US$ 0,00073**. O prompt da sonda pediu algo que o prompt de produção **não** pede: como o produto é vendido no varejo brasileiro (`unidade` / `pacote` / `peso` / `volume`), até 3 candidatos de conteúdo, e se o número veio do rótulo ou do costume. Script no scratchpad, não versionado (mesma convenção do smoke test da v2); o resultado é este:

| # | Fato | Evidência |
|---|---|---|
| F13 | **A intuição de varejo existe e acerta a maioria.** 5 dos 7 produtos-UN sem conteúdo receberam candidato útil: Sacola, Brócolis Ninja, Espátula e Alface como `1 UN` ("a embalagem é a unidade"), e Ovos Iana como `30 UN`. | Saída da sonda. |
| F14 | **O caso dos Ovos (F8) se resolve com essa pergunta:** o modelo respondeu `30 UN` marcando que o número veio do próprio nome. | Saída da sonda × F8. |
| F15 | **Quando não sabe o número, o modelo sabe que não sabe — e propõe alternativas.** `Prato Redondo Descartável 21cm` veio como `forma: pacote`, candidatos `10 UN` e `20 UN`, número **não** vindo do rótulo. É o formato exato de uma pergunta ao humano. | Saída da sonda. |
| F16 | **O erro perigoso é o mesmo de sempre, agora com auto-certeza.** `Filme PVC Wyda 30m x 28cm` virou `30 UN` **com o campo "número veio do rótulo" marcado como verdadeiro** — os 30 metros lidos como 30 unidades. É a armadilha `PRATO 21CM` que o projeto rejeitou duas vezes, e o modelo se declarou certo dela. | Saída da sonda. |
| F17 | **Terceira falha consecutiva de auto-relato de confiança.** `confidence` (v2, rejeitado), número de tags (F9/F12), e agora "o número veio do rótulo" (F16). O **único** sinal honesto medido é o modelo **recusar responder**: o prompt de produção acertou `null` em 6 de 6 (F2). | F2, F12, F16. |
| F18 | **No formato "dê candidatos", o modelo nunca declina.** Em 9 produtos não devolveu lista vazia nem `desconhecido` uma única vez — chuta sempre. Nos controles vendidos por peso produziu lixo dimensional: Bacon tablete `500 KG`, Queijo brie `200 KG`. | Saída da sonda. |
| F19 | O lixo de F18 é inofensivo **porque o RF1 já não pergunta conteúdo de produto vendido por KG**. A sonda incluiu esses dois como controle negativo, e eles confirmam o valor do filtro. | RF1 (F6) × F18. |

### 6.2 RF5 — Conteúdo recusado pela IA vira pergunta ao humano, com candidatos

Quando o enriquecimento devolve `null` para o conteúdo de um produto vendido por UN, o sistema **pergunta ao usuário**, oferecendo os candidatos mais prováveis para escolha por número, com opção de digitar outro valor e de pular.

- **O gatilho é a recusa da IA, não um score** (RF6). Binário, sem constante nova, sem calibragem periódica.
- Pular (ou rodar sem terminal) deixa o produto pendente; ele **volta na próxima rodada**. Nenhum estado novo, nenhuma decisão permanente tomada por inércia — mesma escolha já feita para os nulos legítimos em §2/RF1.
- É esta a exceção interativa que o usuário aceitou: "deve ser a exceção", e é — são ~6 produtos hoje, e só produto novo depois.

### 6.3 RF6 — A intuição de varejo alimenta a pergunta e nunca grava

O conhecimento de "como isso é vendido no Brasil" pode ser consultado, mas **só para gerar as opções** apresentadas no RF5. Nenhum valor vindo de intuição é gravado sem uma tecla do usuário — nem `1 UN`, que foi 4/4 correto na amostra.

Justificativa, com o contraexemplo medido: a mesma intuição que acerta `Brócolis → 1 UN` erra `Filme PVC → 30 UN` **e se declara certa** (F16). Como conteúdo errado não fica evidente — vira um R$/UN plausível na tabela de `consultar` e entra no preço por conteúdo de `mercados comparar` —, ele **não passa** na condição (2) do teste de duas condições (`comparability-closure.md` §4): o erro precisa ser visível na saída normal. Nome, tag e tipo passam; conteúdo **inferido por costume** não passa. Conteúdo lido de rótulo inequívoco continua passando e continua automático — essa é a diferença que separa os dois casos.

Consequência aceita: a comparação bandeja-contra-bandeja (Brócolis entre duas lojas) só é destravada depois que o usuário confirma. Uma tecla por produto, uma vez na vida do produto.

### 6.4 Emenda ao RF2 — a revisão não fica 100% não-interativa

§2/RF2 dizia que a revisão passaria a "não perguntar nada". Isso continua valendo **para categoria** — e só. Estado final:

| Campo | Comportamento |
|---|---|
| Nome legível | aplica sozinho (produto ainda com nome cru) |
| Categoria | aplica a primeira sugestão, sempre, sem perguntar (RF2) |
| Tipo | aplica sozinho |
| Conteúdo **lido do rótulo** | aplica sozinho |
| Conteúdo **que a IA recusou** | **pergunta**, com candidatos de intuição (RF5/RF6) |

O laço interativo não desaparece: ele **muda de campo**. Sai da categoria, onde o modelo sempre responde e sempre acerta a primeira (25/25), e entra no conteúdo, onde o modelo honestamente declina.

Para categoria, o "threshold" pedido pelo usuário é vazio na prática: não houve um caso sequer em que a IA não soubesse propor uma primeira categoria conhecida (F9). Se algum dia devolver **nenhuma** categoria, esse é o gatilho natural para perguntar — mesma regra do RF5, mesmo sinal (a recusa).

## 7. Questões em aberto acrescentadas por esta rodada

6. **Uma chamada ou duas?** A intuição (`forma`/`candidatos`) pode virar campos extras do mesmo item de `enrich`, ou uma segunda chamada só para os produtos recusados. A segunda opção custa ~US$ 0,0007 por rodada e mantém o prompt de produção intacto — inclusive a recusa confiável, que é o ativo mais valioso aqui (F17). Risco de juntar: contaminar o `null` honesto com o hábito de chutar (F18).
7. **Como rotular o candidato na pergunta.** `[1] 1 UN (bandeja)` — a explicação entre parênteses vem do campo `forma` e ajuda a decidir, mas é texto vindo da IA aparecendo direto na interface.
8. **Produto vendido por UN cujo `forma` a IA diz ser "peso"** (ex.: um queijo em peça que o cupom marcou como UN): perguntar mesmo assim, ou tratar como sem conteúdo?

## 8. Fora de escopo, decidido nesta rodada

- **Gravar conteúdo vindo de intuição sem confirmação** — em qualquer variante, inclusive só para `1 UN`. Recusado por F16/RF6.
- **Score de confiança da IA como gatilho** — recusado pela terceira vez, agora com contraexemplo próprio (F16/F17).
- **Marcar "não tem conteúdo" ao pular** — recusado de novo, pela mesma razão de §5: congela erro por inércia.
- **Extrair conteúdo da descrição por regex** — continua rejeitado, e F16 é a evidência mais nova a favor da rejeição.
