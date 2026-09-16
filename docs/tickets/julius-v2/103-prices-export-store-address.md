# 103: Endereço em `PriceRecord` e no CSV

> `prices_for_products` traz `stores.address` como `PriceRecord.store_address`; `exportar` ganha a coluna `store_address`.

## Contexto

Para `consultar` mostrar onde o preço foi pago (→ 111), o registro de preço precisa carregar o endereço da loja. `docs/design/ai-v2.md` §4.1 e §4.8.

Depende de 102 (coluna `address`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/domain/models.py`: `PriceRecord.store_address: str | None = None` (depois de `store_nickname`, com default para não quebrar construtores existentes).
- `julius/repositories/prices.py`: `prices_for_products` seleciona `s.address`; `EXPORT_COLUMNS` ganha `"store_address"` logo após `"store_nickname"`; `_EXPORT_SQL` seleciona `s.address AS store_address` na mesma posição.
- Testes: `tests/test_repositories_prices.py`, `tests/test_services_export.py` (e `tests/test_e2e.py` se algum teste fixar a lista exata de colunas).

### Fora
- Renderização na CLI (→ 111). Mudar ordem/nome das colunas existentes do CSV.

## Requisitos

### Funcionais
- `PriceRecord.store_address` é o `stores.address` da loja do preço; `None` quando a loja ainda não tem endereço.
- CSV: cabeçalho `purchased_at;store_cnpj;store_nickname;store_address;product_id;…` (o resto igual). Valor vazio quando `NULL` (comportamento padrão do `csv.DictWriter`).
- `search.search_prices` não muda de assinatura; `replace(record, highlight=…)` continua funcionando (é dataclass, campo novo vem junto).

### Validação e erros
- Nenhuma.

## Especificação técnica

```
modificar julius/domain/models.py
modificar julius/repositories/prices.py
modificar tests/test_repositories_prices.py
modificar tests/test_services_export.py
modificar tests/test_e2e.py                 (só se fixar EXPORT_COLUMNS)
```

## Testes obrigatórios

1. `test_repositories_prices.py::test_prices_for_products_carry_store_address` — importar `qrcode-3.html` via `import_receipt` → todo registro tem `store_address` terminando em `GUARA II, BRASILIA, DF`.
2. `test_prices_for_products_address_is_none_for_store_without_one` — `ensure_store` sem endereço + `insert_price` manual → `store_address is None`.
3. `test_services_export.py::test_export_header_includes_store_address_after_nickname` — posição exata no cabeçalho.
4. `test_export_writes_address_value_and_empty_when_null`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `julius exportar` num banco de teste produz CSV com a coluna nova e abre em planilha (separador `;` mantido).

## Notas para o agente
- Não adicione o endereço a `PriceRecord` como parte do `highlight`/agrupamento: o agrupamento continua por `unit` apenas.
