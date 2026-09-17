# Julius v2.3 — escopo da revisão e HITL de conteúdo: design

> `/sc:design` de 2026-09-16, a partir de `docs/requirements/review-scope-v2.3.md` (RF1–RF6, §4 e §7 com 8 questões em aberto). Especificação para tickets 131–136; **nenhum código foi alterado**.
> Este documento **fecha as 8 questões em aberto** dos requisitos e refina o RF2 num ponto (§3.2), com a razão medida.

## 0. Decisões dos requisitos que este design obedece

| Decisão | Consequência no design |
|---|---|
| Pendência = falta tag, conteúdo ou tipo; conteúdo só conta para produto vendido por UN | Query nova em `repositories/products.py` (§2), não um filtro em Python |
| Categoria aplica a mais provável, sem perguntar | `auto_tag`/`tag_is_known` somem do domínio (§3); o laço de pergunta de categoria é **removido** |
| Intuição de varejo alimenta a pergunta e nunca grava | Chamada de IA **separada**, com versão e validador próprios (§4); o resultado nunca chega a `curation.apply` sem uma tecla |
| O gatilho da pergunta é a recusa da IA, não um score | Nenhuma constante nova, nenhum corte a calibrar (§5) |
| Pulado volta na próxima rodada | Nenhum estado novo; a pendência é derivada do próprio dado (§2) |
| Coluna distingue "já resolvido" de "sem resposta" | Valor atual em `dim`; célula vazia passa a significar uma coisa só (§6) |

## 1. As oito questões em aberto, fechadas

| # | Questão (requisitos §4/§7) | Decisão | Onde |
|---|---|---|---|
| 1 | O que sobra de `--sim` e do modo interativo? | `--sim` é redefinido como "não perguntar nada"; o modo interativo sobrevive, mas só para conteúdo | §7 |
| 2 | A coluna "Categoria" ainda precisa do prefixo `?` | Não. Mostra a categoria aplicada; as alternativas descartadas saem em `dim` ao lado | §6 |
| 3 | Pendência por tipo tem o mesmo problema dos nulos legítimos? | Sem tratamento especial: tipo nulo mantém o produto pendente e ele reaparece, como conteúdo | §2 |
| 4 | Mandar ao prompt só os campos faltantes? | Não. A passada inteira custa US$ 0,02; a economia não paga a complexidade | §4.3 |
| 5 | Confirmar que o caso dos Ovos se conserta sozinho | Vira critério de aceite do ticket 136, não decisão de design | §10 |
| 6 | Uma chamada ou duas? | **Duas.** A recusa honesta é o ativo mais valioso e não pode ser contaminada | §4.1 |
| 7 | Como rotular o candidato na pergunta | A CLI traduz `form` para uma palavra fixa; **nenhum texto livre da IA vai para a tela** | §5.2 |
| 8 | Produto-UN cuja `form` a IA diz ser "peso" | Pergunta mesmo assim, **sem candidatos** — é exatamente onde a intuição produziu lixo | §5.3 |

## 2. O critério de pendência (RF1)

`curation.pending_product_ids` deixa de ser `products.untagged_product_ids` e passa a `products.incomplete_product_ids`:

```sql
SELECT p.id FROM products p
WHERE p.kind IS NULL
   OR NOT EXISTS (SELECT 1 FROM product_tags WHERE product_id = p.id)
   OR (p.content_quantity IS NULL
       AND EXISTS (SELECT 1 FROM prices WHERE product_id = p.id AND unit = 'UN'))
ORDER BY p.id
```

Três coisas que a query codifica, e por que:

- **`unit = 'UN'` via `EXISTS`, não pela unidade "principal" do produto.** Um produto pode ter linhas em UN numa loja e KG noutra; basta uma linha em UN para o conteúdo passar a importar. A alternativa (unidade majoritária) inventaria um conceito que não existe no schema.
- **Produto vendido só por KG nunca é pendente por conteúdo** — R$/kg já é o preço por conteúdo, ramo 1 de `domain/comparison_basis.py`. São 26 dos 49 de hoje.
- **Produto sem nenhuma linha em `prices`** (só existiria por fusão malfeita) não é pendente por conteúdo, e continua pendente por tag/tipo se for o caso. Nenhum tratamento especial.

**A query mora no repositório, não no serviço**, pelo mesmo motivo de `untagged_product_ids`: é leitura de um agregado. `has_raw_name` já é precedente de query em `prices` dentro de `repositories/products.py`.

**`importar` não muda de escopo.** Ele continua revisando **só os produtos novos daquela nota** (`ImportResult.new_product_ids`). Puxar o catálogo incompleto inteiro a cada import tornaria o import lento e caro sem o usuário ter pedido; o comando dedicado para pôr em dia é `julius produtos revisar`. A dívida dos 49 se paga na primeira execução dele.

> `ponytail:` a query é uma varredura de `products` com dois subselects correlacionados, sobre 105 linhas. Índice só se o catálogo crescer ordens de magnitude.

## 3. Categoria: a primeira conhecida, sem perguntar (RF2)

### 3.1 O que sai

`ProductProposal.tag_is_known` e `ProductProposal.auto_tag` **deixam de existir**. Os dois só existiam para expressar "candidato único e conhecido → automático", regra que a medição derrubou (disparou 1 vez em 25). Com eles saem `_review._ask_tag` e o laço inteiro de pergunta de categoria.

### 3.2 O que entra — e um refinamento do RF2

`ProductProposal.tag: str | None` — **a primeira categoria candidata que já existe no vocabulário**, ou `None` quando nenhuma das candidatas existe.

Isto **estreita** o RF2, que dizia "a primeira sugestão". A razão é medida e não estava à vista quando o requisito foi escrito: o vocabulário de tags é a entrada da medição de `TAG_MATCH_CUTOFF = 75` da v2.1, calibrada contra as 13 tags semeadas com a garantia de que nenhuma pontua acima de 55 contra outra. Deixar a IA **criar** vocabulário sozinha coloca em risco uma constante já medida, num caminho onde ninguém está olhando. Aplicar uma tag existente não corre esse risco.

Custo real do refinamento: **zero na amostra** — a primeira candidata já pertencia ao vocabulário em 25 de 25 (F9). Quando um dia não pertencer, o produto fica pendente, reaparece, e o usuário resolve com `julius produtos tag ID novacategoria` (que cria a tag deliberadamente, com ele olhando). Nenhuma pergunta nova na tela.

Se o usuário preferir o RF2 na forma literal — aplicar a primeira candidata mesmo desconhecida —, é uma linha em `curation.propose` e a nota de `TAG_MATCH_CUTOFF` passa a carregar o risco. A escolha está registrada aqui para ser revertida com consciência, não por descuido.

## 4. A intuição de embalagem: uma segunda chamada (RF6)

### 4.1 Por que duas chamadas, e não campos novos no `enrich`

Os dois enquadramentos foram medidos no mesmo modelo, no mesmo dia:

| Prompt | Comportamento medido |
|---|---|
| Produção (`enrich`): "preencha `content` **só quando a descrição deixa inequívoco**" | Recusa corretamente: `null` certo em **6 de 6** |
| Sonda: "diga a **forma** e dê até 3 **candidatos**" | **Nunca** recusa: 9 de 9 com palpite, inclusive `500 KG` de bacon e `30 UN` de filme PVC |

A recusa honesta do primeiro é o único sinal de incerteza confiável que este projeto já mediu — depois de `confidence` (v2), número de tags (v2.3) e "o número veio do rótulo" (v2.3, §F16) falharem. Misturar no mesmo prompt a instrução "recuse quando não for inequívoco" com "dê candidatos plausíveis" pede ao modelo duas disposições opostas de uma vez e arrisca o ativo que funciona. **Separar é mais barato que medir de novo.**

Custo da separação: **US$ 0,0007 por rodada**, e só quando há o que perguntar (§4.2).

### 4.2 Quando a segunda chamada acontece

Só quando **todas** valerem:
1. a revisão é interativa (TTY e sem `--sim`) — sem ninguém para responder, candidatos são tokens jogados fora;
2. existe ao menos um produto **vendido por UN**, com conteúdo nulo, cuja proposta veio sem conteúdo;
3. a IA está disponível (`suggestions.is_available`) — o `_ask` já cuida do orçamento.

Falha ou indisponibilidade não interrompe nada: sem candidatos, a pergunta ainda acontece, só que sem opções numeradas (§5.3).

### 4.3 O prompt

`SYSTEM_PROMPTS["packaging"]`, `PROMPT_VERSIONS["packaging"] = "1"`. Chaves JSON em inglês, instruções em português, como os três prompts que já existem. Enum de `form` em inglês para casar com as chaves: `"unit"`, `"pack"`, `"weight"`, `"volume"`, `"unknown"`.

O conteúdo da instrução é o da sonda que foi medida (§F13–F18), sem "melhorias": pede a forma pelo **costume do varejo brasileiro**, até 3 candidatos com o mais provável primeiro, e lista vazia quando não houver palpite. **Não** pede auto-avaliação de certeza — o campo existia na sonda e foi medido inútil (F16); incluí-lo seria pagar tokens por um sinal já reprovado três vezes.

`max_tokens`: `70 * len(batch) + 200`. A resposta da sonda gastou 509 tokens para 9 produtos.

Mandar o produto inteiro (nome legível atual) e não só os campos faltantes: decisão 4 da tabela §1. A passada inteira custa centavos; economizar tokens aqui compraria complexidade de montagem de prompt por produto.

## 5. O laço de conteúdo (RF5)

### 5.1 Quem entra no laço

Proposta cujo **conteúdo veio nulo** e cujo produto é **vendido por UN**. A segunda condição precisa estar na proposta: `ProductProposal.sold_by_unit: bool`, preenchido por `curation.propose` a partir de uma leitura de repositório — a CLI não consulta banco direto.

Produto vendido por KG com conteúdo nulo **não entra**: nada a perguntar (§2).

### 5.2 A pergunta

Uma linha por produto, no formato que a tela de categoria já usava (`typer.prompt`, escolha por número, Enter pula):

```
31 · Brócolis Ninja — conteúdo  [1] 1 UN · unidade  [2] digitar  [Enter] pular:
55 · Prato Redondo Descartável 21cm — conteúdo  [1] 10 UN · pacote  [2] 20 UN · pacote  [3] digitar  [Enter] pular:
32 · Filme PVC Wyda 30m x 28cm — conteúdo  [1] 30 UN · unidade  [2] digitar  [Enter] pular:
```

- **Nenhum texto livre da IA aparece na tela** (questão 7). `form` é traduzido por um dicionário fixo em `cli/_review.py`: `unit → "unidade"`, `pack → "pacote"`, `volume → "volume"`, `weight → "peso"`, `unknown → ""`. É a mesma disciplina de `cli/_hints.py`: o serviço devolve dado, a CLI escolhe a palavra.
- `digitar` abre um segundo prompt e aceita a mesma sintaxe do comando manual (`500 G`, `1.5 L`, `30 UN`), reaproveitando `normalize_content` — o mesmo caminho de `julius produtos definir-conteudo`, para não existirem duas gramáticas de conteúdo.
- Entrada inválida (letra solta, número fora da faixa, unidade desconhecida): imprime o erro e **trata como pular**. Não insiste, não repete a pergunta — a rodada seguinte oferece de novo.
- O terceiro exemplo é o Filme PVC: a opção errada aparece, e pular é a resposta certa. Isso é o desenho funcionando, não uma falha.

### 5.3 Quando não há candidatos

Sem candidatos (IA indisponível, lista vazia, ou `form` em `weight`/`unknown` — questão 8), a pergunta sai sem opções numeradas:

```
34 · Bacon Excelência tablete — conteúdo  [1] digitar  [Enter] pular:
```

Suprimir os candidatos de `weight` é o que mantém `500 KG` de bacon fora da tela: foi exatamente aí que a sonda produziu lixo (F18). O humano continua com caminho para responder, e o filtro de §2 já tira da fila a maioria desses casos antes da pergunta existir.

### 5.4 Como a escolha é gravada

Pelo caminho que já existe, para a ação entrar no log com desfazer:

```python
curation.apply(conn, replace(proposal, readable_name=None, content=chosen), tag=None, content=True, kind=False)
```

É o mesmo padrão que o laço de conteúdo da v2 usava antes de ser removido no ticket 122. `AppliedAction(field="content")` sai de lá e vira linha em `actions.jsonl` com `julius produtos definir-conteudo <id> --remover` como desfazer — igual ao conteúdo automático. Do ponto de vista da auditoria, não há diferença entre o que a IA gravou e o que o humano escolheu, e isso é proposital: o que importa no log é o que mudou e como voltar.

## 6. A tabela de revisão (RF3)

| Coluna | Hoje | Depois |
|---|---|---|
| Cupom | `product.canonical_name` — vira o nome renomeado depois da primeira rodada | descrição real do cupom (`prices.description` mais recente) |
| Nome | proposta ou nome atual | inalterado |
| Categoria | `auto_tag` ou `"? a, b"` | a categoria que **vai ser aplicada**; candidatas descartadas em `dim` ao lado (questão 2) |
| Tipo | proposta ou vazio | proposta; **valor atual em `dim`** quando não há proposta |
| Conteúdo | proposta ou vazio | proposta; **valor atual em `dim`** quando não há proposta |

Célula vazia passa a ter um significado só: **a IA não respondeu e o produto não tem o dado**. É o que transforma a tabela numa leitura honesta do estado, e era a causa da confusão que abriu este ciclo.

A descrição do cupom vem de `products.receipt_descriptions(conn, product_ids) -> dict[int, str]` — uma query para o lote todo, não uma por produto.

## 7. `--sim` e o que sobra do modo interativo (questão 1)

| Situação | Categoria/nome/tipo/conteúdo do rótulo | Conteúdo recusado pela IA |
|---|---|---|
| TTY, sem `--sim` | aplica | **pergunta** |
| TTY, com `--sim` | aplica | não pergunta; fica pendente |
| Sem TTY | aplica | não pergunta; fica pendente |

`--sim` passa a significar **"não me pergunte nada"**, e não mais "aceite as sugestões". O nome fica impreciso, e mesmo assim é mantido: renomear para `--sem-perguntas` quebraria o hábito de um usuário para ganhar exatidão num texto de `--help` que pode explicar a mesma coisa em uma linha. O `--help` passa a dizer: *"Não perguntar nada; conteúdo que a IA não soube fica pendente para a próxima revisão."*

`_review._is_interactive` **permanece** (é o que `tests/test_cli_review.py` monkeypatcha). `_ask_tag` sai. `_confirm_pt`, removido no ticket 122, continua fora.

## 8. Contratos por módulo

### 8.1 `julius/domain/models.py`

```python
PackagingForm = Literal["unit", "pack", "weight", "volume", "unknown"]

@dataclass(frozen=True)
class PackagingHint:
    form: PackagingForm
    candidates: tuple[ContentSuggestion, ...]   # best first, at most 3; empty when the model had none

@dataclass(frozen=True)
class ProductProposal:
    product_id: int
    current_name: str
    receipt_description: str      # NEW: what the coupon actually said
    readable_name: str | None
    tags: tuple[str, ...]
    tag: str | None               # NEW: first candidate that already exists; replaces auto_tag/tag_is_known
    content: ContentSuggestion | None
    kind: str | None
    sold_by_unit: bool            # NEW: whether content is worth asking about
```

`tag_is_known` e a property `auto_tag` **saem**.

### 8.2 `julius/repositories/products.py`

```python
def incomplete_product_ids(conn) -> list[int]          # NEW: §2; substitui untagged_product_ids no uso
def sold_by_unit_ids(conn, product_ids) -> set[int]    # NEW: ids com ao menos uma linha em UN
def receipt_descriptions(conn, product_ids) -> dict[int, str]  # NEW: descrição mais recente por produto
```

`untagged_product_ids` **permanece** (é API do repositório e tem teste próprio); só deixa de ser o que `curation` chama.

### 8.3 `julius/services/suggestions.py`

```python
def suggest_packaging(conn, config, client, products, month=None) -> dict[int, PackagingHint]
```

Mesma forma de `enrich_products`: lotes, nunca lança, lote que falha perde só aquele lote. Validação por item: `form` fora do enum → `"unknown"`; cada candidato passa por `_valid_content` (que já existe) e os inválidos são descartados individualmente; item sem candidato válido vira `PackagingHint(form, ())`.

**Nenhum limite numérico de sanidade** nos candidatos (`500 KG` de bacon é formalmente válido). O que mantém isso fora da tela é a supressão por `form == "weight"` (§5.3) e o filtro de pendência (§2) — um corte arbitrário seria uma constante nova sem medição que a sustente.

### 8.4 `julius/services/curation.py`

```python
def pending_product_ids(conn) -> list[int]   # passa a chamar products.incomplete_product_ids
def propose(...) -> list[ProductProposal]    # preenche receipt_description, tag, sold_by_unit
```

`apply` **não muda de assinatura**: já aceita `content=True` com qualquer `ContentSuggestion` na proposta, que é o que o laço do §5.4 usa.

### 8.5 `julius/cli/_review.py`

- `_table`: colunas de §6, com `dim` no valor atual.
- `_ask_content(proposal, hint) -> ContentSuggestion | None`: a pergunta de §5.2.
- `_FORM_LABELS: dict[PackagingForm, str]`: a tradução de §5.2.
- `review_products`: passada automática (nome, tag, tipo, conteúdo do rótulo) → log → resumo → **laço de conteúdo** → duplicatas → pendentes.
- O laço de categoria e `_ask_tag` saem.

A ordem importa: o resumo agregado sai **antes** do laço de conteúdo, para o usuário saber o que já foi feito antes de começar a responder. As respostas do laço entram no log à medida que acontecem e **não** re-imprimem o resumo.

## 9. O que muda de comportamento, e o que os testes atuais dizem

| Teste | Situação | O que acontece |
|---|---|---|
| `test_revisar_prompts_for_ambiguous_tag_and_applies_choice` | espera pergunta de categoria | **Obsoleto.** Vira "aplica a primeira conhecida sem perguntar" |
| `test_revisar_other_option_creates_new_tag` | a opção "outra" | **Obsoleto.** Não há mais opção "outra"; criar tag é `julius produtos tag` |
| `test_revisar_enter_skips_and_reports_pending` | Enter pula categoria | **Reescrito** para conteúdo: Enter pula, produto fica pendente |
| `test_revisar_sim_applies_first_tag_even_if_unknown` | `--sim` aplica tag desconhecida | **Muda de propósito** (§3.2): tag desconhecida não é aplicada; o teste passa a provar que ela **não** é |
| `test_revisar_summary_omits_zero_counts` | proposta com 2 tags, espera só nome no resumo | **Ajuste de expectativa**: agora uma categoria também é aplicada |
| `test_revisar_non_interactive_without_sim_applies_only_auto_...` | sem TTY | **Ajuste**: categoria passa a ser aplicada; conteúdo recusado fica pendente |
| `test_propose_two_tags_or_unknown_tag_is_not_auto` (curation) | `auto_tag`/`tag_is_known` | **Obsoleto.** Substituído por testes de `ProductProposal.tag` |
| `test_revisar_applies_content_without_asking` | conteúdo do rótulo aplicado sem pergunta | **Continua passando sem edição** — é a garantia de que o HITL novo não reintroduziu confirmação onde ela já tinha sido revertida |
| `test_revisar_applies_kind_automatically`, `test_revisar_logs_one_line_per_action`, `test_undo_command_per_field`, todos os de `--ultimas-acoes` | — | **Continuam passando sem edição** |

Se algum da última linha precisar mudar, o desenho está errado, não o teste.

**Fixture novo:** nenhum. Os casos do laço de conteúdo se montam com `ScriptedLlmClient` e `by_kind`, que já suporta um quarto tipo de chamada desde que o marcador do prompt seja distinto — `"packaging"` precisa entrar em `_KIND_MARKERS` (`tests/_fakes.py`), com uma chave própria no JSON de resposta (`"packaging"`), pelo mesmo mecanismo dos três atuais.

## 10. Tickets propostos (131–136)

| # | Ticket | Depende de | Esforço | Entrega |
|---|---|---|---|---|
| 131 | Repositório: pendência por campo faltando | — | S | `incomplete_product_ids`, `sold_by_unit_ids`, `receipt_descriptions` |
| 132 | `curation`: proposta completa, sem `auto_tag` | 131 | M | `ProductProposal.tag`/`receipt_description`/`sold_by_unit`; `pending_product_ids` novo; remove `tag_is_known`/`auto_tag` |
| 133 | `suggestions.suggest_packaging` | — | M | `PackagingHint`, `PackagingForm`, prompt `packaging` v1, validador, `_KIND_MARKERS` |
| 134 | `_review`: tabela honesta e categoria automática | 132 | M | colunas de §6, passada automática com `proposal.tag`, remove `_ask_tag` |
| 135 | `_review`: o laço de conteúdo | 133, 134 | M | `_ask_content`, `_FORM_LABELS`, `--sim` redefinido, pendentes por conteúdo |
| 136 | e2e + docs + rodada real | 131–135 | M | `test_e2e` do ciclo, `CLAUDE.md`/`README.md`, execução contra cópia do banco real |

```
131 ──► 132 ──► 134 ──┐
                       ├──► 135 ──► 136
133 ───────────────────┘
```

Paralelizável desde o início: **{131, 133}**. 133 não depende de nada — é uma chamada de IA nova, isolada, que ninguém consome até o 135.

**Restrição de ordem que é de princípio, não técnica:** 134 antes de 135. O 134 tira a pergunta de categoria; o 135 põe a pergunta de conteúdo. Invertidos, existe um estado intermediário em que a revisão pergunta **as duas coisas** — mais atrito do que hoje, que é exatamente o problema que este ciclo existe para resolver.

## 11. Riscos

- **A segunda chamada vira hábito de chutar também no `enrich`.** Mitigação: prompts, versões e validadores separados; `PROMPT_VERSIONS["enrich"]` não muda, e o teste que prova o `null` honesto continua verde.
- **Conteúdo escolhido pelo humano fica indistinguível do automático no log.** É proposital (§5.4), mas significa que uma auditoria futura não consegue medir a taxa de acerto da IA em conteúdo. Se isso incomodar, o campo entra no registro do log sem mudar o domínio.
- **Vocabulário de tags para de crescer sozinho** (§3.2). Efeito colateral desejado, mas se o usuário comprar num mercado de categoria realmente nova, ele precisa criar a tag à mão uma vez. Visível: o produto fica pendente e reaparece.
- **Pergunta de conteúdo no meio do `importar`.** Com TTY, importar uma nota com muitos produtos novos pode gerar várias perguntas seguidas. Limite deliberadamente **não** imposto: a alternativa é o produto ficar sem conteúdo, que é a dívida que este ciclo está pagando. Se incomodar, `--sim` já é a saída.
- **`incomplete_product_ids` inclui produto que a IA nunca vai completar** (Sacola, Espátula). Aceito nos requisitos §2; o custo é uma linha na tabela por rodada.

## 12. O que este design decidiu não fazer

- **Campos de intuição dentro do prompt `enrich`** (§4.1) — separar é mais barato que arriscar a recusa confiável.
- **Pedir ao modelo qualquer forma de auto-avaliação de certeza** — reprovado três vezes por medição.
- **Limite de sanidade nos candidatos de conteúdo** (§8.3) — seria uma constante nova sem medição; a supressão por `form` resolve o caso observado.
- **Marcar "não tem conteúdo"** em qualquer forma, inclusive como efeito de pular — recusado duas vezes nos requisitos.
- **`importar` revisar o catálogo incompleto inteiro** (§2) — import tem que continuar rápido e previsível.
- **Insistir na pergunta após entrada inválida** (§5.2) — a rodada seguinte oferece de novo; um laço que insiste é um laço que prende.
- **Renomear `--sim`** (§7).
