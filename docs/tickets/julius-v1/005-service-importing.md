# 005: Serviço importing

> `import_receipt(conn, path, parser)` lê um HTML, parseia inteiro e grava loja + produtos + preços numa única transação, de forma idempotente.

## Contexto

Primeiro caso de uso de escrita. Orquestra `parsers.df` (001) e os repositórios `stores` (002), `products` (003), `prices` (004). Leia no `CLAUDE.md`: "Identidade de produto e busca § 1" (produto nasce automaticamente por SKU, sem perguntar nada), "Design de testes § 2", "Estrutura de pacote" (assinatura e regra "uma transação por arquivo").

Depende de 001, 002, 003, 004. Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/services/importing.py` com `import_receipt(conn, path: Path, parser: ReceiptParser) -> ImportResult`.
- `tests/test_services_importing.py`.

### Fora
- Iterar sobre vários arquivos e imprimir por arquivo → 009 (CLI). Sugestão de conteúdo/tags via IA no import → 012 deixa pronta, ninguém chama ainda. Qualquer heurística sobre a descrição.

## Requisitos

### Funcionais
- Lê `path.read_text(encoding="utf-8")`, chama `parser.parse(html, source=path.name)`. **Só depois** do parse completo abre a transação (`with conn:`): `stores.ensure_store`, e para cada item `products.resolve_product_id` + `prices.insert_price`; conta `new_items` (retornou `True`) e `existing_items` (`False`).
- Reimportar o mesmo arquivo: `ImportResult(new_items=0, existing_items=N)` e nenhuma linha nova em tabela alguma.
- Não altera `nickname` de loja já existente, nem `canonical_name` de produto já existente.

### Validação e erros
- Arquivo inexistente → `FileNotFoundError` propaga (mensagem do próprio Python já cita o caminho).
- `ReceiptParseError` / `UnknownUnitError` propagam **antes** de qualquer escrita — o banco fica exatamente como estava (nem a loja é criada).
- Falha de FK/`IntegrityError` no meio dos inserts → a transação faz rollback (garantido pelo `with conn:`); o erro propaga.

## Especificação técnica

```
criar julius/services/importing.py
criar tests/test_services_importing.py
```

Imports permitidos: `pathlib`, `sqlite3`, `julius.domain.models`, `julius.parsers`, `julius.repositories.*`. Nada de `typer`/`rich`/`print`.

## Testes obrigatórios (usar `DFReceiptParser` real + fixtures reais)

1. `test_import_single_receipt` — `qrcode.html` → `ImportResult(20, 0)`; `stores` 1 linha, `products` 15, `prices` 20.
2. `test_reimport_is_idempotent` — segunda chamada → `(0, 20)`; contagens iguais.
3. `test_import_three_receipts_accumulates` — `qrcode.html`, `qrcode-2.html`, `qrcode-3.html` → 3 lojas, 21 produtos, 27 preços.
4. `test_import_all_five_fixtures` — inclui `qrcode-4.html` e `qrcode-5.html`; `prices` = 20+1+6+12+47 = 86; nenhum `unit` fora de `{UN, KG}`.
5. `test_nickname_survives_reimport` — `rename_store` entre dois imports; apelido mantido.
6. `test_same_sku_reuses_product_across_imports` — reimportar não cria produto novo.
7. `test_parse_error_writes_nothing` — arquivo em `tmp_path` com HTML inválido → `ReceiptParseError`; `count(prices) == 0` e `stores` vazio.
8. `test_unknown_unit_writes_nothing` — cópia de `qrcode-2.html` com `KG` trocado por `LT` via `str.replace` → `UnknownUnitError`; nada gravado.
9. `test_missing_file_raises_file_not_found`

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] Nenhum `commit()` explícito: transação só via `with conn:`.

## Notas para o agente
- A ordem "parse tudo → depois grava" é o que garante o teste 7/8; não abra `with conn:` antes do `parser.parse`.
- Não deduplique por conta própria (sem `SELECT` antes do insert) — `INSERT OR IGNORE` + `rowcount` em `prices.insert_price` já é a regra.
