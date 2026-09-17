# Julius v2.4 — fusão reversível e a leitura por unidade base: design

> `/sc:design` de 2026-09-17, a partir de `docs/requirements/auto-merge-and-unit-price-v2.4.md` (F1–F18, RF1a–RF1o, RF2–RF12, as 11 questões fechadas na §5). Especificação para os tickets 137+. **Nenhum código foi alterado.**
> Tudo que este documento afirma sobre SQLite foi executado contra uma cópia do banco real; os números estão em §2.3 e §8.

## 0. O que os requisitos já decidiram e este design obedece

| Decisão | Consequência no design |
|---|---|
| Fundir não apaga nem move linha nenhuma (RF1a) | `prices.product_id` e `product_skus.product_id` **nunca** são reatribuídos; a fusão é uma coluna (§1) |
| Desfazer remove a relação, não reconstrói (RF1b) | Nenhum estado de reversão a guardar; o desfazer é um `UPDATE ... SET merged_into = NULL` (§4.3) |
| A relação guarda o alvo direto e resolve até a raiz (RF1g) | Resolução recursiva numa view, não `COALESCE` espalhado (§2) |
| Fundir nunca perde informação (RF1i–RF1n) | Os atributos do grupo são **derivados na leitura**, não gravados (§3) — e isso torna o RF1n verdadeiro por construção |
| Conteúdo divergente bloqueia a fusão automática (RF1l) | Guarda em `curation`, antes de a IA ser chamada (§5) |
| O gatilho é o veredito da IA, sem limiar (RF2) | Nenhuma constante nova em todo este design |
| O sobrevivente é o de menor id (Q1) | Regra em `catalog`, não escolha da IA |

## 1. Schema — migração 0004, uma coluna e uma view

```sql
-- A fusão passa a ser um estado reversível em vez de uma transformação destrutiva: o produto
-- absorvido continua existindo, com seus próprios nome, tipo, conteúdo e tags. Guarda o alvo
-- DIRETO (não a raiz): é isso que faz desfundir devolver o estado exatamente anterior quando há
-- mais de um nível.
ALTER TABLE products ADD COLUMN merged_into INTEGER REFERENCES products(id);

-- Um produto por linha, sempre, apontando para a raiz do seu grupo. Produto não fundido é raiz
-- de si mesmo, então toda leitura pode dar JOIN nesta view sem tratar caso especial.
CREATE VIEW product_group AS
WITH RECURSIVE walk(product_id, current_id) AS (
    SELECT id, id FROM products
    UNION ALL
    SELECT w.product_id, p.merged_into FROM walk w JOIN products p ON p.id = w.current_id
     WHERE p.merged_into IS NOT NULL
)
SELECT w.product_id, w.current_id AS root_id
  FROM walk w JOIN products p ON p.id = w.current_id
 WHERE p.merged_into IS NULL;
```

Sem índice: são 105 linhas e a resolução custa 0,035 ms (§2.3). Sem `CHECK` impedindo `merged_into = id`: a guarda de ciclo é na escrita (§4.2), porque um `CHECK` de coluna não vê ciclo de dois passos.

**A view é DDL, então vive na migração** — mesma regra que já vale para tabelas (`julius/infra/migrations/*.sql`, nenhuma DDL em string dentro de código Python).

## 2. Resolver o grupo

### 2.1 Onde

Nas **26 queries dos dois repositórios** (F12: 21 em `repositories/products.py`, 5 em `repositories/prices.py`; nenhum SQL cru em `services/` ou `cli/`). Serviços e CLI continuam falando em "product_id" e não sabem que existe grupo — o que eles recebem já é o grupo.

Três formas de a resolução aparecer:

| Situação | Forma |
|---|---|
| Ler preços de um conjunto de ids (`prices_for_products`) | `JOIN product_group g ON g.product_id = p.product_id WHERE g.root_id IN (...)` — pega os preços de todos os membros |
| Listar/buscar produtos (`list_products`, `product_names`, `catalog_for_matching`, `incomplete_product_ids`) | `WHERE merged_into IS NULL` — só raízes aparecem (RF1d) |
| Ler um produto (`get_product`) | resolve o id para a raiz e devolve o **produto efetivo** do grupo (§3) |

### 2.2 O `product_id` que sai nos `PriceRecord` é o da raiz

`prices_for_products` passa a devolver `g.root_id` como `PriceRecord.product_id`, e o `canonical_name` do produto efetivo do grupo. Duas razões, nenhuma cosmética:

1. **RF1c** — o grupo se apresenta com um nome só.
2. `domain/comparison_basis.py` decide "série temporal × comparação entre embalagens" por `len({record.product_id})`. Se os preços saíssem com o id de origem, dois preços do mesmo produto (fundido) seriam lidos como produtos diferentes e a base viraria `price_per_content` — exatamente o erro que a v2.2 consertou. Resolver para a raiz mantém `comparison_basis` **sem nenhuma alteração**.

A origem não se perde: `prices.product_id` continua gravado e `PriceRecord` ganha `source_product_id`, usado só pelo `exportar` (Q10).

### 2.3 Medido, não suposto

Executado contra uma cópia do banco real (105 produtos, 132 preços), com uma cadeia de três níveis montada à mão (80 → 33 → 5):

| Verificação | Resultado |
|---|---|
| Cadeia de 3 níveis | `(5,5) (33,5) (80,5)` — os três resolvem para a raiz |
| A view não duplica nem perde linha | 105 linhas para 105 produtos |
| Preços do grupo sem reatribuir nada | a raiz 5 junta os preços de `5, 33, 80` |
| Desfundir o nível do meio (33) | 80 volta a apontar para **33**, não fica pendurado em 5 — o estado anterior de verdade |
| Custo | 200 resoluções em **7 ms** (0,035 ms cada) |
| **Ciclo (33→80 e 80→33)** | **a consulta não retorna** — travou até `kill`. Ver §4.2 |

## 3. Os atributos do grupo são derivados, não gravados

O requisito (RF1k) pedia "herança registrada como ação e reversível". **Este design entrega algo mais forte e com menos código: a herança não é uma gravação, é uma regra de leitura.** `products.get_product(root_id)` devolve um `Product` cujos campos são compostos do grupo:

| Campo | Regra | Vem de |
|---|---|---|
| `canonical_name` | o primeiro nome **não-cru** do grupo (raiz primeiro, depois os absorvidos por id); todos crus → o da raiz | RF1j, e `has_raw_name` já existe |
| `content_quantity`/`content_unit` | o da raiz; nulo na raiz → o primeiro não-nulo entre os absorvidos | RF1k |
| `kind` | idem | RF1k / RF1m |
| `tags` | união, ordenada | RF1i |

Consequências de fazer assim, em vez de gravar a herança:

- **RF1n sai de graça.** Desfundir devolve o estado anterior porque nada foi copiado para lugar nenhum — não existe "cópia órfã" a limpar. Era o requisito mais chato de cumprir e virou zero código.
- **Nenhuma `AppliedAction` de herança.** Herança derivada não é gravação, então não há o que registrar nem o que desfazer. O que o RF1k realmente protege (o caso `Alho` herdando 400 g do `Pão de Alho`, F17) é coberto pela **notificação** da fusão (§4.4), que continua obrigatória. Desvio consciente do texto do requisito, registrado aqui.
- **Nada precisa reprocessar nada.** Corrigir o conteúdo do absorvido muda o do grupo na próxima leitura.

Quem escreve continua escrevendo na raiz: `produtos tipo 33 tomate` grava em 33. Escrever num produto absorvido é possível e inofensivo (fica inerte enquanto ele estiver fundido, e volta a valer se for desfundido) — mas os comandos recebem o id que as listagens mostram, e as listagens mostram só raízes.

## 4. A fusão

### 4.1 `catalog.merge_products(conn, source_id, target_id)` — reescrita

```
antes: reassign_skus + reassign_product + copia tags + copia conteúdo + DELETE
depois: valida (§4.2) e grava products.merged_into = target_id em source_id. Uma linha.
```

Tudo o que ela copiava à mão (tags, conteúdo) virou §3. O `DELETE` desaparece — com ele desaparece a única operação destrutiva da curadoria.

### 4.2 Validação, e a guarda de ciclo que a medição exigiu

Por ordem, antes de gravar:

1. `source_id != target_id`;
2. os dois produtos existem;
3. **`target_id` não pertence ao grupo de `source_id`** — é a guarda de ciclo. Resolver a raiz de `target_id` e recusar se ela for `source_id` (ou se `target_id == source_id`). Sem ela, `A→B` seguido de `B→A` deixa a view em loop infinito e **todo comando que lê produto para de responder** (§2.3). Erro claro, nada gravado.

Não há guarda de profundidade: a cadeia é finita por construção assim que o ciclo é impossível.

### 4.3 `catalog.unmerge_product(conn, product_id)` — novo

`UPDATE products SET merged_into = NULL WHERE id = ?`, com `LookupError` se o produto não existe e erro claro se ele não está fundido. Os filhos dele (se houver) continuam apontando para ele, que volta a ser raiz — o estado anterior, medido em §2.3.

### 4.4 A fusão automática, em `cli/_review.py`

Onde hoje `review_products` imprime os comandos `fundir`, passa a fundir. Ordem dentro da função (a atual, com o bloco de duplicatas trocado):

```
propor → tabela → passada automática → log → resumo → laço de conteúdo → FUNDIR → pendentes
```

Por cada par que a IA confirmou (`judge_duplicates`, que já filtra `same_product`) e que passou o guarda de conteúdo (§5):

1. `catalog.merge_products(absorvido, sobrevivente)`, com **sobrevivente = menor id** (Q1);
2. uma `AppliedAction` de campo novo `"merge"`, com `before = None` e `after = str(absorvido)`, que `_log_actions` grava em `actions.jsonl` como qualquer outra;
3. `_undo_command` devolve `julius produtos desfundir <absorvido>` (Q11);
4. a notificação, que é requisito (RF4) e não cortesia:

```
Fundidos automaticamente (confira):
  33 ← 80  Banana prata ≈ Banana Prata Extra União — mesma variedade; Extra União é marca/fornecedor
           o grupo herdou o conteúdo 0,4 KG do produto 80
           desfazer: julius produtos desfundir 80
```

A linha de herança (F17) só aparece quando o grupo passou a ter um valor que a raiz não tinha — é a única parte do §3 que precisa ser dita em voz alta, porque um conteúdo herdado errado é invisível na saída normal.

`importar` roda a mesma função e ganha o comportamento junto (Q2), sem código próprio.

### 4.5 `julius produtos fundir` e `desfundir` (CLI)

- `fundir ORIGEM DESTINO` continua existindo e agora chama a mesma coisa. **O aviso de "irreversível" sai** do `--help`, das mensagens e do `README` (RF1h) — e com ele a justificativa da confirmação; ela passa a ser dispensável, então `--sim` no `fundir` perde a razão de existir. Divergência de conteúdo no par: avisa e funde (é o usuário mandando), sem mesclar conteúdo — que é automático pelo §3, já que o conteúdo da raiz ganha.
- `desfundir ID` novo, recebendo o id do **absorvido**.

## 5. O guarda de conteúdo divergente

Em `curation.duplicate_candidates`, que já é o filtro determinístico antes da IA:

1. **produtos absorvidos saem do universo** (`merged_into IS NOT NULL`) — senão o sistema propõe fundir o que já está fundido;
2. **par com conteúdo declarado em ambos os lados e diferente é descartado** antes de virar candidato (RF1l). Não é "descartado depois do veredito": economiza a chamada e deixa o guarda visível numa função determinística e testável.

Medição que sustenta (F16): dos 19 pares do catálogo real, 4 divergem e os 4 são falsos positivos — `Água 500ml ≈ Água 1,5L`, `Pepsi 2L ≈ Guaraná 1,5L`, `Água s/gás ≈ c/gás 1,5L`, `Pão Zinho 300g ≈ Pão de queijo 800g`. Os 12 de conteúdo igual incluem os dois acertos.

Comparação entre unidades diferentes (`0,5 L` vs `0,5 KG`) conta como divergência: são dimensões que o sistema nunca compara (Q7).

## 6. Frente B — a leitura por unidade base

Nenhum cálculo muda (F7). As três mudanças são de apresentação, e duas delas cabem em `services/search.py`.

### 6.1 Colapso de linhas idênticas (RF9)

Em `records_for_products`, **antes** de `_highlight_and_trim`: registros com o mesmo `(product_id, purchased_at, store_nickname, unit_price)` viram um. Tem de ser antes, senão o highlight e o `--limite` contam linhas que são a mesma informação.

Por que a chave é essa: o que duplica é item repetido na mesma nota (a pegadinha documentada desde a v1) e o mesmo preço em notas diferentes do mesmo dia. Sem contagem "2×" (Q4).

### 6.2 A ordem segue a base (RF10, Q5)

`_highlight_and_trim` já computa `basis, participants = comparison_basis(group)`. A ordenação passa a depender disso:

- `basis == "price_per_content"` → ordena por `price_per_content` crescente (a pergunta é "qual embalagem compensa");
- caso contrário → `purchased_at` decrescente, como hoje (a pergunta é "o preço subiu?").

Zero flag, zero constante: a distinção já existe em `comparison_basis` desde a v2.2, e a ordem passa a concordar com o destaque em vez de contradizê-lo.

Efeito colateral bom: o `--limite` passa a cortar as embalagens mais caras em vez das compras mais antigas, no grupo onde a comparação é por conteúdo.

### 6.3 A linha de resposta (RF11, Q6)

Em `cli/receipts.py`, depois da tabela, **só** quando `comparison_basis` daquele grupo devolveu `price_per_content` e há ao menos duas linhas participantes. A CLI já pode chamar `comparison_basis` (a DAG permite `cli → domain`), então nenhum contrato de serviço muda.

```
Mais barato por litro: Água mineral Indaiá 1,5L a R$ 2,46/L — a Água Crystal sem gás 500ml sai a R$ 2,98/L.
```

O texto nomeia o mais barato e o mais caro **do que foi comprado**, sem adjetivo de barato/caro e sem tendência (RF12). Base é o `highlight` que já está nos records: nenhum cálculo novo.

## 7. Contratos por módulo

### 7.1 `julius/infra/migrations/0004_product_merge.sql`
A coluna e a view do §1.

### 7.2 `julius/repositories/products.py`
```python
def set_merged_into(conn, product_id: int, target_id: int | None) -> None   # NEW: grava/limpa a relação
def group_root(conn, product_id: int) -> int                               # NEW: a raiz do grupo (via view)
def group_members(conn, root_id: int) -> list[int]                         # NEW: raiz + absorvidos, ordenados
def get_product(conn, product_id) -> Product | None   # resolve a raiz e devolve o produto EFETIVO (§3)
def list_products(conn) -> list[Product]              # só raízes
def product_names(conn) -> list[tuple[int, str]]      # só raízes, com o nome efetivo
def incomplete_product_ids(conn) -> list[int]         # só raízes, e o conteúdo/tipo efetivos do grupo
```
def product_ids_with_tag(conn, tag_name) -> list[int]   # resolve para a raiz e deduplica
```
`untagged_product_ids`, `has_raw_name`, `sold_by_unit_ids`, `receipt_descriptions` passam a receber/devolver ids de raiz pelo mesmo `JOIN`.

`product_ids_with_tag` merece nota própria: como as tags do grupo são a união (§3), a tag que está só no produto absorvido tem de trazer a **raiz** — senão `consultar --tag limpeza` deixaria de achar um grupo que o `produtos listar` mostra como marcado.

**Três funções ficam órfãs e saem, com seus testes**: `products.reassign_skus`, `prices.reassign_product` e `products.delete_product`. Verificado: as três só têm um chamador cada, `merge_products`. Com elas sai a última linha de código do sistema capaz de apagar um produto.

### 7.3 `julius/repositories/prices.py`
```python
def prices_for_products(conn, product_ids) -> list[PriceRecord]   # ids são raízes; junta os preços do grupo
def export_rows(conn) -> list[dict]                               # + coluna group_product_id (Q10)
```
`reassign_product` **deixa de existir** — ninguém reatribui preço (ver a nota de órfãs em §7.2).

### 7.4 `julius/domain/models.py`
```python
AppliedAction.field: Literal["name", "tag", "content", "kind", "merge"]   # + "merge"
PriceRecord.source_product_id: int   # o produto da linha; product_id é a raiz do grupo
Product.merged_into: int | None      # só para quem precisa saber (CLI de desfundir)
```

### 7.5 `julius/services/catalog.py`
```python
def merge_products(conn, source_id, target_id) -> None   # reescrita: valida e grava a relação (§4.1/4.2)
def unmerge_product(conn, product_id) -> None            # NEW (§4.3)
def merge_inheritance(conn, source_id, target_id) -> tuple[str, str] | None  # NEW: o que o grupo passou a
    # ter e de onde, para a notificação de §4.4 (None quando nada foi herdado)
```

### 7.6 `julius/services/curation.py`
```python
def duplicate_candidates(conn, product_ids=None) -> list[tuple[Product, Product, float]]
    # + exclui absorvidos, + descarta par com conteúdo divergente (§5)
```

### 7.7 `julius/services/search.py`
```python
def records_for_products(conn, product_ids, limit) -> list[PriceRecord]   # + colapso (§6.1)
def _highlight_and_trim(group, limit)                                     # + ordem pela base (§6.2)
```

### 7.8 `julius/cli/`
- `_review.py`: funde em vez de imprimir (§4.4); `_undo_command` ganha `"merge"`; `_FIELD_LABELS` ganha `("merge", "fusão(ões)")`.
- `products.py`: `desfundir ID`; `fundir` sem o aviso de irreversível e sem confirmação.
- `receipts.py`: a linha de resposta (§6.3).

## 8. Riscos

| Risco | Mitigação |
|---|---|
| **Ciclo travando todo o sistema** — medido: a view não retorna e o comando pendura | §4.2, guarda na escrita, com teste dedicado. É o risco mais grave deste design e o único que não falha alto por si. |
| A resolução esquecida numa query nova, e um preço de grupo fundido some de uma leitura | A resolução vive em 2 arquivos (F12) e cada função pública deles tem teste; o e2e do ciclo cobre fundir → consultar → desfundir → consultar. |
| `comparison_basis` mudar de ramo por engano | §2.2: o `product_id` que sai já é a raiz, então o módulo não muda e seus testes atuais continuam valendo sem edição. |
| A IA confirmar um par errado que o guarda de conteúdo não pega (ambos sem conteúdo) | É o risco aceito do RF2, agora barato: desfundir é um comando e nada foi destruído. `Picanha ≈ Fraldinha` (ambos sem conteúdo, 0,82) é o par a observar — a IA o rejeita hoje. |
| Produto absorvido recebendo escrita por engano | Inofensivo por construção (§3): o valor fica inerte e volta a valer se for desfundido. |
| Alguém "consertar" o design reatribuindo `prices.product_id` na fusão, por parecer mais simples | `reassign_product` é removida no §7.3 justamente para o atalho não existir; o teste que prova que `prices.product_id` não muda depois de fundir é obrigatório. |
| Fusão automática no `importar` deixando o comando lento | Nenhuma chamada nova: `judge_duplicates` já roda ali hoje para imprimir as sugestões. |

## 9. Sequência de implementação

```
137 migração 0004 + repositório (coluna, view, set_merged_into, group_root, group_members)
138 produto efetivo do grupo (get_product/list_products/product_names/incomplete_*) ──┐
139 preços do grupo (prices_for_products, source_product_id, export group_product_id) ─┤
140 catalog: merge reescrita + unmerge + guarda de ciclo + merge_inheritance ──────────┴─► 141
141 CLI: desfundir, fundir sem aviso de irreversível, "merge" no log e no desfazer
142 curation: guarda de conteúdo divergente + excluir absorvidos
143 review: funde automaticamente e notifica (depende de 141 e 142)
144 search: colapso + ordem pela base          (independente de 137–143)
145 CLI: a linha de resposta por conteúdo      (depende de 144)
146 e2e + docs + rodada real
```

**Restrição de ordem que é de princípio:** 141 antes de 143 — o `desfundir` existe e está testado antes de qualquer fusão automática ser ligada (RF7, mesma regra que pôs o 118 antes do 122). E 140 antes de 141, porque a guarda de ciclo é o que impede o comando manual de pendurar o sistema.

{144, 145} são a frente B e não dependem de nada da frente A; podem ir primeiro se a leitura incomodar mais que a fusão manual.

## 10. O que este design decidiu, além dos requisitos

| Decisão | Razão |
|---|---|
| **A herança de atributos é leitura, não gravação** (§3) | Cumpre RF1i–RF1n com menos código e torna RF1n verdadeiro por construção. Desvia do texto do RF1k (que pedia herança registrada como ação); o que o RF1k protege continua, na notificação. |
| **Uma view com CTE recursiva**, em vez de `COALESCE` em 26 queries ou resolução em Python | Uma definição só, na migração onde DDL já mora; e `WHERE merged_into IS NULL` resolve sozinho os casos de listagem, sem tocar a view. |
| **`PriceRecord.product_id` passa a ser a raiz**, com a origem em `source_product_id` | Mantém `comparison_basis` intacto (§2.2) e preserva a verdade histórica para o CSV. |
| **`reassign_product`, `reassign_skus` e `delete_product` são removidas** | As três existiam só para `merge_products`. Impede o atalho destrutivo de voltar por parecer mais simples, e deixa o sistema sem nenhum caminho que apague um produto. |
| **O guarda de conteúdo divergente fica em `duplicate_candidates`**, antes da IA | Determinístico, testável e economiza a chamada; e deixa claro que é filtro de candidato, não segundo palpite sobre o veredito. |
| **A confirmação do `fundir` manual cai** | Ela existia porque a operação era irreversível (RF1h); mantê-la seria pedir confirmação para algo que se desfaz com um comando. |
