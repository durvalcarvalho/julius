# 102: Migração 0002 — `stores.address` e categorias semeadas

> Primeira migração real do projeto: coluna `address` em `stores`, 13 tags-categoria semeadas; `ensure_store` faz upsert só do endereço; `import_receipt` passa o endereço da nota.

## Contexto

`docs/design/ai-v2.md` §3 (SQL), §4.8 (`ensure_store`), §0 (decisão "Tags": a lista fixa de categorias vive **no banco**, na própria tabela `tags`, para a IA preferir e o usuário estender com `produtos tag`). É a primeira vez que o mecanismo de `PRAGMA user_version` + backup roda num banco com dados de verdade (`CLAUDE.md` § "Migração de schema").

Depende de 101 (`Receipt.store_address`). Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/infra/migrations/0002_store_address_and_seed_tags.sql`.
- `julius/domain/models.py`: `Store.address: str | None = None`.
- `julius/repositories/stores.py`: `ensure_store(conn, cnpj, legal_name, address: str | None = None)` com upsert do endereço; `get_store`/`list_stores` devolvem `address`.
- `julius/services/importing.py`: passa `receipt.store_address` para `ensure_store`.
- Testes: `tests/test_db.py`, `tests/test_repositories_stores.py`, `tests/test_services_importing.py`.

### Fora
- `prices`/CSV com endereço (→ 103). CLI (→ 111). Comando para apagar/renomear tags semeadas (não existe; `sqlite3` direto).

## Requisitos

### Funcionais
- Conteúdo exato da migração:
  ```sql
  -- Address as printed on the receipt header; NULL until a receipt of that store is (re)imported.
  ALTER TABLE stores ADD COLUMN address TEXT;

  -- Aisle categories the AI is asked to prefer. Users add more with `julius produtos tag`.
  INSERT OR IGNORE INTO tags (name) VALUES
      ('hortifruti'), ('carnes'), ('frios'), ('laticinios'), ('padaria'), ('mercearia'),
      ('bebidas'), ('limpeza'), ('higiene'), ('congelados'), ('temperos'), ('doces'), ('utilidades');
  ```
  Minúsculas e sem acento de propósito: `consultar --tag` só faz `.lower()`, não tira acento.
- Banco novo: `db.connect` aplica 0001 e 0002 em sequência, `user_version == 2`, **sem** arquivo `.bak`.
- Banco em v1 com dados: `db.connect` cria `prices.db.bak-v1`, aplica 0002, `user_version == 2`, todas as linhas de `stores`/`products`/`prices` intactas, `address IS NULL` nas lojas antigas.
- `ensure_store`:
  ```sql
  INSERT INTO stores (cnpj, legal_name, nickname, address) VALUES (?, ?, ?, ?)
  ON CONFLICT(cnpj) DO UPDATE SET address = COALESCE(excluded.address, stores.address)
  ```
  Loja nova nasce com `nickname = legal_name` (como hoje). Loja existente: **só** `address` muda, e só se o novo não for `NULL`; `nickname` e `legal_name` nunca são tocados.
- `import_receipt` chama `stores.ensure_store(conn, receipt.store_cnpj, receipt.store_legal_name, receipt.store_address)`. Reimportar os HTMLs antigos é o backfill oficial do endereço.

### Validação e erros
- Nenhuma nova. `test_shipped_migrations_start_at_one_and_are_contiguous` continua valendo.

## Especificação técnica

```
criar     julius/infra/migrations/0002_store_address_and_seed_tags.sql
modificar julius/domain/models.py            (Store.address)
modificar julius/repositories/stores.py      (ensure_store, _to_store, SELECTs)
modificar julius/services/importing.py       (1 linha)
modificar tests/test_db.py
modificar tests/test_repositories_stores.py
modificar tests/test_services_importing.py
```

Dois testes existentes **quebram de propósito** e devem ser ajustados neste ticket:
- `test_pending_migration_backs_up_existing_db_then_applies_it` usa `(2, extra)` — agora existe um 0002 real. Passe a usar `(3, extra)`, espere `user_version == 3` e backup `prices.db.bak-v2`. Ele também faz `INSERT INTO stores VALUES ('1', 'Legal', 'Nick')` positional (3 valores para 4 colunas): nomeie as colunas.
- Em `test_repositories_stores.py`, `Store(cnpj=…, legal_name=…, nickname=…)` continua válido (default `None`), mas a igualdade agora inclui `address`.

## Testes obrigatórios

1. `test_db.py::test_fresh_db_is_at_version_two_with_address_column_and_seed_tags` — `PRAGMA table_info(stores)` tem `address`; `SELECT count(*) FROM tags == 13`; nenhum `*.bak-*` na pasta.
2. `test_db.py::test_upgrading_a_v1_db_backs_up_and_keeps_rows` — abra `sqlite3.connect(db_path)` cru, aplique só `db.available_migrations()[0]` via `db.apply_migrations(conn, db_path, [primeira])`, insira 1 loja, 1 produto, 1 preço, feche. `db.connect(db_path)` → versão 2, `prices.db.bak-v1` existe com versão 1 e sem coluna `address`, contagens iguais no banco novo, `address IS NULL`.
3. `test_db.py::test_pending_migration_backs_up_existing_db_then_applies_it` — ajustado como descrito.
4. `test_repositories_stores.py::test_ensure_store_records_address_on_create` — `Store(..., address="QUADRA QE 30, …")`.
5. `test_ensure_store_fills_missing_address_without_touching_nickname` — cria sem endereço, renomeia, chama de novo com endereço → endereço preenchido, apelido editado mantido.
6. `test_ensure_store_keeps_existing_address_when_new_is_none`.
7. `test_ensure_store_never_overwrites_edited_nickname` — existente; deve continuar verde (e `legal_name` também não muda).
8. `test_services_importing.py::test_import_receipt_stores_the_address` — `qrcode-3.html` → `get_store(...).address` termina em `GUARA II, BRASILIA, DF`; importar `qrcode-4.html` → segunda loja com `CANDANGOLANDIA`; reimportar `qrcode-3.html` não altera nada.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] Rodar manualmente contra uma **cópia** do banco real (`JULIUS_DB=/tmp/copia.db julius mercados listar`) cria `copia.db.bak-v1` e não perde linhas — anote o resultado no commit.
- [ ] `grep -c "INSERT OR IGNORE INTO stores" julius/repositories/stores.py` == 0 (o upsert substituiu).

## Notas para o agente
- Não coloque DDL em string Python: migração é `.sql` na pasta, `package-data` já inclui `*.sql`.
- Não invente coluna `neighborhood`: o design guarda o endereço inteiro e ponto.
- `INSERT OR IGNORE` nas tags: o usuário pode já ter criado `limpeza` à mão antes de migrar.
