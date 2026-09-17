# 132: `curation` — proposta completa e fim do `auto_tag`

> A proposta passa a carregar a descrição do cupom, a categoria que será aplicada e se o produto é vendido por UN; `tag_is_known`/`auto_tag` somem.

## Contexto

`docs/design/review-scope-v2.3.md` §3 (categoria), §5.1 (`sold_by_unit`), §8.1/§8.4 (contratos). Requisitos RF1/RF2 de `docs/requirements/review-scope-v2.3.md`.

Medido: a IA devolveu **2 categorias para 24 dos 25 produtos** e a primeira já existia no vocabulário em **25 de 25**. A regra "candidato único e conhecido → automático" disparou 1 vez em 25, e o usuário respondeu "1" em 21 de 21 perguntas. O par `tag_is_known`/`auto_tag` existia só para expressar essa regra derrubada.

Depende de **131** (`incomplete_product_ids`, `sold_by_unit_ids`, `receipt_descriptions`).

## Escopo

### Dentro
- `julius/domain/models.py`: `ProductProposal` ganha `receipt_description`, `tag`, `sold_by_unit`; perde `tag_is_known` e a property `auto_tag`.
- `julius/services/curation.py`: `pending_product_ids` passa a usar `incomplete_product_ids`; `propose` preenche os campos novos.
- `julius/cli/_review.py`: **só a ponte mínima** para a suíte continuar verde (ver "Ponte obrigatória").
- Testes: `tests/test_services_curation.py`, e os de `tests/test_cli_review.py` que a ponte muda.

### Fora
- A tabela de revisão e a remoção do laço de categoria (→ 134). Este ticket **não** mexe em `_table` nem em `_ask_tag`.
- A chamada de embalagem e o laço de conteúdo (→ 133, 135).
- Mudar `curation.apply` — a assinatura já serve.
- Mudar `duplicate_candidates`/`judge_duplicates`.
- Fazer `importar` revisar catálogo incompleto: ele continua revisando só `new_product_ids` (design §2).

## Requisitos

### Funcionais

- `ProductProposal` passa a ser:
  ```python
  product_id: int
  current_name: str
  receipt_description: str      # o que o cupom dizia; "" quando o produto não tem preço
  readable_name: str | None
  tags: tuple[str, ...]         # todas as candidatas, melhor primeiro (inalterado)
  tag: str | None               # a primeira candidata QUE JÁ EXISTE no vocabulário
  content: ContentSuggestion | None
  kind: str | None
  sold_by_unit: bool
  ```
  A ordem dos campos é contrato: há construção posicional em `tests/test_services_curation.py`.

- **`tag` é a primeira candidata que já existe em `tags`**, não simplesmente `tags[0]`. Se nenhuma candidata existir no vocabulário, `tag is None` e o produto continua pendente.
  Isto estreita o RF2 de propósito (design §3.2): o vocabulário de tags é a entrada da medição de `TAG_MATCH_CUTOFF = 75` da v2.1, calibrada contra as 13 tags semeadas; deixar a IA criar vocabulário sozinha põe em risco uma constante medida num caminho onde ninguém olha. Custo na amostra: zero (25 de 25 já eram conhecidas). Criar categoria nova continua sendo `julius produtos tag ID nova`, com o humano olhando.

- `pending_product_ids(conn)` passa a chamar `products.incomplete_product_ids`. Nada mais muda na função.

- `propose` preenche, para cada proposta:
  - `receipt_description` a partir de `products.receipt_descriptions` (uma chamada para o lote, não uma por produto);
  - `sold_by_unit` a partir de `products.sold_by_unit_ids` (idem);
  - `tag` pela regra acima, usando a lista `known` que a função já carrega.

### Ponte obrigatória em `julius/cli/_review.py`

Sem isto a suíte fica vermelha, porque `_review` usa `proposal.auto_tag` em três pontos. A mudança é **mecânica**, e o 134 é que reescreve a tela:
- na passada automática, `tag=proposal.tag` no lugar de `tag=proposal.auto_tag`;
- no laço de categoria, `if proposal.tag is not None: continue`;
- em `_table`, `proposal.tag or ("? " + ", ".join(proposal.tags) if proposal.tags else "")`.

Efeito colateral aceito e desejado: a categoria conhecida passa a ser aplicada sozinha já neste ticket, e o laço de pergunta só sobrevive para produto cujas candidatas são todas desconhecidas — quase nunca. O 134 remove o laço de vez.

### Validação e erros
- `propose` continua nunca lançando por causa de IA: lote que falha não gera proposta.
- Produto sem preço → `receipt_description == ""`, `sold_by_unit == False`. Não é erro.

## Especificação técnica

```
modificar julius/domain/models.py          — ProductProposal (3 campos novos, 2 removidos)
modificar julius/services/curation.py      — pending_product_ids, propose
modificar julius/cli/_review.py            — ponte mecânica (3 pontos)
modificar tests/test_services_curation.py
modificar tests/test_cli_review.py
```

### Padrão a seguir
- `propose` já lê `products.all_tag_names` e `products.all_kinds` uma vez por chamada; as duas leituras novas seguem o mesmo lugar e o mesmo estilo (uma chamada, resultado reaproveitado no laço).
- `apply` continua gravando direto pelos repositórios; nada muda ali.

### Testes existentes que este ticket torna obsoletos
- `test_propose_single_known_tag_is_auto` → vira `test_propose_tag_is_first_known_candidate`.
- `test_propose_two_tags_or_unknown_tag_is_not_auto` → vira dois testes: duas conhecidas devolvem a primeira; nenhuma conhecida devolve `None`.
- `test_apply_*` que constroem `ProductProposal` posicionalmente (3 sítios) → acrescentar os campos novos.
- Em `tests/test_cli_review.py`, os que dependem do laço de categoria mudam de expectativa (a categoria agora é aplicada sem perguntar). `test_revisar_sim_applies_first_tag_even_if_unknown` **inverte de propósito**: com tag desconhecida, nada é aplicado.

## Testes obrigatórios

1. `test_pending_uses_incomplete_criterion` — produto com tag mas sem tipo aparece em `pending_product_ids` (não aparecia antes).
2. `test_propose_tag_is_first_known_candidate` — IA devolve `["mercearia", "bebidas"]`, ambas conhecidas → `proposal.tag == "mercearia"`.
3. `test_propose_tag_skips_unknown_first_candidate` — IA devolve `["ovos", "mercearia"]` com só `mercearia` conhecida → `proposal.tag == "mercearia"`.
4. `test_propose_tag_is_none_when_no_candidate_is_known` — IA devolve `["ovos"]` → `proposal.tag is None`, e `proposal.tags == ("ovos",)` continua preenchido.
5. `test_propose_carries_receipt_description` — produto renomeado à mão: `current_name` é o nome novo e `receipt_description` é a descrição crua do cupom (os dois diferentes na mesma proposta).
6. `test_propose_marks_sold_by_unit` — produto UN → `True`; produto KG → `False`.
7. `test_propose_reads_descriptions_and_units_once` — com 3 produtos, a proposta de cada um vem preenchida (prova a leitura em lote; não precisa contar queries).
8. `test_apply_still_returns_actions_with_new_proposal_shape` — regressão: `apply` com a forma nova devolve as 4 ações na ordem `name, tag, content, kind`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -rn "auto_tag\|tag_is_known" julius tests` **vazio**.
- [ ] `grep -n "untagged_product_ids" julius/services/curation.py` vazio (o repositório mantém a função; o serviço não a chama mais).
- [ ] `tests/test_architecture.py` verde sem edição.

## Notas para o agente
- **Não remova `_ask_tag` nem o laço de categoria neste ticket** — é o 134, e a ordem existe para nunca haver um estado em que a revisão pergunta categoria *e* conteúdo ao mesmo tempo.
- A regra de `tag` é "primeira **conhecida**", não "primeira". Se você achar que deveria ser "primeira", pare e anote: está justificado no design §3.2 com a medição que sustenta, e reverter é decisão do usuário.
- `receipt_description` é dado de exibição. Não a use para decidir nada — em particular, não tente extrair tamanho dela.
