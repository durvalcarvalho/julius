# 008: Serviço export

> `export_csv(conn, destination)` despeja todos os preços (com loja e produto) num CSV legível em planilha.

## Contexto

CSV não é fonte da verdade — é uma view para Excel/LibreOffice ou backup legível. Leia no `CLAUDE.md`: "Armazenamento" (por que CSV virou export), "CLI § exportar".

Depende de 004 (`prices.export_rows`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/services/export.py` com `export_csv(conn, destination: Path) -> int`.
- `tests/test_services_export.py`.

### Fora
- Filtros/colunas configuráveis. Formatos além de CSV. Comando de CLI → 009.

## Requisitos

### Funcionais
- Colunas e ordem exatamente as de `prices.export_rows` (004). Cabeçalho sempre escrito, mesmo com zero linhas.
- Delimitador `;`, `encoding="utf-8"`, `newline=""` (regra do módulo `csv`). Números como o Python os representa (`6.99`), sem formatação pt-BR — planilha lê `;` como separador e converte.
- Cria diretórios pais de `destination` se não existirem; sobrescreve arquivo existente.
- Retorna o número de linhas de dados escritas (sem contar cabeçalho).

### Validação e erros
- `destination` apontando para um diretório existente → o `IsADirectoryError` do Python propaga.

## Especificação técnica

```
criar julius/services/export.py
criar tests/test_services_export.py
```

Imports: `csv`, `pathlib`, `sqlite3`, `julius.repositories.prices`. Use `csv.DictWriter` com `fieldnames` fixos.

## Testes obrigatórios

1. `test_export_empty_db_writes_header_only_and_returns_zero`
2. `test_export_after_import_writes_all_rows` — `qrcode.html` via 005 → retorna 20; `csv.reader` com `delimiter=";"` lê 21 linhas.
3. `test_export_columns_in_exact_order`
4. `test_export_creates_parent_directories`
5. `test_export_overwrites_existing_file`
6. `test_export_rows_contain_store_nickname_not_only_cnpj`

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.

## Notas para o agente
- Não use `pandas`; é `csv` da stdlib.
- Não adicione BOM (`utf-8-sig`) sem pedido — se o usuário reclamar de acento no Excel, vira um ticket.
