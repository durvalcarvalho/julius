# Julius — por que só 6 grupos: design da cobertura de `mercados comparar`

> Sessão de 2026-09-17 (`/sc:troubleshoot` → `/sc:design`), a partir do uso real: *"Tô achando estranho ter tão poucos produtos que dá pra comparar preços... Principalmente de vegetais e frutas que eu compro sempre, de carne também que é comum eu comprar. Pq não tá comparando os demais produtos?"*
> **Tema diferente do de `differentiated-kinds.md`, na mesma tela.** Aquele pergunta *"os 6 grupos que aparecem significam algo?"* (bem fungível × diferenciado, RF0/RF1/RF2). Este pergunta *"por que só 6?"*. Um é qualidade do grupo, o outro é cobertura. Nenhum dos dois responde o outro.
> **Estado: implementado em 2026-09-17**, depois dos tickets 147/148 e com a árvore verde. Três mudanças, não duas — D1, D2 e um terceiro achado durante a implementação (§7). 754 testes verdes.
> **Nada disso é bug.** O funil de §0 fecha exato. As duas decisões abaixo existem para a saída **dizer** por que é pequena, em vez de deixar o usuário deduzir.

## 0. Medições (banco de produção, 105 produtos / 132 preços / 6 notas / 5 lojas)

Ficam aqui porque se perderam: foram anexadas a `docs/requirements/differentiated-kinds.md` §0 como F7–F10 e sobrescritas na reescrita do mesmo dia, que renumerou aqueles fatos para outra coisa. Este doc não depende mais daquela numeração.

| # | Fato | Evidência |
|---|---|---|
| C1 | **A cobertura é limitada pelo dado, não pelo código.** Os **87 tipos** batem exatamente com `differentiated-kinds.md` (mesmo banco, mesmo dia); a contagem de produtos divergiu porque os 108 de lá são a rodada reprocessada da v2.4 e este banco tem **105**. 105 produtos → **104 com tipo (99%)** → **87 tipos distintos** → **7 tipos comprados em 2+ mercados** → 6 sobrevivem à divisão por `unit` → 6 tabelas. A aritmética fecha: nenhum grupo é suprimido por bug. **80 dos 87 tipos foram comprados em um mercado só** — com 6 notas de 5 lojas (só a Costa foi visitada duas vezes), as cestas quase não se cruzam. | Script sobre o banco real, agrupando por `kind` e por `(kind, unit)`. |
| C2 | **Nos dois corredores que o usuário nomeou o teto já foi atingido, e num deles é zero.** *hortifruti*: Costa vendeu 15 tipos, Assaí 6, DdC-Cand 2, DdC-Guará 1; compartilhados são exatamente **4** (`banana`, `cebola`, `tomate`, `uva`) e **os 4 estão na tela**. Laranja, limão, maçã, mexerica, mamão, cenoura, abóbora, quiabo, repolho, alface: só na Costa. *carnes*: **zero** compartilhados — Assaí (bacon, carne seca), Costa (acém, filé de peito de frango, fraldinha, linguiça, picanha), HTP (contrafilé). Seis cortes, nenhuma repetição, e o corte *é* a unidade de comparação: comparar carne exige comprar o mesmo corte em duas lojas. | Mesmo script, cruzando `product_tags` com loja. Converge com `differentiated-kinds.md` F8 pelo outro lado: lá a granularidade de `carnes` está certa, aqui ela não tem par. |
| C3 | **`ovo` × `ovos`: dois tipos que são um, separados por uma letra.** *Ovo branco grande com 30 unidades* (Assaí, R$ 15,90 → **R$ 0,53/UN**) × *Ovos Iana 30 unidades médio branco* (Costa, R$ 16,99 → **R$ 0,57/UN**): mesmo bem fungível, os dois com tag `hortifruti` — e é justamente o caso dos 20×30 ovos que motivou `price_per_content` no projeto inteiro. Segundo candidato defensável: `suco` × `suco integral` (uva integral 1,5L nas duas lojas, R$ 9,93/L × R$ 9,99/L). Os outros dois vizinhos alfabéticos **reprovam** no teste fungível×diferenciado: `macarrão` × `macarrão espaguete` (Barilla espaguete R$ 13,70/kg × Rummo fettuccine R$ 39,98/kg, 3×) e `água com gás` × `água mineral` (par já rejeitado por nome no `CLAUDE.md`). | Detecção por tipos vizinhos alfabeticamente — a query que o `CLAUDE.md` documenta e que nunca havia sido rodada. |
| C4 | **`s` final ignorado é seguro nos 87 tipos reais: 3 tipos tocados, 1 colisão, e é a correta.** Tocados: `brócolis`, `ovos`, `água com gás`. Colisão única: `ovo` ↔ `ovos`. `brócolis` e `água com gás` passam intactos porque não existe `brócoli` nem `água com gá` no catálogo — a regra casa com grafia existente, nunca reescreve. | Script sobre os 87 tipos distintos do banco real. |
| C5 | **`queijo parmesão` é o único grupo perdido pela divisão por `unit`.** *Piracanjuba pedaço* (Assaí, KG, R$ 115,90/kg) × *Frac Scala 180g* (Costa, UN com conteúdo 180 g → **R$ 183,28/kg**): duas bases já comensuráveis que nunca se encontram, porque `compare_stores` agrupa por `(kind, unit)` **antes** de `comparison_basis` escolher a base. | Mesmo script; `services/comparison.py:30`. |

## 1. D1 — o rodapé passa a dizer a cobertura

O rodapé é o único lugar que já declara "o que sustenta esta comparação" (`base: 6 grupos · 04/09 a 16/09`). A cobertura pertence a ele:

```
base: 6 grupos · 04/09 a 16/09 · 80 dos 87 tipos comprados em um mercado só
```

Quando nenhum tipo foi comprado em dois mercados, a mesma frase é a resposta inteira:

```
Nenhum tipo de produto foi comprado em dois mercados ainda — sem base para comparar.
Todos os 87 tipos comprados até agora saíram de um mercado só.
```

**Por que esses dois números e não o funil todo.** "80 em um mercado só" é o complemento que *responde* à pergunta; "7 em dois mercados" só repete que a saída é pequena. Os degraus de C1 são material de doc, não de rodapé.

**O rodapé não vai somar, e é aceito.** 6 + 80 = 86, não 87: falta o `queijo parmesão` de C5, elegível e morto na divisão por `unit`. A linha não afirma partição (nem "6 de 87", nem "os outros"), então cada metade continua verdadeira — mas fica registrado, para a subtração não voltar como a mesma pergunta. Fechar C5 zera a diferença.

**Isto deleta código, não adiciona.** Hoje o `cli/stores.py` faz uma segunda consulta (`catalog.list_products`) para contar produtos com tipo, e esse número é o errado: neste banco diria *"1 dos 105 produtos ainda não têm tipo"* — verdadeiro, irrelevante, e aponta para a causa errada, porque a curadoria está em 99%. `kinds_total == 0` já significa "nenhum produto tem tipo ainda" (todo produto nasce de uma linha de preço, então todo produto tipado aparece no funil). Somem a consulta, o contador `typed` e o ramo.

## 2. D2 — `s` final ignorado em `set_kind` (C3/C4)

`repositories/products.py::set_kind:91` já reaproveita a grafia existente quando `normalize_text` coincide — é lá que a regra de grafia mora, documentado, porque `curation.apply` grava pelos repositórios e uma regra em `catalog` seria contornada. Singular/plural é a mesma comparação com o `s` final ignorado. Vale para a escrita da IA e para o `produtos tipo` na mesma linha, sem caminho novo.

**Isto é o sinal oposto do RF1, não uma variação dele.** RF1 (`differentiated-kinds.md` §4) **divide** tipo grosso demais, com 9 tipos que juntam produtos que não competem; D2 **junta** tipo fino por acidente, um mesmo tipo escrito de duas formas. As duas são correção de granularidade, em direções opostas, e nenhuma atravessa a outra: `ovo`/`ovos` não é um dos 9, e nenhum dos 9 vira par de plural.

**Não é uma das regras automáticas refutadas.** As três de `differentiated-kinds.md` §2 (corredor, dispersão, similaridade de texto) tentam decidir **fungibilidade**, que a conclusão de lá localiza no comprador, não no dado. D2 não decide nada sobre competição: `ovo` e `ovos` são a mesma palavra. É identidade de grafia, a mesma classe do `normalize_text` que já está naquela linha.

**Também não é o "terceiro corte fuzzy" que o `CLAUDE.md` rejeitou.** A objeção registrada é a *constante nova a medir*; um radical sem `s` final não tem score nem limiar — é comparação exata sobre um caractere a menos. Medido em C4: 3 tipos tocados, 1 colisão, correta.

**Qual grafia sobrevive é a que já estava lá** — `set_kind` reaproveita a existente, então é ordem de escrita, não regra. Para `ovo`/`ovos` tanto faz; é rótulo de grupo.

**Limite, explícito:** a regra vale para gravação futura. `ovo` e `ovos` já estão no banco, então o par atual continua exigindo um comando, igual aos de RF1:

```
julius produtos tipo 26 "ovos"   # Assaí, hoje 'ovo'
julius produtos tipo 52 "suco"   # Costa, hoje 'suco integral'
```

## 3. Não decidido aqui

**A contagem agregada ("mais barato em N de M grupos") fica como está.** Já decidido em `differentiated-kinds.md` §6, com razão melhor que a minha: aplicar RF1 nos tipos heterogêneos faz o problema desaparecer por construção, e mexer antes é resolver com código o que o dado vai resolver. D1 reforça isso de graça — o contexto que um filtro queria impor passa a estar escrito no rodapé.

**C5 (a divisão por `unit` antes da escolha de base) — adiado.** É **1 grupo de 87**; peça inteira × porção fatiada é plausivelmente bem diferenciado (o eixo de `differentiated-kinds.md` §1, outra vez), não só base errada; e consertar significa mudar a dimensão de agrupamento em três lugares (`services/comparison.py:30`, `:79`/`:84`, `services/search.py:115`). Desproporcional para um grupo. Reabrir quando aparecer o segundo caso — a assinatura é a de C5.

**Fragmentação além de C3.** `macarrão` × `macarrão espaguete` e `água com gás` × `água mineral` reprovam no teste fungível×diferenciado e não entram em regra nenhuma.

## 4. Contrato

| Camada | Arquivo | Mudança |
|---|---|---|
| `domain` | `models.py::StoreComparison` | `+ kinds_total: int = 0`, `+ kinds_single_store: int = 0`. Com default: `compare_stores` já devolve `StoreComparison((), "", "")` em dois caminhos. |
| `services` | `comparison.py::compare_stores` | no laço que já monta `groups`, um segundo dict `kind -> set(store_cnpj)`. **Os dois números vêm dele, nunca de `len(groups)`**: são 87 tipos contra 89 chaves `(kind, unit)`. |
| `cli` | `stores.py::compare_stores` | a frase de cobertura no rodapé e no ramo vazio; **remove** `catalog.list_products`, o contador `typed` e o aviso de produtos sem tipo. |
| `repositories` | `products.py::set_kind` | o `s` final ignorado na comparação com a grafia existente (D2). |

Nada em `domain/comparison_basis.py`, nada em `services/search.py`, nada em `new_extremes`. A DAG não é tocada.

## 5. Checagens (uma por decisão, sem suíte nova)

- **D1** — dois tipos comprados, um deles em dois mercados: o rodapé diz `1 de 2 ... em um mercado só`.
- **D1, ramo vazio** — nenhum produto com tipo: sai a mensagem de `produtos revisar`.
- **D2** — `set_kind(id, "ovos")` grava `ovo` quando `ovo` já existe.

## 6. Sequência, e o estado real da árvore

**A árvore de trabalho está suja com duas features em voo e 8 testes vermelhos** — o apelido de mercado por CNPJ/nome fantasia (`infra/cnpj_client.py`, `StoreNaming`, `docs/requirements/store-branch-nickname.md`) e a coluna de nomes do RF0. Os vermelhos são daquele trabalho, não deste design: `test_cli_receipts` e `test_e2e` esperam apelidos e dicas que o naming novo mudou.

Ordem, então:

1. **A árvore fica verde antes** — não é este design que conserta isso.
2. **Tickets 147 e 148** (`differentiated-kinds.md` §7) antes, em série: **mesmo arquivo, funções diferentes** — eles mexem em `StorePrice`/`PriceExtreme` e em `_comparison_table`, D1 mexe em `StoreComparison` e no rodapé de `compare_stores`. Não há linha compartilhada: a ordem é por prioridade declarada (RF0 é exibição pura e cobre 9 tipos sem curadoria), não por conflito.
3. **D1 e D2 são independentes entre si** — nenhuma ordem obrigatória entre os dois.
4. **Um teste a reescrever, não apagar:** `tests/test_cli_catalog.py::test_comparar_says_how_many_products_still_have_no_kind` afirma exatamente a frase que D1 remove (`"14 dos 15 produtos ainda não têm tipo"`). O caso que ele cobre — saída vazia com catálogo parcial — continua valendo; troca-se a asserção pela frase de cobertura do ramo vazio.

## 7. O que a implementação acrescentou ao contrato

**Um achado, fora do design:** `julius produtos tipo ID TIPO` ecoava o **argumento**, não o que gravou. Com D2 isso virou mentira comum (`produtos tipo 108 "ovos"` → gravou `ovo`, dizia `ovos`), e o eco é justamente onde o usuário veria o agrupamento acontecer. O mesmo defeito já existia para `ACAI` → `açaí` desde a v2.2, então é conserto de raiz, não de sintoma: `cli/products.py` relê o produto (`catalog.get_product`) em vez de reformatar o argumento. Teste próprio.

**Um desvio do texto do §1:** `_coverage` tem três ramos, não dois. O caso `total == 1` (primeiro uso, um tipo só) produziria *"todos os 1 tipos"* na forma escrita aqui; virou *"o único tipo comprado saiu de um mercado só"*.

**Verificado contra o banco real** (cópia, sem gravar no do usuário): o rodapé imprime `80 dos 87 tipos comprados em um mercado só`, e `produtos tipo 108 "ovos"` grava `ovo` e destrava o grupo `ovo · por UN (por conteúdo)` com R$ 0,53 (Assaí) × R$ 0,57 (Costa) — exatamente C3.
