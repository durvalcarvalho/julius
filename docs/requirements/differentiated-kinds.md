# Julius — comparar só o que é comprável (bem fungível × bem diferenciado): requisitos

> Brainstorm de 2026-09-17 (`/sc:brainstorm`), duas rodadas, a partir de uso real.
> Rodada 1 — pergunta sobre a saída de `julius mercados comparar`: "tem uns produtos que é mais complexo comparar, tipo vinho, que vinho foi, não dá pra botar todos os vinhos no mesmo balaio."
> Rodada 2 — o usuário fecha o enquadramento: "tem alguns produtos que tem diferenciação (e isso reflete no preço) e tem outros que não, que é meio commodity (frutas, verduras, carnes) **eu quero comparar o que é comprável**."
> Rodada 3 — o usuário aponta o que faltava em toda a análise anterior: "**o nome é importante tbm, só vinho é muito genérico né**". É a mesma frase da rodada 1 ("que vinho foi") vista pelo lado da saída: o rótulo do grupo é a única identidade que a tela mostra, e ele é genérico por construção. Vira o RF0 (§4.0), que passa na frente de tudo.
> Insumos: banco de produção real (108 produtos, 132 preços, 87 tipos, 11 categorias em uso); `services/comparison.py`, `domain/comparison_basis.py`, `services/suggestions.py::SYSTEM_PROMPTS["enrich"]`, `services/curation.py::_proposed_kind`, `repositories/products.py::incomplete_product_ids`.
>
> **Resultado das três rodadas, em ordem de prioridade:**
> 1. **Nenhuma comparação diz hoje o nome dos produtos que comparou** (F11/F12) — nem a tabela do `mercados comparar`, nem a frase do sinal do `importar`. Corrigir isso resolve os 9 tipos de uma vez, inclusive os que nenhuma regra sabe classificar, sem curadoria nenhuma. É o RF0 e é o que deve ser feito primeiro.
> 2. O conceito de "isso compete com aquilo" já existe no schema — é `products.kind`; falta granularidade nos tipos que a IA propôs (RF1) e uma tela para ver quais estão misturando (RF2).
> 3. Três regras automáticas candidatas foram medidas e **refutadas** (§2): por corredor, por dispersão de preço e por similaridade de texto.

## 0. Fatos medidos

| # | Fato | Evidência |
|---|---|---|
| F1 | **O eixo não é "mesmo produto × produtos diferentes".** Dos 6 grupos que `compare_stores` publica: 3 comparam o **mesmo** `product_id` em lojas diferentes (`cebola` 7,89/9,99; `sacola reutilizável` 0,22/0,22; `tomate` 11,89/14,99 — os três já fundidos à mão); 1 compara produtos diferentes e **está certo** (`banana`: *Banana Prata Extra União* R$ 3,79/kg × *Banana prata* R$ 5,99/kg); 1 é limítrofe (`uva`, duas bandejas de 500 g); **1 não significa nada** (`vinho`: *Mioranza frisante suave* R$ 31,99/L × *Norton BC SV* R$ 46,53/L). | Script sobre o banco real, agrupando por `(kind, unit)` e resolvendo a base com `comparison_basis`. |
| F2 | **O consumidor mais afetado não é `mercados comparar`, é `new_extremes`** (o sinal "Nesta compra:" do `importar`), que usa a mesma janela `row.kind == record.kind`. Contra a nota real de 16/09: `[vinho] MENOR: Mioranza R$ 31,99 contra R$ 46,53 do Assaí` e `[uva] MAIOR: Uva Green Dreams Mimo R$ 29,98 contra R$ 13,98 do Assaí`. O segundo é pior: lê-se como "você pagou caro" quando só foi comprada uma variedade premium. `[banana] MENOR: R$ 3,79 contra R$ 5,99` saiu certo, na mesma rodada. | `new_extremes(conn, [chave de 16/09])` executado nesta sessão. |
| F3 | **A contagem agregada lava o grupo ruim.** Hoje: FL 3 Costa "mais barato em 4 de 5 grupos" — dois desses 4 são `banana` e `vinho`. Restrita a grupos de mesmo `product_id`: FL 3 Costa 2 de 2, Assaí **1 de 3 → 0 de 0**, Dona de Casa Candangolândia 1 de 2 → 1 de 2, Guará 0 de 2 → 0 de 2. | Mesmo script de F1, contando vitórias com e sem filtro. |
| F4 | **Uma loja é representada pela linha mais barata que cobrou no grupo.** Para tipo fungível é o certo ("o que eu pagaria lá"); para tipo diferenciado é viés direcional — quem estocou a variedade barata ganha o grupo para sempre. | `compare_stores`, docstring e `cheapest`. |
| F5 | **A IA nunca sobrescreve um `kind` já escolhido** (`_proposed_kind` devolve `None` quando `product.kind is not None`), e `incomplete_product_ids` só cobra "falta tipo" de quem está sem tipo. Um tipo corrigido à mão **não** é desfeito nas rodadas seguintes. | `services/curation.py:65-67`; `repositories/products.py::incomplete_product_ids`. |
| F6 | `products.kind` é **texto livre**, sem `CHECK` nem vocabulário fechado, e `compare_stores` descarta grupo com menos de 2 lojas (`if len(cheapest) < 2: continue`). Tipo mais fino faz o grupo desaparecer sozinho. | migração `0003_product_kind.sql`; `compare_stores`. |
| F7 | **Só 9 dos 87 tipos têm mais de um produto** — e são exatamente esses 9 que podem estar misturando coisas não-comparáveis. `mercados comparar` só revela 6 deles (os que têm duas lojas): `tempero` (5 produtos), `uva` (4), `água mineral` (3), `banana`, `manga`, `suco`, `vinho`, `refrigerante`, `aveia` (2 cada). Os outros 78 tipos têm um produto e não têm como errar. | Query de `(kind, unit)` com ≥2 `product_id` no banco real. |
| F8 | **`carnes` — o caso "commodity" do usuário — já está com a granularidade certa e não tem nenhum problema hoje**: os 8 produtos têm um tipo por corte (`picanha`, `fraldinha`, `contrafilé`, `acém bovino`, `linguiça`, `bacon`, `carne seca`, `filé de peito de frango`), zero tipos com mais de um produto. O corte *é* a unidade de comparação, e a IA acertou. | `products` × `product_tags` no banco real. |
| F9 | **Achado colateral, não é este requisito:** `tempero` é a maior dispersão da saída (4,45x) com valores de R$ 149,50 a R$ 665,83 — são sachês de 12–20 g, e `price_per_content` produz um número aritmeticamente correto e ilegível. Problema de leitura na mesma tabela, independente de fungibilidade. | Tabela de dispersão por tipo, nesta sessão. |
| F10 | **Achado colateral:** `sqlite3` **não está instalado** nesta máquina (`which sqlite3` vazio, `/usr/bin/sqlite3` inexistente). A saída de emergência documentada no `CLAUDE.md` ("Decisões" item 2: corrigir linha de preço errada via `sqlite3 prices.db`) não existe na prática — e "rode uma query" não serve como resposta para a descoberta de §5. | `which sqlite3`, `ls /usr/bin/sqlite3`. |

| F11 | **A tabela do `mercados comparar` não mostra o nome de nenhum produto.** `_comparison_table` (`cli/stores.py:119-129`) monta `Table("Mercado", "Preço", "Data", title=f"{group.kind} · {basis}")` — o rótulo do grupo (`vinho`) é a **única** identidade de produto na tela, e `StorePrice` (`domain/models.py`) nem carrega o nome para exibir. Com uma coluna "Produto", os três casos se explicam sozinhos: `Mioranza frisante 750ml suave branco` × `Norton 750ml BC SV` (absurdo na hora), `Uva Vitória` × `Uva Pta Seleta União` (o usuário julga), `Banana Prata Extra União` × `Banana prata` (claramente ok). | `cli/stores.py`; `domain/models.py::StorePrice`; tabela renderizada com a coluna nesta sessão. |
| F12 | **O sinal do `importar` nomeia o produto comprado e esconde o que ele bateu.** `_extreme_line` (`cli/receipts.py:205-213`) imprime `era {previous_price} em {previous_store}, {previous_at}` — e `PriceExtreme` tem `previous_store`/`previous_price`/`previous_at`, mas **não tem `previous_product_name`**. Saída real: `↓ Vinho brasileiro Mioranza frisante 750ml suave branco R$ 31,99/L (por conteúdo) menor preço já pago (era R$ 46,53 em ASSAI-ATACADISTA, 04/09)`. É o mesmo buraco de F11 num lugar onde não há coluna para acrescentar — há um campo. O caso da uva fica pior: `↑ Uva Green Dreams Mimo ... maior preço já pago (era R$ 13,98 ...)` afirma "pagou caro" sem dizer que o R$ 13,98 era Uva Vitória. | `cli/receipts.py::_extreme_line`; `domain/models.py::PriceExtreme`; `new_extremes` executado nesta sessão. |
| F13 | **`julius produtos tipo ID --remover` NÃO é durável — é uma armadilha.** Medido em cópia do banco: o produto 23 (vinho) está fora da fila de pendentes; depois de `clear_product_kind`, `incomplete_product_ids` volta a incluí-lo, e como `product.kind is None`, `_proposed_kind` aceita a proposta seguinte. Ou seja: a próxima `produtos revisar` grava `vinho` de volta **automaticamente, sem perguntar**. "Tirar o tipo do bem diferenciado" (que seria a opção mais barata, já que `new_extremes` trata `kind IS NULL` com o escopo por produto) não é uma opção hoje: o sistema não sabe distinguir "sem tipo ainda" de "sem tipo de propósito". | Script com `catalog.clear_product_kind` + `products.incomplete_product_ids` sobre cópia do banco real. |

## 1. O problema, em uma frase

`products.kind` responde "que tipo de coisa isso é" e é consumido como **grupo de alternativas de compra**. Para bem fungível (cebola, tomate italiano, picanha, banana prata) o tipo é um balaio legítimo: se eu quero cebola, compro a mais barata. Para bem **diferenciado**, marca e variedade *são* o preço — ninguém troca um Norton por um frisante suave, nem Lemon Pepper por Dry Rub Beef.

O código não está errado: `compare_stores` e `comparison_basis` fazem exatamente o especificado, sobre um agrupamento grosso demais. **O dado está errado, não o código.**

## 2. Três regras automáticas, medidas e refutadas

O pedido "quero comparar o que é comprável" convida a uma regra que decida sozinha. Nenhuma das três candidatas sobrevive ao banco real — e cada uma falha com um contraexemplo **dentro** do próprio critério:

| Regra candidata | Contraexemplo medido | Veredito |
|---|---|---|
| **Pelo corredor (tag)**: `hortifruti`/`carnes` comparam, `bebidas`/`utilidades` não | Falha nos dois sentidos. Dentro de `hortifruti`: `banana` (Prata × Prata Extra, comparável) e `manga` (**Palmer R$ 5,99/kg × rosa R$ 8,90/kg** — variedades diferentes, não comparáveis). Dentro de `bebidas`: `vinho` (não comparável) e **`água mineral`** (Indaiá 1,5L R$ 2,46/L × Crystal 500ml R$ 2,98/L — commodity pura, marca irrelevante). | Refutada |
| **Pela dispersão de preço no grupo** ("se varia mais de X%, não compare") | A ordem mistura os dois casos: `uva` 2,52x → `banana` **1,58x (legítima)** → `suco` 1,51x → `manga` 1,49x → `água mineral` 1,46x → **`vinho` 1,45x** → `refrigerante` 1,05x. O `vinho`, que é o caso que motivou esta sessão, tem dispersão **menor** que a `banana`, que está certa. Nenhum corte separa. | Refutada |
| **Por similaridade de texto entre os nomes** | `Água mineral Indaiá 1,5L` × `Água Crystal com gás 500ml` divergem em marca e tamanho e **são** comparáveis por litro; `Banana prata` × `Banana Prata Extra União` quase coincidem e são comparáveis — mas `Manga rosa` × `Manga Palmer` também quase coincidem e **não** são. | Refutada |
| **Por `product_id` igual** (comparar só produto fundido) | Mataria a linha da `banana`, que é a melhor linha da saída inteira (F1). | Refutada para as tabelas; ver §6 para a contagem |

**Conclusão:** fungibilidade não é propriedade do produto, do corredor nem do preço — é **do comprador**. Nenhum sinal armazenado hoje a contém, e nenhum sinal derivável a contém. Só a declaração do usuário contém. É o mesmo formato de conclusão de "sem veredito automático de barato/caro" e de "fusão continua manual": o sistema mede, o humano julga.

## 3. Causa raiz da granularidade grossa: uma frase no prompt

`SYSTEM_PROMPTS["enrich"]` (v2, `services/suggestions.py:60-65`) instrui, textualmente:

> `"kind"`: o TIPO da coisa […] Marca, fornecedor, sabor e tamanho **NÃO** entram no tipo ("tomate", não "tomate italiano união"; **"uva", não "uva green dreams"**).

A IA não errou: **ela produziu exatamente o tipo que o prompt manda produzir**, usando como exemplo negativo justamente `uva green dreams`, um dos casos quebrados. E a instrução não pode simplesmente ser invertida — a tensão está dentro dela:

- **Tirar a marca é obrigatório** para bem fungível: sem isso `Tomate Italiano União` nunca compara com `Tomate Italiano`, e a fusão manual que o usuário já fez perderia sentido.
- **Manter a variedade é obrigatório** para bem diferenciado: sem isso todo vinho cai no mesmo balaio.

E §2 mostra que nenhuma regra textual distingue os dois casos. Logo o prompt não tem como acertar sempre — o que ele pode fazer é errar para o lado barato de corrigir, e a correção precisa ser visível (§5).

## 4.0 Requisito funcional 0 (prioridade máxima) — nenhuma comparação sem os dois nomes

**RF0 — toda afirmação de comparação deve dizer o nome dos dois produtos que ela comparou.** Hoje nenhuma diz (F11, F12), e é essa ausência que transforma um agrupamento grosso em afirmação errada: `vinho · por L` com duas linhas de preço *parece* uma comparação de vinho; as mesmas duas linhas com `Mioranza frisante suave` e `Norton BC SV` ao lado **são** obviamente duas coisas diferentes, e o usuário descarta em meio segundo.

Por que isso passa na frente do RF1 e do RF2:

| | RF0 (mostrar os nomes) | RF1 (dividir os tipos) |
|---|---|---|
| Cobertura | **os 9 tipos de uma vez**, inclusive `manga`, `água mineral` e `uva`, que nenhuma regra de §2 sabe classificar | um tipo por vez, à mão |
| Curadoria exigida | **nenhuma** | um comando por produto, sempre que um tipo novo passar de um produto |
| Regride? | **nunca** | não para o passado (F5); **não medido** para produtos novos (§4) |
| Corrige o sinal do `importar`? | sim (F12, um campo) | sim, indiretamente |
| O que resolve | o usuário **julga** qualquer grupo | o grupo ruim **sai** da saída |

Os dois são complementares e a ordem importa: com os nomes na tela, dividir tipo deixa de ser correção de bug e passa a ser limpeza de ruído — opcional, feita quando incomodar. Sem os nomes, dividir os 9 tipos é obrigatório e nunca termina, porque todo produto novo pode criar o décimo.

Escopo mínimo de RF0, dois pontos:
1. **`mercados comparar`**: coluna "Produto" na tabela de grupo (`StorePrice` ganha o nome; `compare_stores` já tem o `PriceRecord` em mão em `cheapest`).
2. **Sinal do `importar`**: `PriceExtreme.previous_product_name`, para a frase virar `era R$ 46,53 (Vinho Norton 750ml BC SV) em Assaí, 04/09`. Quando o `scope` é o próprio produto (tipo ausente), os dois nomes coincidem e o trecho é redundante — vale suprimir nesse caso.

Limite conhecido: a coluna é tão boa quanto o nome. `Vinho Norton 750ml BC SV` mantém `BC SV` abreviado porque o prompt de `enrich` manda preservar a abreviação na dúvida ("Não invente o que a abreviação não permite deduzir"). O conserto é `julius produtos renomear`, que já existe, e o nome editado à mão nunca é sobrescrito (`has_raw_name`).

## 4. Requisito funcional 1 — declarar que dois produtos não competem

**RF1.** O usuário precisa dizer que dois produtos não são alternativas, sem deixar de tê-los tipados. **Já existe e atende:** `julius produtos tipo ID TIPO`, com um tipo mais fino.

```
julius produtos tipo  23 "vinho tinto seco"       #  antes: vinho
julius produtos tipo 104 "vinho frisante suave"   #  antes: vinho
julius produtos tipo  73 "uva green dreams"       #  antes: uva
julius produtos tipo  80 "manga palmer"           #  antes: manga
```

Efeito, sem uma linha de código nova: cada tipo fino passa a ter uma loja só, `compare_stores` descarta o grupo (F6), `new_extremes` cai no escopo por produto (o "escopo degradado" que já existe e é o certo aqui), e a contagem de F3 se corrige nesses grupos.

**Por que isso é estritamente melhor que uma flag `comparavel` por tipo** — e por que a rejeição da rodada 1 **continua valendo**, com motivo melhor: o usuário tem um binário na cabeça (commodity × diferenciado), então a objeção "o gradiente não tem binário" caiu. O que derruba a flag agora é expressividade: `comparable = false` em `uva` mata a comparação de uva para sempre; dividir em `uva vitória`/`uva green dreams` **continua comparando `uva vitória` entre duas lojas** no dia que ela aparecer nas duas. O tipo fino é a flag mais a granularidade — e não custa coluna, migração nem comando novo.

**Não use `tipo --remover` para bem diferenciado (F13).** Seria o caminho mais barato — `new_extremes` já trata `kind IS NULL` com escopo por produto, que é o comportamento certo — mas o produto volta para a fila de pendentes e a IA regrava `vinho` sozinha, sem perguntar, na revisão seguinte. Só o tipo **fino** é estável. Distinguir "sem tipo ainda" de "sem tipo de propósito" exigiria dado novo, e RF0 torna isso desnecessário.

**Durabilidade — duas metades, uma verificada e uma não:**
- **Verificada em código (F5):** um tipo corrigido à mão nunca é sobrescrito. `_proposed_kind` garante.
- **NÃO verificada, e é a metade que decide se §4 basta:** se um vinho **novo** vai receber o tipo fino. O prompt recebe `known_kinds` (`all_kinds(conn)`) e diz "Prefira um tipo da lista quando servir" — mas a **mesma frase** manda tirar a variedade do tipo. Qual das duas instruções ganha é comportamento de prompt, não dedução: um Malbec novo vendo `["vinho tinto seco", "vinho frisante suave"]` pode voltar com `vinho`. **Medir isso é o primeiro item de `/sc:design`**: uma chamada `enrich` real com produtos sintéticos de vinho e o vocabulário já dividido, custo ~US$ 0,002. Se `vinho` voltar, §4 conserta o passado e não o futuro, e o prompt precisa de ajuste (ou o `kind` proposto precisa ser restrito ao vocabulário conhecido, como já é feito com categoria desde a v2.3).

## 5. Requisito funcional 2 — ver quais tipos estão misturando (o único candidato a código)

**RF2.** O usuário precisa ver, num lugar, os tipos com mais de um produto e quais produtos são, para decidir quais dividir. Hoje não existe essa tela:

- `julius produtos listar` tem a coluna "Tipo", mas por produto — o erro só aparece se ele cruzar 108 linhas de cabeça.
- `julius mercados comparar` mostra o agrupamento, mas só dos 6 tipos que têm duas lojas; os outros 3 heterogêneos (`manga`, `aveia`, e o próprio `tempero` em parte) ficam invisíveis até virarem uma linha errada numa comparação futura.
- Uma query direta não é opção: `sqlite3` não está instalado (F10).

É uma tela de **9 linhas hoje** (F7), revisada uma vez e depois só quando um tipo novo passar de um produto. O conteúdo mínimo: tipo · nº de produtos · nomes dos produtos. A dispersão de preço **não** serve como filtro (§2) mas serve como ordenação — põe `tempero` (4,45x) e `uva` (2,52x) no topo, que é onde a atenção rende mais.

**Não decidir onde isso mora sem o usuário** — ver §7.

## 6. Em aberto da rodada 1, ainda em aberto: a contagem agregada

A linha "mais barato em N de M grupos" é a única parte da saída que **afirma** algo; as tabelas só mostram. Enquanto houver tipo heterogêneo na base, ela é o "índice único de carestia por mercado" que o `CLAUDE.md` rejeitou, entrando pela porta de trás (F3: Assaí 1 de 3 → 0 de 0).

Se §4 for aplicado nos 9 tipos de F7, o problema desaparece por construção — a contagem passa a somar só grupos que o usuário declarou comparáveis, que é exatamente o que ele pediu. **Recomendação: não mexer na contagem agora**; aplicar §4 e reavaliar com a saída limpa. Mexer antes é resolver com código o que o dado vai resolver.

## 7. Requisito não funcional

**RNF1 — nada de vocabulário fechado de `kind`.** A granularidade certa é do usuário e varia por corredor: `cebola` e `picanha` já são finas o bastante, `vinho` e `tempero` não. Uma lista de tipos válidos transformaria uma escolha de curadoria em decisão de código.

**RNF2 — o que já está curado não regride.** Qualquer mudança no prompt de `kind` (§3/§4) precisa preservar `_proposed_kind`: tipo escolhido à mão é palavra final.

## 8. Rejeitado nesta sessão (não repropor sem dado novo)

- **Regra por corredor, por dispersão de preço, por similaridade de texto** — as três refutadas com contraexemplo medido em §2. `manga Palmer × rosa` dentro de `hortifruti` e `água mineral` dentro de `bebidas` derrubam a versão por corredor nos dois sentidos; `vinho` 1,45x abaixo de `banana` 1,58x derruba a versão por dispersão.
- **Flag `comparavel` por tipo** (tabela `kinds` ou `products.kind_comparable`) — rejeitada de novo, e agora por expressividade, não por falta de binário: tipo fino é a flag **mais** a granularidade (§4).
- **Filtrar as tabelas por `product_id` igual** — mataria a `banana` (§2).
- **Pedir à IA para julgar se um tipo é comparável** — quinto pedido de auto-relato de incerteza no projeto; os quatro anteriores falharam (`CLAUDE.md`, "Camada opcional de IA"). Além disso §2 mostra que a informação não está no texto, então a IA estaria adivinhando a preferência do comprador.
- **`kind` hierárquico** (`bebidas > vinho > vinho tinto`) — segunda coluna para um caso; `produtos tipo "vinho tinto seco"` já dá a folha, que é a única parte que qualquer consumidor lê.
- **`julius produtos tipo ID --remover` como forma de dizer "não compare este"** — medido em F13: não é durável, a IA regrava o tipo genérico automaticamente na revisão seguinte.
- **Dividir `kind` automaticamente** por qualquer critério — é a mesma coisa que as três regras de §2, aplicada na escrita em vez da leitura.

## 9. Perguntas abertas

**Q0 — RF0 (§4.0) sai primeiro, nesta ordem?** É a recomendação: dois pontos pequenos (uma coluna e um campo), cobertura dos 9 tipos, zero curadoria, sem regressão possível. RF1 e RF2 viram limpeza opcional depois disso.

**Q1 — onde mora a tela de RF2 (§5)?** Três formas, todas pequenas:
(a) subcomando novo `julius produtos tipos` — lista tipo · nº de produtos · nomes, ordenada por dispersão;
(b) flag em comando existente, `julius produtos listar --tipos` (ou agrupar a listagem por tipo quando a flag vier);
(c) uma dica (`guidance`) no fim de `mercados comparar` apontando os tipos heterogêneos que entraram na saída — aproveita o módulo de dicas e não cria comando, mas só vê os 6 de 9 que têm duas lojas.

A (c) é a mais barata e a menos completa; a (a) é a única que mostra os 9.
