# 131: Repositório — pendência por campo faltando

> Três leituras novas em `repositories/products.py` que sustentam o critério de pendência da v2.3. Ninguém as consome ainda.

## Contexto

`docs/design/review-scope-v2.3.md` §2 (a query e por que ela mora no repositório), §8.2 (contratos). Requisito RF1 de `docs/requirements/review-scope-v2.3.md`.

Hoje `curation.pending_product_ids` é `products.untagged_product_ids`: produto com tag sai da fila para sempre. Medido no banco real: **4 produtos** pendentes por esse critério e **49 com tag e sem conteúdo**, dos quais 16 têm quantidade inequívoca no nome. Este ticket cria só as leituras; quem troca o critério é o 132.

## Escopo

### Dentro
- `julius/repositories/products.py`: `incomplete_product_ids`, `sold_by_unit_ids`, `receipt_descriptions`.
- `tests/test_repositories_products.py`.

### Fora
- `services/curation.py` e qualquer CLI (→ 132, 134).
- **Remover `untagged_product_ids`** — ele continua existindo e continua testado; só deixa de ser chamado pelo `curation` no 132.
- A chamada de IA de embalagem (→ 133).
- Índice em qualquer coluna: são 105 linhas (design §2, nota `ponytail:`).

## Requisitos

### Funcionais

- `incomplete_product_ids(conn) -> list[int]` — ids ordenados de produtos aos quais falta pelo menos um campo:

  ```sql
  SELECT id FROM products p
  WHERE p.kind IS NULL
     OR NOT EXISTS (SELECT 1 FROM product_tags WHERE product_id = p.id)
     OR (p.content_quantity IS NULL
         AND EXISTS (SELECT 1 FROM prices WHERE product_id = p.id AND unit = 'UN'))
  ORDER BY id
  ```
  As três condições e o `EXISTS` de `unit = 'UN'` são contrato, não detalhe:
  - **conteúdo só falta para produto vendido por UN** — R$/kg já é preço por conteúdo (ramo 1 de `domain/comparison_basis.py`); sem isso 26 produtos ficariam pendentes para sempre sem nada a ganhar;
  - **`EXISTS`, não "unidade principal"** — um produto pode ter linha em UN numa loja e KG noutra; basta uma em UN para o conteúdo importar. "Unidade majoritária" seria um conceito que o schema não tem.
  - produto **sem nenhuma linha em `prices`** não é pendente por conteúdo, e continua pendente por tag/tipo se for o caso.

- `sold_by_unit_ids(conn, product_ids: Sequence[int]) -> set[int]` — subconjunto dos ids que têm ao menos uma linha em `prices` com `unit = 'UN'`. Sequência vazia → `set()`, sem consultar.

- `receipt_descriptions(conn, product_ids: Sequence[int]) -> dict[int, str]` — a `prices.description` da compra **mais recente** de cada produto, numa query só para o lote todo. Produto sem preço não aparece no dicionário. Sequência vazia → `{}`, sem consultar.

### Validação e erros
- Nenhuma das três lança. Id inexistente simplesmente não aparece no resultado.
- Nenhuma recebe `product_ids` como `None`.

## Especificação técnica

```
modificar julius/repositories/products.py   — incomplete_product_ids, sold_by_unit_ids, receipt_descriptions
modificar tests/test_repositories_products.py
```

### Padrão a seguir
- Query com lista de ids: `placeholders = ",".join("?" * len(product_ids))`, exatamente como `prices.prices_for_products` já faz.
- Guarda de sequência vazia antes de montar SQL, como `prices.prices_for_products` (o `IN ()` do SQLite é erro de sintaxe).
- `has_raw_name` já é precedente de query em `prices` dentro de `repositories/products.py` — não mova nada para `repositories/prices.py`.
- Para `receipt_descriptions`, use o comportamento documentado do SQLite de **coluna nua com um único `max()`**: numa consulta agregada com `GROUP BY product_id` e `max(purchased_at)`, as demais colunas vêm da linha que casou com o máximo. Isso evita subconsulta correlacionada. **Deixe um comentário explicando isso** — é o tipo de coisa que não é óbvia e alguém "consertaria" achando que é bug. Empate exato de `purchased_at` escolhe uma linha arbitrária entre as empatadas; é aceitável (é coluna de exibição).

## Testes obrigatórios

1. `test_incomplete_includes_product_without_kind` — produto com tag e conteúdo, `kind IS NULL` → aparece.
2. `test_incomplete_includes_product_without_tag` — com tipo e conteúdo, sem tag → aparece.
3. `test_incomplete_includes_un_product_without_content` — vendido por UN, com tag e tipo, conteúdo nulo → aparece.
4. `test_incomplete_excludes_kg_product_without_content` — **o caso que justifica a exceção**: vendido por KG, com tag e tipo, conteúdo nulo → **não** aparece.
5. `test_incomplete_includes_product_sold_by_un_in_any_store` — mesmo produto com linha KG numa loja e UN noutra, sem conteúdo → aparece.
6. `test_incomplete_excludes_complete_product` — tag, tipo e conteúdo → não aparece; catálogo todo completo → `[]`.
7. `test_incomplete_is_ordered_by_id` — três pendentes inseridos fora de ordem → lista ordenada.
8. `test_sold_by_unit_ids` — mistura de UN e KG devolve só os UN; lista vazia → `set()`; id inexistente → ausente do resultado.
9. `test_receipt_descriptions_returns_latest` — duas compras do mesmo produto com descrições diferentes → vem a da data mais recente.
10. `test_receipt_descriptions_ignores_product_without_prices_and_empty_input` — produto sem preço fora do dicionário; `[]` → `{}`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira — hoje 541 testes).
- [ ] `grep -rn NotImplementedError julius` vazio.
- [ ] `grep -rn "incomplete_product_ids\|sold_by_unit_ids\|receipt_descriptions" julius/services julius/cli` **vazio** — ninguém consome ainda.
- [ ] `tests/test_architecture.py` verde sem edição.
- [ ] Rodar contra uma cópia do banco real e conferir o número: `cp ~/.local/share/julius/prices.db /tmp/p.db` e um `python -c` chamando `incomplete_product_ids` deve devolver perto de 90 ids (contra 4 de `untagged_product_ids`).

## Notas para o agente
- Não "melhore" a condição de conteúdo para olhar o nome do produto atrás de um número. Extrair tamanho da descrição por regex está rejeitado três vezes neste projeto, a última com evidência nova (`Filme PVC 30m x 28cm` lido como 30 unidades).
- Não transforme as três funções em uma só que devolve um objeto: cada uma responde uma pergunta e tem chamador diferente.
