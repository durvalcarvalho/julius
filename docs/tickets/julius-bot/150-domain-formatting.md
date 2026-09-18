# 150: `domain/formatting.py` — os formatadores puros saem da CLI

<!-- status:done implemented:2026-09-17 commit:77b344c -->
<!-- adjustments: none -->

> As funções de texto que as duas interfaces precisam passam a morar na única camada que as duas podem importar.

## Contexto

`docs/design/telegram-bot.md` §1 (último parágrafo) e §6. O bot (`julius/bot/`, camada L4) precisa de `money`, `br_date`, `relative_age` e `content_text`, que hoje vivem em `julius/cli/_common.py`, e de `_labels`/`_coverage`/`_plural`, que vivem em `julius/cli/stores.py`. `bot` não pode importar `cli` (seria a única seta L4→L4 do projeto e traria `typer`/`rich` para o grafo do bot). São funções puras, só stdlib — o lugar delas é `domain/`, o mesmo motivo que pôs `comparison_basis` lá.

Não depende de nenhum ticket. É o primeiro da trilha porque 154 (render do bot) e 156/157 (previews) importam daqui.

## Escopo

### Dentro
- Criar `julius/domain/formatting.py` com `money`, `br_date`, `relative_age`, `content_text` (movidas de `cli/_common.py`, **corpo idêntico**), `store_labels`, `coverage_text`, `plural_groups` (movidas de `cli/stores.py::_labels`/`_coverage`/`_plural`).
- `julius/cli/_common.py`: importa as quatro de `julius.domain.formatting` e as mantém no namespace (reexport) — nenhum outro arquivo da CLI precisa mudar por causa das quatro.
- `julius/cli/stores.py`: usa `store_labels`/`coverage_text`/`plural_groups` de `domain.formatting`; as três funções privadas somem daqui.
- Testes: criar `tests/test_domain_formatting.py`; `tests/test_cli_common.py` fica só com o que usa `rich` (`date_cell`) e um teste de reexport.

### Fora
- Qualquer arquivo em `julius/bot/` (→ 153 em diante).
- Mudar o comportamento de qualquer formatador — este ticket move, não corrige.
- `date_cell` (devolve `rich.text.Text`; fica em `cli/_common.py`).
- `_weekday`, `_store_cell`, `_extreme_line` de `cli/receipts.py` — usam `rich` ou são exclusivas da CLI; ficam.

## Requisitos

### Funcionais
- Assinaturas idênticas às atuais: `money(value: float) -> str`, `br_date(purchased_at: str) -> str`, `relative_age(purchased_at: str, *, today: date | None = None) -> str`, `content_text(quantity: float, unit: str) -> str`.
- `store_labels(comparison: StoreComparison) -> dict[str, str]` — mesmo corpo de `_labels` (apelido repetido entre CNPJs ganha ` · {cnpj}`).
- `coverage_text(comparison: StoreComparison) -> str` — mesmo corpo de `_coverage` (três ramos).
- `plural_groups(count: int) -> str` — `"grupo"`/`"grupos"`.
- `from julius.cli._common import money, br_date, relative_age, content_text` continua funcionando (reexport explícito, não `import *`).

### Validação e erros
- `tests/test_architecture.py::test_domain_imports_nothing_outside_the_standard_library` continua verde: o módulo importa só `datetime` e `julius.domain.models`.
- Nenhuma exceção nova: `br_date`/`relative_age` de entrada ruim continuam devolvendo `""`.

## Especificação técnica

```
criar     julius/domain/formatting.py      — as sete funções; docstrings movidas junto (inclusive o comentário `ponytail:` de relative_age)
modificar julius/cli/_common.py            — remove os quatro corpos; `from julius.domain.formatting import br_date, content_text, money, relative_age`
modificar julius/cli/stores.py             — remove _labels/_coverage/_plural; importa de domain.formatting
criar     tests/test_domain_formatting.py  — testes movidos de test_cli_common.py + os novos
modificar tests/test_cli_common.py         — fica date_cell + reexport
```

### Padrão a seguir
- `julius/domain/comparison_basis.py`: função pura em `domain`, consumida por duas camadas — o precedente exato.
- Os testes de faixa de `relative_age` continuam com `TODAY = date(2026, 9, 17)` fixo (regra da v2.5.1: faixa nunca depende do dia em que o teste roda).

## Testes obrigatórios

1. `test_cli_common_reexports_the_formatters` — `julius.cli._common.money is julius.domain.formatting.money` (e as outras três).
2. `test_money_uses_comma` — `money(12.9) == "R$ 12,90"`.
3. `test_content_text_drops_trailing_zeros` — `content_text(0.5, "KG") == "0,5 KG"`; `content_text(30, "UN") == "30 UN"`.
4. `test_store_labels_append_cnpj_only_when_nickname_repeats` — dois CNPJs com o mesmo apelido → ambos com ` · {cnpj}`; um apelido único → sem sufixo.
5. `test_coverage_text_three_branches` — `single < total`, `total == 1`, `single == total > 1`.
6. Os testes de `br_date` e `relative_age` hoje em `test_cli_common.py` passam **inalterados** importando de `julius.domain.formatting`.
7. `test_date_cell_*` continuam em `test_cli_common.py`, verdes.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -n "^def money\|^def br_date\|^def relative_age\|^def content_text" julius/cli/_common.py` **vazio**.
- [ ] `grep -n "_labels\|_coverage\|_plural" julius/cli/stores.py` **vazio**.
- [ ] `tests/test_architecture.py` verde **sem edição**.
- [ ] `julius consultar picanha` e `julius mercados comparar` (num banco de teste) imprimem exatamente o que imprimiam.

## Notas para o agente

- Mover, não reescrever: copie os corpos com os comentários que já têm. Se sentir vontade de "melhorar" um formatador, anote e não faça — a v2.5.1 mediu esses textos.
- `store_labels` recebe `StoreComparison` (não a lista de grupos) para a assinatura ficar igual à de `coverage_text`.
- Não crie `julius/bot/` neste ticket, mesmo vazio.
