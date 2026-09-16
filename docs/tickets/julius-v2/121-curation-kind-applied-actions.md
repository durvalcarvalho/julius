# 121: `curation` propõe tipo e `apply` passa a dizer o que aplicou

> Leva o tipo da IA até a proposta (sem sobrescrever escolha humana) e faz `apply` devolver a lista do que mudou — o dado que o log de ações e o resumo agregado vão consumir.

## Contexto

`docs/design/comparability-v2.2.md` §4.7. Requisitos RF2/RF3 de `docs/requirements/comparability-closure.md`; a exigência de auditabilidade vem da decisão do usuário "resumo agregado, detalhe sob demanda" (§5 do fechamento).

Hoje `curation.apply(conn, proposal, tag=..., content=...)` grava e não devolve nada — quem chama não tem como saber o que mudou nem como montar um desfazer. Este ticket resolve isso e acrescenta o tipo. **Ninguém aplica automaticamente ainda**: `_review` só passa a usar isso no 122.

Depende de **120** (`ProductEnrichment.kind`) e de **118** (os comandos de desfazer precisam existir antes de qualquer automação — `comparability-closure.md` §4).

## Escopo

### Dentro
- `julius/domain/models.py`: `AppliedAction`; `ProductProposal.kind`.
- `julius/services/curation.py`: `propose` passa `all_kinds` e preenche `kind`; `apply` ganha o parâmetro `kind` e devolve `list[AppliedAction]`.
- Testes: `tests/test_services_curation.py`.

### Fora
- `cli/_review.py`, resumo agregado, escrita do log (→ 122).
- `produtos revisar --ultimas-acoes` (→ 123).
- Montar a **string** do comando de desfazer: `AppliedAction` é dado puro; quem conhece a sintaxe da CLI é a CLI (→ 122).
- `duplicate_candidates`/`judge_duplicates` — intocados.

## Requisitos

### Funcionais

- `AppliedAction` (`domain/models.py`, `@dataclass(frozen=True)`):
  ```python
  product_id: int
  field: Literal["name", "tag", "content", "kind"]
  before: str | None      # None when there was no previous value
  after: str | None       # None when the action cleared the value
  ```
  `before`/`after` são **texto** de propósito, para o log ser legível e estável: conteúdo vira `"0.5 KG"`, tipo vira `"tomate"`, tag vira o nome da tag.

- `ProductProposal` ganha `kind: str | None` — `None` significa "nada a aplicar".

- `propose`:
  - passa `products.all_kinds(conn)` como `known_kinds` para `enrich_products`.
  - preenche `ProductProposal.kind` com `enrichment.kind` **somente quando o produto ainda não tem tipo** (`product.kind is None`). Produto que já tem tipo → `kind=None` na proposta, mesmo que a IA tenha sugerido outro. Mesma disciplina de `has_raw_name` para nome: a IA não sobrescreve escolha humana.
  - se `enrichment.kind` for igual ao tipo atual (comparando `normalize_text`), também devolve `None` — não há mudança a aplicar nem a registrar.

- `apply(conn, proposal, *, tag: str | None, content: bool, kind: bool) -> list[AppliedAction]`:
  - lê o estado atual do produto **antes** de gravar (`products.get_product`), para preencher `before`.
  - aplica, dentro do `with conn:` único que já existe, o que foi pedido: nome legível (quando `proposal.readable_name`), tag (quando `tag`), conteúdo (quando `content and proposal.content`), tipo (quando `kind and proposal.kind`).
  - devolve uma `AppliedAction` por campo efetivamente alterado, na ordem `name, tag, content, kind`. Campo que não mudou (ou que não foi pedido) não gera ação.
  - tipo é gravado via `products.set_kind`, que aplica a regra de grafia do 117 — então `after` deve refletir **o que ficou gravado**, não o que foi proposto (ler de volta ou usar o retorno da consulta pós-escrita).

### Validação e erros
- `apply` com `tag` em branco continua levantando `ValueError` como hoje (comportamento existente, não mexer).
- `kind=True` com `proposal.kind is None` → nada acontece, lista sem ação de tipo; não é erro.
- `propose` continua nunca lançando por causa de IA: lote que falha simplesmente não gera proposta.

## Especificação técnica

```
modificar julius/domain/models.py            — AppliedAction, ProductProposal.kind
modificar julius/services/curation.py        — propose (known_kinds, kind), apply (parâmetro kind, retorno)
modificar tests/test_services_curation.py
```

### Padrão a seguir
- `apply` continua gravando **direto pelos repositórios** (`products.rename_product`, `products.add_tag`, `products.set_content`, `products.set_kind`) — não via `services/catalog.py`: `tests/test_architecture.py` proíbe `services → services`. É exatamente por isso que a regra de grafia do tipo mora no repositório (design §4.3).
- Uma transação só por `apply`, como hoje.
- `normalize_text` de `julius.domain.normalization` para a comparação "tipo proposto é igual ao atual".

## Testes obrigatórios

1. `test_propose_fills_kind_for_product_without_one` — produto com `kind IS NULL` e IA devolvendo `"tomate"` → `proposal.kind == "tomate"`.
2. `test_propose_keeps_human_kind` — produto que já tem `kind="tomate"` e IA sugerindo `"tomate italiano"` → `proposal.kind is None` (nada a aplicar).
3. `test_propose_ignores_kind_equal_to_current` — tipo atual `"açaí"`, IA devolve `"ACAI"` → `proposal.kind is None`.
4. `test_propose_passes_known_kinds_to_ai` — com dois produtos já tipados, o `user_prompt` capturado contém os dois tipos na linha `tipos:`.
5. `test_apply_kind_returns_action` — `apply(..., kind=True)` grava e devolve uma `AppliedAction(field="kind", before=None, after="tomate")`.
6. `test_apply_kind_action_reports_stored_spelling` — já existe `"açaí"`; proposta `"acai"` → a ação registra `after == "açaí"` (o que ficou no banco, não o que foi proposto).
7. `test_apply_returns_one_action_per_changed_field` — proposta com nome, tag, conteúdo e tipo aplicados de uma vez → 4 ações, na ordem `name, tag, content, kind`, com `before` correto em cada.
8. `test_apply_skips_unchanged_fields` — `apply` com `tag=None, content=False, kind=False` e `readable_name=None` → lista vazia, nada gravado.
9. `test_apply_content_action_formats_value` — conteúdo `0.5 KG` aplicado → ação com `after == "0.5 KG"`.
10. `test_apply_kind_requested_but_proposal_empty` — `kind=True` com `proposal.kind is None` → nenhuma ação de tipo, sem erro.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `tests/test_architecture.py` verde sem edição.
- [ ] `grep -n "ultimas-acoes\|action_log" julius/` vazio — o log é do 122.
- [ ] Nenhuma string de comando de CLI dentro de `services/curation.py` (`grep -n "julius produtos" julius/services/` vazio).

## Notas para o agente
- `AppliedAction` **não** tem campo de comando de desfazer, de propósito: serviço que sabe escrever comando de CLI é serviço acoplado à UI. A CLI monta a string a partir de `field` + `product_id` + `before` no 122.
- A ordem das ações no retorno é contrato (os testes dependem dela) porque o resumo do 122 conta por campo.
- Não mude a assinatura de `duplicate_candidates` nem de `judge_duplicates` neste ticket, mesmo que pareça natural estreitar por tipo — está explicitamente fora (design §9).
