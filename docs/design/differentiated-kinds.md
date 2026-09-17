# Julius — nenhuma comparação sem os dois nomes: design

> Requisitos: `docs/requirements/differentiated-kinds.md` (RF0 §4.0, RF1 §4, RF2 §5, refutações §2).
> **Escopo deste design: RF0 apenas** — os dois pontos onde o sistema compara e não diz o que comparou. RF1 e RF2 ficam sequenciados em §7 com os itens abertos intactos (Q1 dos requisitos continua sem resposta e este design não a decide).
> **Baseline: a árvore de trabalho, não o `HEAD`.** Commit `39a6f28` + 404 linhas não commitadas de duas features independentes (nome fantasia via CNPJ, datas legíveis) que tocam **os quatro** arquivos do RF0. Quem implementar deve diferenciar contra a árvore, não contra `39a6f28`.

## 0. O que os requisitos já decidiram e este design obedece

1. **Não existe regra automática.** Corredor, dispersão de preço e similaridade de texto foram medidos e refutados (requisitos §2). Este design não classifica nada: ele mostra os nomes e o usuário julga.
2. **RF0 antes de RF1.** Mostrar os nomes cobre os 9 tipos heterogêneos de uma vez, sem curadoria e sem regressão possível; dividir tipo cobre um por vez e depende de curadoria contínua.
3. **`tipo --remover` é proibido como solução** (requisitos F13, medido): o produto volta para `incomplete_product_ids` e a IA regrava o tipo genérico sozinha na revisão seguinte. RF1 é sempre "dividir em tipo fino", nunca "limpar".
4. **Nada de schema.** Nenhuma migração, nenhuma coluna, nenhuma tabela. Os dois dados que faltam na tela já existem em memória no ponto de construção.

## 1. O que a árvore de trabalho já entregou de graça

A refatoração em voo do `compare_stores` trocou `cheapest: dict[str, tuple[float, str]]` por `dict[str, tuple[float, PriceRecord]]` (para chavear por CNPJ em vez de apelido). Consequência não intencional e decisiva: **`record.canonical_name` já está em mão exatamente onde `StorePrice` é construído.** O RF0.1 deixou de precisar de qualquer mudança em repositório ou serviço de leitura.

`PriceRecord.canonical_name` já é o nome do **grupo de fusão** (`repositories/prices.py` faz `JOIN product_group` e lê `n.canonical_name`), então a coluna mostra o mesmo nome que `produtos listar` e `consultar` mostram — nenhuma tela diverge (commit `39a6f28`, "Name a merged group the same way on every screen").

## 2. RF0.1 — coluna "Produto" em `mercados comparar`

### 2.1 Contrato

```python
# julius/domain/models.py
@dataclass(frozen=True)
class StorePrice:
    store_nickname: str
    price: float                  # on the comparison basis
    purchased_at: str
    product_name: str             # NEW: the product whose price represents this store in the group
    store_cnpj: str = ""          # already there
```

**Campo obrigatório, sem default, declarado antes de `store_cnpj`** — campo sem default não pode vir depois de campo com default.

> **O único jeito de esta mudança quebrar em silêncio:** `StorePrice` é construído **posicionalmente** em `comparison.py:49`, e `cnpj` está hoje no 4º lugar. Inserir `product_name` no 4º lugar passa o CNPJ para `product_name` se o ponto de chamada não for editado no mesmo commit. É o mesmo ticket e a mesma linha — mas está escrito aqui porque um erro de posição em campos ambos `str` não levanta exceção nenhuma, só renderiza a coluna errada.

Medido: `StorePrice(` aparece em **um** lugar em todo o repositório (`services/comparison.py:49`) e em **nenhum** teste, então um campo obrigatório não custa uma linha de churn e ganha a garantia de que um ponto de construção futuro não pode esquecê-lo e renderizar célula vazia. `store_cnpj = ""` é defensivo e não é precedente para copiar aqui: a diferença é que o dado de `product_name` está sempre em mão (é o mesmo `record`).

### 2.2 Pontos de chamada (2)

| Arquivo | Mudança |
|---|---|
| `services/comparison.py::compare_stores` | `StorePrice(record.store_nickname, value, record.purchased_at, cnpj, record.canonical_name)` — `record` já está no `cheapest` |
| `cli/stores.py::_comparison_table` | `Table("Mercado", "Produto", "Preço", "Data", …)` e `entry.product_name` na segunda posição do `add_row` |

### 2.3 O que a coluna significa, e o viés que ela torna visível

`compare_stores` representa uma loja pela **linha mais barata** que ela cobrou no grupo (requisitos F4). Antes, esse viés era invisível: a tabela dizia `vinho` e um preço. Agora a coluna nomeia qual produto ganhou a vaga da loja — que é exatamente a informação que faltava para o viés ser julgável. Nenhuma mudança de comportamento: a escolha da linha continua a mesma.

### 2.4 Renderizado a 80 colunas, com os dados reais (não é mockup)

```
                          vinho · por L (por conteúdo)
┃ Mercado                   ┃ Produto                  ┃ Preço    ┃ Data       ┃
│ Costa Atacadao ADE Aguas  │ Vinho brasileiro         │ R$ 31,99 │ 2026-09-16 │
│ Claras                    │ Mioranza frisante 750ml  │          │            │
│                           │ suave branco             │          │            │
│ ASSAI-ATACADISTA          │ Vinho Norton 750ml BC SV │ R$ 46,53 │ 2026-09-04 │

                          cebola · por KG
┃ Mercado                         ┃ Produto ┃ Preço   ┃ Data       ┃
│ Costa Atacadao ADE Aguas Claras │ Cebola  │ R$ 7,89 │ 2026-09-16 │
│ DONA DE CASA CANDANGOLANDIA     │ Cebola  │ R$ 9,99 │ 2026-09-10 │
```

Os 6 grupos reais foram renderizados a 80 colunas nesta sessão. O `vinho` quebra em 3 linhas e é o grupo que mais precisa da informação; os grupos de produto único (`cebola`, `sacola reutilizável`, `tomate`) repetem o nome e leem bem — o nome repetido **é** o sinal de "comparação direta".

## 3. RF0.2 — `previous_product_name` no sinal do `importar`

### 3.1 Contrato

```python
# julius/domain/models.py
@dataclass(frozen=True)
class PriceExtreme:
    ...
    previous_price: float
    previous_store: str
    previous_at: str
    previous_product_name: str        # NEW: the product this row beat
    scope: str
```

**Campo obrigatório, entre `previous_at` e `scope`**, junto dos outros três `previous_*`. `PriceExtreme` não tem nenhum campo com default hoje, então não há restrição de ordem. Medido: um ponto de construção em produção (`services/comparison.py:107`, tudo por palavra-chave) e um helper de teste (`tests/test_cli_receipts.py:485::_extreme`, `PriceExtreme(**values)`).

O helper precisa de **uma linha**, e ela deve ser `previous_product_name=name` — igual ao `product_name`, coerente com o `scope=name` que já está lá (escopo por produto ⇒ nomes coincidem). Assim toda asserção existente continua exercitando o ramo **suprimido**, e o teste do ramo novo passa `previous_product_name="Outro"` por `**overrides`.

### 3.2 Ponto de produção

`services/comparison.py::new_extremes` já tem `previous_row` em mão (`highlight, (previous_value, previous_row) = lowest`) e hoje só usa `previous_row.store_nickname`. Passa `previous_product_name=previous_row.canonical_name`. Zero query nova.

### 3.3 Ponto de consumo e o predicado de supressão

`cli/receipts.py::_extreme_line`, linha do `previous`:

```python
previous = f"era {money(extreme.previous_price)} em {extreme.previous_store}, {_day_month(extreme.previous_at)}"
if extreme.previous_product_name and extreme.previous_product_name != extreme.product_name:
    previous = f"era {money(extreme.previous_price)} ({extreme.previous_product_name}) em …"
```

**O predicado é `previous_product_name != product_name`, e não uma inspeção de `scope`.** Motivo: quando `kind IS NULL`, `new_extremes` filtra o escopo por `row.product_id == record.product_id`, então o anterior é sempre o mesmo produto e os nomes coincidem por construção — o teste de nome cobre o teste de escopo e mais um caso que o de escopo não cobre (produto fundido batendo o próprio preço em outra loja, onde `kind` existe mas o nome é o mesmo).

Medido nesta sessão contra a nota real de 16/09: o predicado dispara em **3 de 3** linhas que precisam (`banana` ← Banana prata, `uva` ← Uva branca bandeja 500g, `vinho` ← Norton) e em nenhuma que não precisa. O caso da uva passa de `↑ Uva Green Dreams Mimo R$ 29,98/KG maior preço já pago (era R$ 13,98 em Assaí, 04/09)` — que afirma "pagou caro" — para a mesma linha com `(era R$ 13,98 (Uva branca bandeja 500g) …)`, que se explica.

**Atenção para quem implementar:** essa nota **não exercita o ramo de supressão** (0 casos). O ramo suprimido é o mais comum no uso normal (recomprar cebola mais barato que a última vez) e está garantido estruturalmente, não observado. É teste obrigatório (§5.2), não medição pendente.

## 4. Contratos por módulo

| Camada | Arquivo | Mudança | Linhas |
|---|---|---|---|
| `domain` | `models.py` | `StorePrice.product_name`, `PriceExtreme.previous_product_name`, ambos obrigatórios | 2 |
| `services` | `comparison.py` | um argumento em `StorePrice(...)`, um em `PriceExtreme(...)` | 2 |
| `cli` | `stores.py::_comparison_table` | coluna no `Table` + célula no `add_row` | 2 |
| `cli` | `receipts.py::_extreme_line` | `if` de supressão + interpolação | 3 |

Nenhum módulo novo, nenhuma função nova, nenhuma assinatura de serviço alterada, nenhuma dependência. A DAG de `tests/test_architecture.py` não é tocada: `domain` continua sem importar nada, `services` continua a única camada que monta os dois modelos e `cli` continua só formatando.

## 5. Testes

### 5.1 `tests/test_services_comparison.py` — o nome que chega ao `StorePrice`

- **Feliz:** grupo com dois produtos diferentes na mesma `kind`/`unit` → cada `StorePrice.product_name` é o nome do produto da linha que representa aquela loja.
- **Triste/específico:** loja com **dois** produtos no grupo, um mais barato → `product_name` é o do mais barato, não o primeiro encontrado. É o teste que trava o viés de F4 no lugar onde ele agora aparece.

### 5.2 `tests/test_services_comparison.py` — os dois ramos do predicado

- **Nomes diferentes:** produto novo bate o recorde de outro produto do mesmo `kind` → `previous_product_name` é o nome do produto batido e difere de `product_name`.
- **Nomes iguais (o ramo não observado):** produto sem `kind` batendo o próprio histórico → `previous_product_name == product_name`. Um teste de CLI afirma que a frase **não** repete o nome nesse caso.

### 5.3 `tests/test_cli_catalog.py` — a coluna na saída

- `mercados comparar` com um grupo de dois produtos diferentes → a saída contém os dois nomes.
- Grupo de produto único → o nome aparece (repetido), e o cabeçalho tem "Produto". Afirmar presença de substring, nunca largura ou arte da tabela (o `rich` quebra linha conforme a largura do terminal e o apelido da loja mudou duas vezes esta semana).

### 5.4 Churn esperado nos testes existentes: uma linha

Exatamente uma — `previous_product_name=name` no dict de `tests/test_cli_receipts.py:485::_extreme` (§3.1). Nada mais constrói `StorePrice` ou `PriceExtreme` fora de `services/comparison.py`. Se a implementação precisar editar mais que isso, algum ponto de construção novo apareceu e merece ser olhado, não silenciado com um default.

## 6. Decisões deste design, além dos requisitos

**D1 — a coluna aparece sempre, não só quando o grupo mistura produtos.** A alternativa (mostrar só quando há ≥2 nomes distintos) foi considerada: economizaria a repetição em 3 dos 6 grupos e sinalizaria heterogeneidade de graça. **Rejeitada** porque faz a *ausência* da coluna carregar significado: quem não conhece a regra lê coluna faltando como funcionalidade faltando. Sempre presente é um ramo a menos e nunca ambíguo. Não "otimizar" isso de volta sem um pedido explícito.

**D2 — sem truncamento de nome.** Com `_labels` podendo render `Apelido · CNPJ` (14 caracteres extras) e nomes de até ~50 caracteres, a tabela de 4 colunas quebra linha a 80 colunas — verificado, o pior caso (`vinho`) usa 3 linhas. `rich` quebra sozinho; truncar exigiria escolher o que cortar de um nome cuja íntegra é justamente o ponto. Consequência aceita, não surpresa.

**D3 — o predicado de supressão compara nomes, não escopos** (§3.3). Registrado porque comparar `scope` parece mais "correto" e cobre menos casos.

**D4 — a coluna não muda ordenação, destaque nem seleção de linha.** `HIGHLIGHT_STYLE` continua por posição (primeira/última), a base continua vinda de `comparison_basis`, a linha representante continua a mais barata. RF0 é exibição, e é isso que torna seguro fazê-lo antes de qualquer curadoria.

## 7. Sequência e o que fica para depois

**Ticket 147 — `mercados comparar` diz qual produto** (§2): `StorePrice.product_name`, o argumento em `compare_stores`, a coluna, testes 5.1 e 5.3.
**Ticket 148 — o sinal do import diz o que foi batido** (§3): `PriceExtreme.previous_product_name`, o argumento em `new_extremes`, o `if` em `_extreme_line`, testes 5.2.

Independentes entre si (arquivos de CLI diferentes, modelos diferentes) e ambos independentes das duas features em voo — mas os dois tocam `domain/models.py` e `services/comparison.py`, então **em série**, 147 antes de 148, para não conflitar com a árvore suja.

### 7.1 RF1 (dividir os 9 tipos) — tem um gate de medição antes de qualquer código

Aplicar o tipo fino é o usuário rodando `julius produtos tipo ID "tipo fino"`; não há ticket. O que precisa de decisão é se isso **se sustenta para produtos novos**, e isso é um número que não existe:

> Uma chamada `enrich` real, com 2–3 vinhos sintéticos, contra um vocabulário `tipos` em que `vinho` já foi substituído por `vinho tinto seco`/`vinho frisante suave`. Custo ~US$ 0,002. Se voltar `vinho`, a instrução "Marca, fornecedor, sabor e tamanho NÃO entram no tipo" (que usa `"uva", não "uva green dreams"` como exemplo negativo — requisitos §3) vence a instrução "Prefira um tipo da lista", e aí RF1 exige mexer no prompt ou restringir o `kind` proposto ao vocabulário conhecido, como já é feito com categoria desde a v2.3.

**Não desenhar mudança de prompt antes desse número.** Mexer no texto medido é o que os requisitos §8 proíbem sem dado novo.

### 7.2 RF2 (tela dos tipos heterogêneos) — Q1 continua aberta

Requisitos §9 Q1 oferece três formas (subcomando `produtos tipos`, flag em `produtos listar`, dica no fim de `mercados comparar`) e **o usuário não escolheu**. Este design não escolhe por ele. Observação que talvez mude a resposta: com o RF0 entregue, a tabela do `mercados comparar` já mostra os nomes lado a lado nos 6 tipos que têm duas lojas — a tela de RF2 passa a valer pelos **3 tipos restantes** (`manga`, `aveia` e o resto de `tempero`), não pelos 9. É menos urgente do que era quando a pergunta foi feita.
