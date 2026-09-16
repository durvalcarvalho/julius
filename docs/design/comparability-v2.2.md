# Julius v2.2 — comparabilidade: design

> `/sc:design` de 2026-09-16, a partir de `docs/requirements/comparability-closure.md` (RF1–RF7 e as 18 perguntas fechadas em §5). Especificação para tickets 117–124; **nenhum código foi alterado**.
> Medições novas desta rodada estão em §1 e §2 — o resto reaproveita as medições já registradas no documento de requisitos.

## 0. Decisões do fechamento que este design obedece

| Decisão | Consequência no design |
|---|---|
| Agrupar sem fundir | `products.kind` (§2). `merge_products` não é tocado; `fundir` continua manual. Nenhuma infraestrutura de undo de merge. |
| Grupo e conteúdo aplicados automaticamente, reversíveis | O comando de desfazer precisa **existir antes** da automação — daí a ordem de tickets 118 → 121 (§7). |
| Resumo agregado, detalhe sob demanda | Log de ações em JSONL + `produtos revisar --ultimas-acoes` (§4.6). |
| Comparação entre mercados com `n` e período | `services/comparison.py::compare_stores` devolve sempre o intervalo de datas e os grupos que sustentam a conta (§4.7). |
| Dia da semana só como dado | Derivado na CLI a partir de `purchased_at`; nada no domínio, nada calculado (§4.9). |
| KG compara direto, UN exige conteúdo | É a regra de §1, o núcleo deste design. |

## 1. A regra de base de comparação (fecha RF7 e o achado KG/UN)

O `CLAUDE.md` tem como princípio fundador "nunca comparar ou fazer média entre preços de bases diferentes". Hoje `_highlight_and_trim` compara sempre `unit_price` dentro do grupo de mesma `unit` — o que **viola o próprio princípio** para itens vendidos por UN, porque aí `unit_price` é o preço da embalagem, e embalagens de tamanhos diferentes não são a mesma base. Medido no banco real: o grupo `Agua [UN]` marca hoje a garrafa de 500ml (R$ 1,49) como a mais barata, quando por litro ela é a **mais cara** (R$ 2,98/L contra R$ 2,46/L da de 1,5L).

A regra abaixo substitui a escolha da base. Cada ramo existe por um caso observado — nenhum é especulativo:

| Situação do grupo | Base | Caso real que obriga esse ramo |
|---|---|---|
| `unit == "KG"` | `unit_price` | `Cebola`, `Tomate`, `Banana`: R$/kg **já é** preço por conteúdo. Comparável entre produtos e lojas sem mais nada. |
| `unit == "UN"`, todas as linhas do **mesmo `product_id`** | `unit_price` | Mesma embalagem em datas diferentes — série temporal legítima. É o que `test_never_mixes_units_in_highlight` e `test_limit_keeps_newest_but_always_includes_extremes` já exigem hoje. |
| `unit == "UN"`, vários produtos, **todas** com `price_per_content` e `content_unit` único | `price_per_content` | `Agua [UN]` (conteúdo já definido nas duas lojas): inverte quem é o mais barato, corrigindo o erro atual. Também `Macarrao`, `Suco`. |
| `unit == "UN"`, vários produtos, conteúdo **parcial** | `price_per_content` **só no subconjunto** com conteúdo e `content_unit` único (se tiver ≥ 2 linhas); as demais linhas ficam com `highlight = None` | `Tempero [UN]` (8 de 13 com conteúdo): sachê de 5g e frasco de 70g só se comparam por grama; as 5 linhas sem conteúdo não participam. |
| idem, subconjunto com < 2 linhas | **nenhum** `highlight` no grupo | `Queijo [UN]` (1 de 4): não há duas linhas comparáveis: silêncio é a resposta honesta. |

Consequência que **não** é bug: enquanto o conteúdo de um produto-UN não estiver definido, ele deixa de receber marcação de mínimo/máximo em grupos heterogêneos. É exatamente o que RF7 pede, e é o que transforma "preencher conteúdo" na ação de maior valor do sistema (32 dos 79 produtos-UN sem conteúdo hoje).

Nota de implementação: a comparação de igualdade com o mínimo/máximo passa a ser feita sobre um valor **calculado** (`unit_price / content_quantity`). Duas linhas com os mesmos operandos produzem o mesmo float pelas mesmas operações, então a igualdade continua válida; linhas que só são "matematicamente iguais" por coincidência são preços genuinamente distintos. Mantém-se o padrão que o código já usa, sem tolerância epsilon.

## 2. Onde o grupo vive (fecha RF1)

**`ALTER TABLE products ADD COLUMN kind TEXT`** — uma coluna, anulável.

Por que não na tabela `tags`, que já existe e já é auto-aplicada:
- `tags` é muitos-para-muitos **por desenho** (um produto é `laticinios` e `frios`). O grupo de comparação é **um só** por produto — RF1. Na coluna, o invariante é do banco; na tabela de tags, seria disciplina de aplicação. É a mesma escolha de "constraint do banco em vez de código" que já justificou as FKs e a `CHECK (unit IN ...)`.
- `comparability-closure.md` §7: entrar ~75 nomes finos (`tomate`, `uva`, `leite uht`) no espaço de `tags` invalida a medição de `TAG_MATCH_CUTOFF = 75`, calibrada contra as 13 tags de corredor com a garantia de que nenhuma pontua acima de 55 contra outra. A coluna mantém a medição — e os tickets 115/116 — intactos.

Por que não uma tabela `kinds` com id: a lista é `SELECT DISTINCT kind`, renomear é um `UPDATE products SET kind=? WHERE kind=?`, e o catálogo tem 105 produtos. Tabela nova só pagaria custo de join.

**Grafia e fragmentação.** O risco real do agrupamento por nome é `tomate` / `Tomate` / `tomates` fragmentarem o grupo silenciosamente. Duas defesas, nenhuma nova:
1. Escrita normalizada para minúsculas, **mantendo acento** (o valor aparece na tabela de comparação, então `açaí` não deve virar `acai`). Na atribuição, `set_product_kind` compara o proposto contra os existentes via `normalize_text` (que já remove acento e caixa) e **reaproveita a grafia já existente** quando houver equivalente — o que elimina de graça toda variação de caixa e acento.
2. O prompt recebe a lista de tipos conhecidos e é instruído a preferi-los, exatamente a mecânica que fez as 13 tags semeadas "pegarem" em vez de proliferarem (§4.5).

Singular/plural fica fora dessas duas defesas. **Não** entra corte fuzzy novo agora: seria um terceiro cutoff a medir sem nenhuma evidência de que o problema existe. Detecção quando existir, sem código novo:

```sql
SELECT kind, count(*) FROM products WHERE kind IS NOT NULL GROUP BY kind ORDER BY kind;
```

Dois tipos vizinhos na ordem alfabética com contagens pequenas é a assinatura de fragmentação. Se aparecer, o `UPDATE` de uma linha resolve, e só então vale discutir snapping automático.

## 3. Visão geral do fluxo

```
julius importar [ARQUIVO...]            ← sem argumento: varre entrada/*.html   (ticket 124)
   │
   ├─ por arquivo: importing.import_receipt  (inalterado)
   │    └─ sucesso → receipt_files.archive(...) + descarta _files/             (ticket 124)
   │
   ├─ revisão dos produtos novos  (_review.review_products)                    (ticket 121)
   │    ├─ curation.propose → nome, categoria, conteúdo, TIPO
   │    ├─ aplica automático: nome · categoria · conteúdo · tipo
   │    ├─ grava cada aplicação em actions.jsonl (antes → depois → desfazer)
   │    └─ imprime RESUMO agregado ("Apliquei N conteúdos, M tipos")
   │
   ├─ sinal de extremos: comparison.new_extremes(conn, access_keys)            (ticket 123)
   │    └─ compara contra o GRUPO (kind+unit), base pela regra de §1
   │
   └─ dicas (guidance)  — inalterado

julius consultar <palavras>       → + coluna "Dia" · highlight pela regra §1    (117/119/123)
julius mercados comparar          → comparison.compare_stores                   (ticket 122)
julius produtos tipo ID TIPO [--remover]                                        (ticket 118)
julius produtos definir-conteudo ID [QTD UNIDADE] [--remover]                   (ticket 118)
julius produtos revisar [--ultimas-acoes]                                       (ticket 121)
```

`kind` **não** muda como `consultar` seleciona produtos: a seleção continua por `rapidfuzz` sobre `canonical_name` e por `--tag`. O grupo é consumido pela comparação entre mercados e pelo sinal de import. Isso preserva N4 do documento de requisitos anterior ("nenhuma mudança em `search_prices`") — a única mudança no caminho de leitura é a base do `highlight` (§1), que é correção de um erro medido, não feature nova.

## 4. Contratos por módulo

### 4.1 `julius/infra/migrations/0003_product_kind.sql` (novo)

```sql
-- Comparison group: "what kind of thing is this", so prices of the same kind can be compared
-- across stores. One column, not a table: a product belongs to at most one group, and a single
-- column makes that the database's rule instead of the application's.
ALTER TABLE products ADD COLUMN kind TEXT;
```

Sem índice (catálogo de centenas de linhas) e sem `CHECK` — não-vazio é garantido na escrita, como já é feito para `tags.name`. A migração é puro `ALTER TABLE ADD COLUMN`, que o SQLite faz sem reescrever a tabela; `apply_migrations` já faz o backup `.bak-v2` automático antes de rodar.

### 4.2 `julius/domain/models.py`

```python
@dataclass(frozen=True)
class Product:
    ...
    kind: str | None = None          # comparison group; NULL until assigned

@dataclass(frozen=True)
class PriceRecord:
    ...
    kind: str | None = None          # of the product this row belongs to

@dataclass(frozen=True)
class ProductEnrichment:
    readable_name: str
    tags: tuple[str, ...]
    content: ContentSuggestion | None
    kind: str | None                 # NEW

@dataclass(frozen=True)
class ProductProposal:
    ...
    kind: str | None                 # NEW; None => nothing to apply

@dataclass(frozen=True)
class StorePrice:
    store_nickname: str
    price: float
    purchased_at: str

@dataclass(frozen=True)
class KindComparison:
    kind: str
    unit: SaleUnit
    basis: Literal["unit_price", "price_per_content"]
    content_unit: ContentUnit | None            # set when basis is price_per_content
    entries: tuple[StorePrice, ...]             # one per store, cheapest first

@dataclass(frozen=True)
class StoreComparison:
    comparisons: tuple[KindComparison, ...]
    first_purchase: str
    last_purchase: str

@dataclass(frozen=True)
class PriceExtreme:
    product_name: str
    store_nickname: str
    unit: SaleUnit
    price: float                     # on the comparison basis
    highlight: Highlight             # "lowest" | "highest"
    previous_price: float
    previous_store: str
    previous_at: str
    scope: str                       # the kind, or the product name when kind is NULL
```

**Sem** dataclass de ranking por loja: a contagem "mais barato em X de Y" é derivável de `comparisons` com um `Counter` na CLI. Mesma decisão já registrada no ticket 115 ("não grave o que já é calculável").

**Sem** campo de dia da semana em `PriceRecord`: é derivado de `purchased_at` na renderização (§4.9).

### 4.3 `julius/repositories/products.py`

```python
def set_kind(conn, product_id: int, kind: str | None) -> None      # NEW; None clears
def all_kinds(conn) -> list[str]                                   # NEW; DISTINCT, ordered
def clear_content(conn, product_id: int) -> None                    # NEW; both columns to NULL
```
`_to_product` e `list_products` passam a selecionar `kind`. `set_kind` valida existência com `_require_exists`, como as irmãs.

**A normalização de grafia de §2 vive aqui, em `set_kind`, não na camada de serviço.** Motivo: existem dois caminhos de escrita — o comando manual (`catalog.set_product_kind`) e a aplicação automática (`curation.apply`, que grava direto pelos repositórios, como já faz para nome/tag/conteúdo) — e `services` não pode importar `services` na DAG. Se a regra morasse em `catalog`, o caminho automático a burlaria. No repositório, ela é inescapável: `set_kind` minúsculo o valor, procura em `all_kinds` um existente cujo `normalize_text` coincida e, achando, grava a grafia já existente. É o mesmo tipo de leitura-antes-de-escrita que `resolve_product_id` já faz neste arquivo.

### 4.4 `julius/repositories/prices.py`

`prices_for_products` passa a trazer `products.kind` no `SELECT` (o join com `products` já existe). Nenhuma query nova: `services/comparison.py` reaproveita essa função inteira, inclusive o `price_per_content` que ela já calcula.

> `ponytail:` a comparação entre mercados chama `prices_for_products` com todos os produtos que têm `kind` — varredura completa da tabela `prices` (132 linhas hoje). Se um dia o banco tiver dezenas de milhares de linhas, virar agregação em SQL é a evolução; não antes.

### 4.5 `julius/services/catalog.py`

```python
def set_product_kind(conn, product_id: int, kind: str) -> None
    # Validates non-blank and delegates: the spelling rule lives in products.set_kind (§4.3),
    # so the automatic path in curation.apply cannot bypass it.

def clear_product_kind(conn, product_id: int) -> None
def clear_product_content(conn, product_id: int) -> None
```

### 4.6 `julius/services/suggestions.py` — prompt de enriquecimento v2

`PROMPT_VERSIONS["enrich"]` vai de `"1"` para `"2"`. `enrich_products` ganha o parâmetro `known_kinds: Sequence[str]` e o `user_prompt` ganha a linha `tipos: [...]`, no mesmo formato da linha `categorias:` que já existe. O bullet novo no system prompt:

```
- "kind": o TIPO da coisa, em minúsculas, para comparar preço entre lojas. Deve ser
  específico o bastante para que dois produtos do mesmo tipo sejam alternativas de compra
  um do outro: "leite uht" e "leite condensado" são tipos DIFERENTES; "pão de forma",
  "pão de alho" e "pão de queijo" também. Marca, fornecedor, sabor e tamanho NÃO entram no
  tipo ("tomate", não "tomate italiano união"; "uva", não "uva green dreams"). Prefira um
  tipo da lista "tipos" quando servir.
```

A instrução de granularidade não é estética: os grupos `Leite [UN]` (leite UHT junto com leite condensado) e `Pao [UN]` (forma, alho e queijo juntos) foram medidos como inutilizáveis, e nenhum cálculo os salva — só o nome do tipo na granularidade certa. Já "marca/sabor/tamanho fora do tipo" é o que faz `uva branca` e `uva green dreams` caírem no mesmo grupo e aparecerem lado a lado (R$ 6,99 contra R$ 14,99 pela mesma bandeja de 500g), que é o resultado desejado — no nível de grupo, os dois **são** uva.

Exemplo a acrescentar na saída do prompt (itens 1 e 2 já existentes ganham o campo):

```json
{"id": 1, "readable_name": "Linguiça de frango resfriada Aurora", "tags": ["carnes"], "content": null, "kind": "linguiça"}
{"id": 2, "readable_name": "Refrigerante Antarctica Guaraná PET 1,5L", "tags": ["bebidas"], "content": {"quantity": 1.5, "unit": "L"}, "kind": "refrigerante"}
```

`_valid_enrich_item` (ou equivalente) trata `kind` como opcional: ausente, vazio ou não-string vira `None`. Invariante do módulo continua: nada lança.

### 4.7 `julius/services/curation.py`

`propose` passa `products.all_kinds(conn)` para `enrich_products` e preenche `ProductProposal.kind` **apenas quando o produto ainda não tem tipo** (`product.kind is None`) — mesma disciplina de `has_raw_name`, que impede a IA de sobrescrever escolha humana.

`apply` ganha os parâmetros para aplicar tipo e conteúdo, e passa a devolver o que aplicou, para o log de ações:

```python
def apply(conn, proposal, *, tag: str | None, content: bool, kind: bool) -> list[AppliedAction]
```

`AppliedAction` é a tupla `(field, before, after, undo_command)` — com `field` em `{"name", "tag", "content", "kind"}`. Quem grava o log é a CLI (§4.9), não o serviço: serviço devolve dado, não escreve arquivo nem imprime, como toda a camada.

### 4.8 `julius/services/comparison.py` (novo)

```python
def comparison_basis(records: Sequence[PriceRecord]) -> tuple[str, ContentUnit | None, set[int]]
    """Applies §1 to one same-unit group. Returns the basis, the content unit when the basis
    is price_per_content, and the indices of the records that participate in the comparison."""

def compare_stores(conn) -> StoreComparison
    """One KindComparison per (kind, unit) observed in at least 2 stores. A store's price for
    a group is the CHEAPEST it charged, with that observation's date — the price-shopping
    question is 'what would I pay there', so the cheapest available is the fair representative.
    Never averages, never produces a single index (RF5)."""

def new_extremes(conn, access_keys: Sequence[str]) -> list[PriceExtreme]
    """Items in the given receipts that set a new low or high. Scope: same kind + same unit
    when the product has a kind, else same product_id + same unit. Basis per §1. 'Previous'
    excludes every row from `access_keys`, so the comparison is never circular."""
```

`comparison_basis` é a única implementação da regra de §1 e é **compartilhada** com `search._highlight_and_trim` — a regra não pode existir em duas versões. Como `services` não importa `services` na tabela de dependências... verificar: a tabela permite `services → domain, config, infra, parsers, repositories`, não `services → services`. Então a regra vive em **`julius/domain/comparison_basis.py`** (domínio: função pura sobre `PriceRecord`, zero I/O) e é importada por `services/search.py` e `services/comparison.py`. Isso mantém a DAG que `tests/test_architecture.py` verifica.

### 4.9 `julius/config.py` e `julius/infra/receipt_files.py` (novo)

```python
# config.py
@property
def inbox_path(self) -> Path:        return self.db_path.parent / "entrada"
@property
def archive_path(self) -> Path:      return self.inbox_path / "importados"
@property
def action_log_path(self) -> Path:   return self.db_path.parent / "actions.jsonl"
```

```python
# infra/receipt_files.py
def archive(html_path: Path, destination_dir: Path, *, purchased_at: str, access_key: str) -> Path
    """Moves the HTML to <destination_dir>/<YYYY-MM-DD>_<access_key>.html and returns the new
    path. The date+key name is required, not cosmetic: the browser always saves as
    'qrcode.html', so a flat archive would collide on the second import."""

def discard_sidecar(html_path: Path) -> bool
    """Removes the '<stem>_files' directory next to the HTML, if it exists. Only ever touches a
    directory with that exact name, and only after the HTML is safely archived."""
```

`ImportResult` ganha `access_key: str` e `purchased_at: str`, sem os quais a CLI não sabe como nomear o arquivo arquivado sem reparsear o HTML.

### 4.10 `julius/cli/`

- **`produtos tipo ID TIPO [--remover]`** → `catalog.set_product_kind` / `clear_product_kind`. É o comando de desfazer de que a automação depende; existe **antes** dela (ticket 118 antes de 121).
- **`produtos definir-conteudo ID [QTD UNIDADE] [--remover]`** → `--remover` chama `clear_product_content`. Hoje não há como desfazer um conteúdo, o que impediria aplicar conteúdo automaticamente sem quebrar a condição (1) de `comparability-closure.md` §4.
- **`produtos listar`** ganha coluna "Tipo".
- **`produtos revisar [--ultimas-acoes]`** → com a flag, apenas lê o fim de `actions.jsonl` e imprime uma tabela (data · produto · campo · antes → depois · comando de desfazer). Não chama IA, não aplica nada.
- **`_review.review_products`** aplica nome, categoria, conteúdo e tipo; grava cada `AppliedAction` via `ai_log.append(settings.action_log_path, ...)`; e troca as linhas por item por **um resumo**: `Aplicado: N nome(s), M categoria(s), C conteúdo(s), T tipo(s). Desfazer ou auditar: julius produtos revisar --ultimas-acoes`. O bloco de conteúdo que hoje imprime uma linha `definir-conteudo` por produto deixa de existir — passa a ser aplicado.
- **`consultar`** ganha coluna "Dia" com o dia da semana abreviado (`seg`…`dom`) derivado de `purchased_at` na renderização. Nenhuma afirmação, nenhum cálculo (RF6).
- **`mercados comparar`** → `comparison.compare_stores`. Uma tabela por grupo (loja · preço · data), depois a contagem derivada ("mais barato em 3 de 3 grupos"), e sempre o rodapé com número de grupos e intervalo de datas. Sem grupos suficientes, mensagem explícita em vez de tabela vazia.
- **`importar`** → `files` vira opcional; sem argumento, varre `config.inbox_path` por `*.html` (mensagem explícita se a pasta não existir ou estiver vazia). Após cada arquivo importado com sucesso: `receipt_files.archive` e `discard_sidecar`. Após a revisão: imprime os `PriceExtreme` de `new_extremes`, no máximo 5 linhas, com `+N mais` quando passar.

Ordem obrigatória dentro de `importar`: importar → **revisar** (é onde o tipo é atribuído) → sinal de extremos. Invertida, o sinal roda com `kind IS NULL` em todo produto novo e cai sempre no escopo degradado (`product_id`), perdendo justamente a comparação entre lojas.

## 5. O que muda de comportamento, e o que os testes atuais dizem

Verifiquei os testes que hoje exercitam `highlight` contra a regra de §1:

| Teste | Situação | Resultado |
|---|---|---|
| `test_never_mixes_units_in_highlight` | grupo UN com 2 linhas do **mesmo** produto, sem conteúdo | **Passa** — ramo "mesmo `product_id` → `unit_price`". Este teste é a razão de esse ramo existir. |
| `test_limit_keeps_newest_but_always_includes_extremes` | 5 preços de um produto só, UN | **Passa** — mesmo ramo. |
| `test_eggs_bigger_pack_is_cheaper_per_unit` (e2e) | 2 produtos UN, conteúdo definido nos dois, unidade única | **Passa** — só afirma a coluna "Por UN". De brinde, o `highlight` passa a marcar a embalagem de 30 como a mais barata, que é exatamente a tese do teste. |
| `test_real_data_has_no_flip_between_total_and_per_liter` (e2e) | Pepsi 2L e Guaraná 1,5L, conteúdo nos dois | **Passa** — não afirma `highlight`. |
| `test_records_for_products_highlights_per_unit_and_trims_like_search_prices` | a revisar no ticket | Verificar no 119; se afirmar `highlight` em grupo UN multi-produto sem conteúdo, a expectativa muda **de propósito**. |

Testes novos que o ticket 119 deve trazer, um por ramo de §1: inversão por conteúdo (caso `Agua`), subconjunto parcial (caso `Tempero`, linhas sem conteúdo com `highlight is None`), subconjunto insuficiente (caso `Queijo`, nenhum `highlight`), e KG multi-produto (comparável direto).

Fixture sintético novo: só o caso "novo máximo" do sinal de import, que não existe nos dados reais (cebola e tomate só caíram de preço). Mínimo e "sem histórico" têm caso real.

## 6. Trilha B — `entrada/` e arquivamento (independente de tudo acima)

- **Symlink**, não pasta nova: alvo no `Makefile` criando `entrada -> ~/.local/share/julius/entrada`. O Ctrl+S cai em `precos-dos-mercados/entrada/` e o arquivo **já está** fisicamente no lugar canônico — o que elimina qualquer passo de mover e, com ele, a pergunta "mover antes ou depois de ler".
  ```make
  inbox:
  	mkdir -p ~/.local/share/julius/entrada
  	ln -sfn ~/.local/share/julius/entrada entrada
  ```
- **`.gitignore`**: acrescentar `/entrada`. O padrão `/*_files/`, que este design ia pedir, **já foi adicionado** no commit `65f2fc7` durante a própria sessão de brainstorm — a lacuna que `receipt-inbox.md` F3 registra está fechada.
- **Arquivamento**: `entrada/importados/<data>_<chave>.html`, plano. Renomear é obrigatório (§4.9).
- **`_files/`**: descartado após o arquivamento do HTML. É a única exceção ao "nunca apagar", e ela é consistente com o princípio: o que o princípio protege é a fonte **reparseável** — foi reimportando HTMLs que o endereço da loja foi recuperado em v2. jQuery, CSS e um SVG de logo não podem gerar campo novo nunca. Pendente de veto do usuário; se vetado, `discard_sidecar` simplesmente não é chamado — o resto da trilha não muda.
- **Falha não move nada**: `archive`/`discard_sidecar` só rodam depois de `import_receipt` retornar sem exceção, dentro do `try` por arquivo que a CLI já tem. Arquivo que falhou fica onde está, para corrigir e tentar de novo.

## 7. Tickets propostos (117–124)

Gerados em `docs/tickets/julius-v2/117-*.md` … `130-*.md` (trilha única, numeração continuando a do repositório). São **14**, não os 8 que um corte mais grosso daria: serviço e CLI ficam sempre em tickets separados (124/125, 126/127), e a infra de arquivamento separada de quem a usa (128/129), para cada ticket caber numa sessão de agente.

| # | Ticket | Depende de | Esforço | Entrega |
|---|---|---|---|---|
| 117 | Migração 0003 + `products.kind` | — | S | `0003_product_kind.sql`, `Product.kind`, `PriceRecord.kind`, `set_kind` (regra de grafia), `all_kinds`, `clear_content` |
| 118 | Comandos de desfazer | 117 | M | `produtos tipo [--remover]`, `definir-conteudo --remover`, coluna "Tipo" |
| 119 | Base de comparação | — | M | `domain/comparison_basis.py`, `_highlight_and_trim` corrigido |
| 120 | Prompt `enrich` v2 com `kind` | 117 | M | `ProductEnrichment.kind`, versão `"2"`, `known_kinds` |
| 121 | `curation`: tipo + `AppliedAction` | 118, 120 | M | `propose` não sobrescreve tipo humano; `apply` devolve o que mudou |
| 122 | `_review` aplica + log de ações | 118, 121 | M | conteúdo e tipo automáticos, `actions.jsonl`, resumo agregado |
| 123 | `revisar --ultimas-acoes` | 122 | S | `ai_log.tail`, tabela com comando de desfazer |
| 124 | `comparison.compare_stores` | 117, 119 | M | `KindComparison`, `StoreComparison` |
| 125 | CLI `mercados comparar` | 124 | M | tabela por grupo, contagem derivada, rodapé com `n` e período |
| 126 | `comparison.new_extremes` | 119, 124 | M | `PriceExtreme`, escopo de grupo, exclui a própria nota |
| 127 | CLI: sinal no `importar` + coluna "Dia" | 122, 126 | M | "Nesta compra:" (máx. 5), dia da semana no `consultar` |
| 128 | Infra de arquivamento | — | M | `infra/receipt_files.py`, `Config.inbox_path`/`archive_path`, `ImportResult.access_key` |
| 129 | CLI: entrada e arquivamento | 128 | M | `importar` sem argumento, arquiva, descarta sidecar, `make inbox` |
| 130 | e2e + docs | 117–129 | M | `test_e2e` do ciclo novo, `CLAUDE.md`/`README.md` (inclui a reversão do conteúdo confirmado) |

```
                 ┌─► 118 ─┐
117 ─────────────┼─► 120 ─┴─► 121 ──► 122 ─┬─► 123
                 └─► 124 ──► 125           └─► 127
119 ────────────────┴──────► 126 ───────────────┘

128 ──► 129                     117–129 ──► 130
```

Paralelizável desde o início: **{117, 119, 128}**. **Restrição de ordem que não é técnica, é de princípio:** 118 antes de 122 — a automação só pode aplicar o que já tem comando de desfazer (`comparability-closure.md` §4, condição 1). Caminho crítico: 117 → 118 → 121 → 122 → 127 → 130.

## 8. Riscos

- **Granularidade do tipo escolhida pela IA.** O prompt instrui com os dois casos medidos (`leite uht` ≠ `leite condensado`; marca/sabor/tamanho fora do tipo), mas nada garante consistência. Mitigação: o tipo é reversível por comando (118), a coluna "Tipo" em `produtos listar` torna o erro visível, e um tipo errado num grupo de um só produto é inerte.
- **Fragmentação por singular/plural** (§2) — sem defesa automática de propósito; query de detecção documentada.
- **Obsolescência na comparação entre mercados**: o preço mais barato de uma loja pode ser de semanas antes do de outra. Por isso o rodapé com intervalo de datas é obrigatório, não decorativo. Janela temporal (`--desde`) fica de fora até incomodar.
- **Varredura completa de `prices`** em `compare_stores` — marcado com `ponytail:` e teto documentado (§4.4).
- **`discard_sidecar` é o único passo destrutivo do sistema.** Guardas: nome exato `<stem>_files`, só após arquivamento bem-sucedido, e nunca em caminho de falha.

## 9. O que este design decidiu não fazer

- **`consultar --tipo X`**: `rapidfuzz` sobre `canonical_name` já encontra o grupo quando o termo é o próprio tipo (`consultar tomate` acha os dois tomates hoje). Um filtro novo diria a mesma coisa de outra forma.
- **Corte fuzzy para snapping de tipo**: terceiro cutoff a medir sem evidência de que o problema existe (§2).
- **Estreitar `duplicate_candidates` por `kind`** — tentador, porque mataria o falso positivo `Alho` ↔ `Pão de Alho` (tipos diferentes) de graça e melhoraria a precisão medida de ~5%. Fica fora porque nenhum requisito pediu, e as sugestões de fusão continuam só imprimindo. Vira trivial depois do 117, se incomodar.
- **Índice único de carestia por mercado**: RF5 é contagem por grupo, com `n` e período. Média de razões entre grupos de preços muito diferentes seria um número confiante em cima de 3 pontos.
- **Qualquer estatística de dia da semana** (RF6 mostra o dado e cala).
- **Fusão automática, em qualquer confiança**, e a infraestrutura de undo de merge que ela exigiria (`comparability-closure.md` §3).
