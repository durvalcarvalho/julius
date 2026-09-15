# 002: Repositório stores

> Funções de persistência do agregado **Store** (tabela `stores`), sem regra de negócio.

## Contexto

Camada `repositories` (L2): SQL entra, `Store` (de `julius/domain/models.py`) sai. Schema já existe em `julius/infra/migrations/0001_initial_schema.sql`; conexão via fixture `conn` de `tests/conftest.py` (FKs ligadas, `row_factory=sqlite3.Row`). Leia no `CLAUDE.md`: "Armazenamento", "Estrutura de pacote" (regras da DAG e agregados).

Sem dependência de outro ticket. Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/repositories/stores.py` e `tests/test_repositories_stores.py`.

### Fora
- Normalizar/validar apelido (strip, vazio) — isso é do serviço (→ 007). Listar produtos por loja. Qualquer coisa que toque `prices`/`products`.

## Requisitos

### Funcionais
- `ensure_store(conn, cnpj: str, legal_name: str) -> None` — `INSERT OR IGNORE`; ao criar, `nickname = legal_name`. Chamar de novo com mesmo CNPJ **nunca** altera `legal_name` nem `nickname` já gravados.
- `list_stores(conn) -> list[Store]` — ordenado por `nickname` (collation padrão), depois `cnpj`.
- `rename_store(conn, cnpj: str, nickname: str) -> None` — `UPDATE`; se `rowcount == 0` → `LookupError(f"store {cnpj} not found")`.
- `get_store(conn, cnpj: str) -> Store | None`.
- Nenhuma função faz `commit`; quem controla transação é o chamador (serviços usam `with conn:`).

### Validação e erros
- Nenhuma validação de formato aqui (CNPJ já chega com 14 dígitos do parser). Só `LookupError` acima.

## Especificação técnica

```
criar julius/repositories/stores.py
criar tests/test_repositories_stores.py
```

Todas as funções recebem `conn: sqlite3.Connection` como primeiro argumento. Construir `Store` a partir de `sqlite3.Row` por nome de coluna (`row["legal_name"]`), nunca por posição.

## Testes obrigatórios

1. `test_ensure_store_creates_with_nickname_equal_to_legal_name`
2. `test_ensure_store_twice_is_idempotent` — 1 linha, contagem inalterada.
3. `test_ensure_store_never_overwrites_edited_nickname` — `rename_store` depois `ensure_store` com `legal_name` diferente: `nickname` e `legal_name` continuam os originais.
4. `test_list_stores_orders_by_nickname`
5. `test_list_stores_empty_returns_empty_list`
6. `test_rename_store_updates_nickname`
7. `test_rename_store_unknown_cnpj_raises_lookup_error`
8. `test_get_store_returns_none_when_missing`

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `julius/repositories/stores.py` importa só `sqlite3` e `julius.domain.models`.

## Notas para o agente
- `sqlite3.Row` já está configurado em `infra.db.connect`; não reconfigure na função.
- Sem classes `StoreRepository` — são funções de módulo, por decisão de design.
