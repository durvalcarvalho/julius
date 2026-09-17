# 134: `_review` — tabela honesta e fim da pergunta de categoria

> A tabela passa a distinguir "já resolvido" de "a IA não soube", volta a mostrar o cupom de verdade, e o laço de pergunta de categoria é removido.

## Contexto

`docs/design/review-scope-v2.3.md` §6 (tabela), §3.1 (o que sai), §1 questão 2. Requisitos RF2/RF3 de `docs/requirements/review-scope-v2.3.md`.

Foi a coluna que abriu este ciclo: na tela real, "Conteúdo" em branco significava ao mesmo tempo "já está gravado, nada a propor" e "a IA não soube" — das 25 linhas, 9 em branco **já tinham** conteúdo. A coluna "Cupom" tinha o mesmo defeito: mostra `canonical_name`, que depois do primeiro `renomear` não é mais o que o cupom dizia (na tela real, "Cupom" e "Nome" saíram idênticos nas 25 linhas).

Depende de **132** (`ProductProposal.tag`, `receipt_description`; a ponte mecânica já feita lá).

## Escopo

### Dentro
- `julius/cli/_review.py`: `_table` reescrita; remoção de `_ask_tag` e do laço de categoria; contagem de pendentes passa a ser de conteúdo.
- `tests/test_cli_review.py`.

### Fora
- O laço de pergunta de conteúdo (→ 135). Depois deste ticket a revisão **não pergunta nada**; o 135 é que reintroduz uma pergunta, só para conteúdo.
- `suggest_packaging` e `PackagingHint` (→ 133/135).
- `curation` e domínio (fechados no 132).
- `--sim` e `_is_interactive` — só mudam no 135.
- O bloco de duplicatas e o resumo agregado: comportamento existente, preservado.

## Requisitos

### Funcionais

- **Colunas de `_table`**, nesta ordem: `ID`, `Cupom`, `Nome`, `Categoria`, `Tipo`, `Conteúdo`.

  | Coluna | Conteúdo |
  |---|---|
  | `Cupom` | `proposal.receipt_description` (o que o cupom dizia); vazio quando o produto não tem preço |
  | `Nome` | `proposal.readable_name or proposal.current_name` (inalterado) |
  | `Categoria` | `proposal.tag` (a que vai ser aplicada); candidatas descartadas em `dim` ao lado |
  | `Tipo` | `proposal.kind`; quando `None`, o **tipo atual do produto em `dim`** |
  | `Conteúdo` | `proposal.content` formatado; quando `None`, o **conteúdo atual do produto em `dim`** |

- **Célula vazia passa a ter um significado só**: a IA não respondeu e o produto não tem o dado. É esse o ponto do ticket.

- Para o valor atual em `dim`, `_table` precisa do estado do produto. Receba-o como parâmetro (`_table(proposals, products_by_id)`), montado em `review_products` a partir de `catalog.list_products` — **não** consulte repositório direto da CLI (a DAG proíbe `cli → repositories`).

- Estilo: `rich.text.Text(valor, style="dim")` na célula. `cli/receipts.py::_store_cell` já é precedente de célula com trecho em `dim`.

- Categoria com candidatas descartadas: `mercearia` normal seguido de ` · bebidas` em `dim`. Sem o prefixo `?` — não há mais dúvida do ponto de vista da tela, a primeira conhecida vai ser aplicada.

- **Remover** `_ask_tag` e o laço de categoria inteiro. Depois dele, `review_products` é: propor → tabela → passada automática → log → resumo → duplicatas → pendentes.

- A contagem final de pendentes deixa de ser "sem categoria" e passa a contar **produtos que continuaram sem conteúdo** (proposta sem conteúdo, produto vendido por UN e sem conteúdo gravado): `Pendentes: N produto(s) sem conteúdo.` Zero pendentes → linha não sai.

### Validação e erros
- Proposta cuja `tag is None` simplesmente não aplica categoria; nenhuma pergunta, nenhum erro.
- `receipt_description` vazia → célula vazia, tabela renderiza.
- Nada aqui pode mudar código de saída: a revisão continua saindo 0 em todos os casos que já saía.

## Especificação técnica

```
modificar julius/cli/_review.py       — _table, review_products; remove _ask_tag e o laço de categoria
modificar tests/test_cli_review.py
```

### Padrão a seguir
- `rich.text.Text` com `style="dim"`: ver `cli/receipts.py::_store_cell`, que já põe o endereço em cinza embaixo do apelido.
- Formatação de conteúdo (`0,5 KG`): `cli/products.py::_content` já formata `Product`; use o mesmo formato (`f"{quantity:g} {unit}"`) para a proposta, para as duas telas não divergirem.
- Testes de CLI monkeypatcham `_review._is_interactive`; mantenha a função.

### Testes existentes que este ticket muda
- `test_revisar_prompts_for_ambiguous_tag_and_applies_choice` → **obsoleto**; vira "aplica a primeira conhecida sem perguntar".
- `test_revisar_other_option_creates_new_tag` → **obsoleto**; não há mais opção "outra".
- `test_revisar_enter_skips_and_reports_pending` → **obsoleto aqui**; o 135 reescreve o conceito de pendente para conteúdo.
- `test_revisar_prints_table_with_cupom_and_new_name_columns` → passa a **exigir** que "Cupom" e "Nome" sejam diferentes quando o produto já foi renomeado.

## Testes obrigatórios

1. `test_table_shows_receipt_description_not_renamed_name` — produto renomeado à mão: a linha traz a descrição crua do cupom **e** o nome novo, em colunas diferentes.
2. `test_table_shows_current_content_dim_when_nothing_to_propose` — produto que já tem `0,5 KG` e proposta sem conteúdo: a saída contém `0,5 KG` (o valor atual), e o teste distingue essa linha da de um produto sem conteúdo nenhum, cuja célula fica vazia.
3. `test_table_shows_current_kind_when_nothing_to_propose` — idem para Tipo.
4. `test_table_shows_category_and_discarded_candidates` — IA devolve `["mercearia", "bebidas"]` → a saída traz as duas, e `?` não aparece.
5. `test_revisar_applies_first_known_category_without_asking` — duas candidatas conhecidas, `_is_interactive` verdadeiro, sem `--sim` → categoria gravada e **nenhum prompt** na saída.
6. `test_revisar_does_not_apply_unknown_category` — candidatas todas fora do vocabulário → nenhuma tag gravada, nenhuma tag criada em `tags`, nenhuma pergunta.
7. `test_revisar_reports_pending_content` — produto UN sem conteúdo e sem proposta de conteúdo → `Pendentes: 1 produto(s) sem conteúdo.`
8. `test_revisar_no_pending_line_when_nothing_pending` — todas as propostas completas → a linha de pendentes não aparece.
9. `test_revisar_asks_nothing_at_all` — com `_is_interactive` verdadeiro e uma proposta ambígua, rodar **sem `input=`** termina com código 0 (prova que nada bloqueia esperando stdin).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -n "_ask_tag" julius tests -r` **vazio**.
- [ ] `grep -n "categoria" julius/cli/_review.py` não mostra nenhuma linha de `typer.prompt`.
- [ ] `julius produtos revisar` com IA configurada e TTY não pede nada e sai 0.
- [ ] `tests/test_architecture.py` verde sem edição (em particular: `cli` não importa `repositories`).

## Notas para o agente
- **Não reintroduza confirmação de conteúdo.** O teste `test_revisar_applies_content_without_asking` tem que continuar passando sem edição — ele é a garantia de que a reversão da v2.2 não voltou atrás.
- Depois deste ticket a revisão fica temporariamente 100% silenciosa. Isso é o estado intermediário correto: o 135 reintroduz **uma** pergunta, e só para o conteúdo que a IA recusou.
- Não use `?` nem nenhum outro marcador de incerteza na coluna Categoria: a primeira conhecida é sempre aplicada, e sinalizar dúvida numa ação já tomada é ruído.
