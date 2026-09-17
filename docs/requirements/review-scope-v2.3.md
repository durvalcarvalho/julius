# Julius — escopo e atrito da revisão assistida: requisitos

> Brainstorm de 2026-09-16 (`/sc:brainstorm`), disparado pelo primeiro `julius produtos revisar` real depois da v2.2, no banco de produção. Duas observações do usuário: (1) "vários itens não têm conteúdo definido, mesmo tendo a quantidade no nome — por que não pegamos essa informação?"; (2) "nessa sequência de tags tudo é sempre a primeira opção, então por que não fazer isso automático?".
> Insumos: `~/.local/share/julius/prices.db` e `~/.local/share/julius/ai_calls.jsonl` reais, lidos nesta sessão; respostas do usuário às perguntas do brainstorm.
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
