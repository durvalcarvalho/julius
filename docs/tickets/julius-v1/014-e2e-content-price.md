# 014: Ponta a ponta — fixture sintético e fluxos completos pela CLI

> Prova que a DAG inteira funciona junta: importar → definir conteúdo → consultar mostra preço por unidade (caso dos ovos), além de renomear, fundir, exportar e reimportar via CLI.

## Contexto

Fecha o "Design de testes § 4" do `CLAUDE.md` (caso ilustrativo 20 × 30 ovos, que não existe nos dados reais) e exercita cada comando como o usuário usaria. Leia também "Preço por conteúdo" (achado real vs. caso ilustrativo — não confundir).

Depende de 009, 010, 013. Regras comuns: `index.md`.

## Escopo

### Dentro
- `tests/fixtures/synthetic_eggs.html` — HTML **mínimo** no mesmo formato da Receita/DF (mesmas âncoras que o parser usa), com: loja `MERCADO SINTETICO LTDA`, CNPJ `00.000.000/0001-91`, chave `5326 0900 0000 0000 0191 6500 1000 0000 0111 0000 0001` (44 dígitos), `Emissão: 01/09/2026 10:00:00`, dois itens `UN`: `OVOS BRANCOS C/20` (cód. `9001`, `12,00`) e `OVOS BRANCOS C/30` (cód. `9002`, `16,50`), `Qtd. total de itens: 2`.
- `tests/test_e2e.py`.

### Fora
- Qualquer código em `julius/`. Se um fluxo falhar, o conserto vai para o ticket da camada responsável — anote e pare.

## Requisitos

Todos via `CliRunner` com `JULIUS_DB` em `tmp_path`, sem `JULIUS_AI_*`.

1. `test_eggs_bigger_pack_is_cheaper_per_unit` — `importar synthetic_eggs.html`; obter ids via `produtos listar`; `definir-conteudo A 20 UN`, `definir-conteudo B 30 UN`; `consultar ovos` → tabela tem coluna `Por UN` com `0,60` e `0,55`; linha de `R$ 12,00` marcada como menor preço cru (é o que o destaque mede), e o texto `0,55` aparece na linha de `R$ 16,50` — o pacote maior é mais barato por unidade mesmo custando mais no total.
2. `test_real_data_has_no_flip_between_total_and_per_liter` — nível de serviço: após `importar qrcode.html`, `set_product_content` de Pepsi `2 L` e Guaraná `1.5 L`; `search_prices("refri")` → `price_per_content` do Guaraná (`4.99/1.5`) menor que o da Pepsi (`6.99/2`) **e** `unit_price` do Guaraná também menor — sem inversão nos dados reais, registrado para não reaparecer como bug.
3. `test_rename_store_shows_in_search` — `mercados renomear … "FL 3 Costa Águas Claras"` → `consultar picanha` mostra o apelido.
4. `test_merge_via_cli_unifies_history` — `importar qrcode.html qrcode-3.html`; `produtos fundir <tomate DdC> <tomate FL3> --sim`; `consultar tomate` mostra as duas datas sob um produto só.
5. `test_reimport_is_idempotent_end_to_end` — segunda importação reporta `já existiam`; `exportar` continua com 20 linhas.
6. `test_import_all_five_real_receipts_and_export` — 86 linhas exportadas; `consultar banana` acha `BANANA PRATA kg` (Assaí) por `KG`.
7. `test_unknown_unit_receipt_fails_loudly_and_writes_nothing` — cópia de fixture com `KG`→`LT`; CLI exit 1, mensagem cita `'LT'`, `exportar` → 0 linhas.

## Especificação técnica

```
criar tests/fixtures/synthetic_eggs.html
criar tests/test_e2e.py
```

Para achar ids na saída de `produtos listar`, use regex sobre o texto da tabela — não consulte o banco direto neste arquivo (o objetivo é o caminho do usuário).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `synthetic_eggs.html` passa por `DFReceiptParser` sem nenhum caso especial no parser.

## Notas para o agente
- Se o fixture sintético exigir mudar o parser, o fixture está errado — copie a estrutura de `qrcode-2.html` (1 item) e edite os valores.
- Não teste cor/ANSI; `CliRunner` desabilita cor. Teste texto.
