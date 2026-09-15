# 001: Parser DF

> `julius/parsers/df.py` transforma o HTML salvo da NFC-e da Receita/DF num `Receipt`, com todos os itens normalizados, validado contra os 5 recibos reais.

## Contexto

Único ponto do sistema que conhece o layout HTML de um estado. Implementa o `Protocol ReceiptParser` já existente em `julius/parsers/__init__.py`. Tudo o que produz já sai normalizado via `julius/domain/normalization.py` (existente e testado). Leia no `CLAUDE.md`: "Contrato do parser", "Fatos e pegadinhas do domínio", "Design de testes § 1".

Sem dependência de outro ticket. Regras comuns: `index.md`.

## Escopo

### Dentro
- `class DFReceiptParser` com `parse(self, html: str, source: str = "") -> Receipt`.
- `class ReceiptParseError(ValueError)` em `julius/parsers/__init__.py` (compartilhada por qualquer parser futuro).
- Copiar `~/.local/share/julius/entrada/qrcode-4.html` e `qrcode-5.html` para `tests/fixtures/` (só o `.html`, nunca a pasta `*_files/`).
- `tests/test_parser_df.py`.

### Fora
- Gravar no banco (→ 005). Detecção automática de estado. Qualquer campo não listado no contrato (Consumidor/CPF, forma de pagamento, tributos). BeautifulSoup ou qualquer dependência nova — é `re` + `html.unescape` da stdlib.

## Requisitos

### Funcionais
- Item = bloco que contém o marcador `(Cód: N)` seguido dos rótulos `Qtde.:`, `UN:`, `Vl. Unit.:` e do valor total no `<div class="col-3">` seguinte. Blocos de "Qtd. total de itens", "Valor a pagar", "Forma de pagamento", "Tributos" também são `li.list-group-item` — **não** têm `(Cód:` e não podem virar item. DOM injetado por extensão (`plasmo-csui`) é ignorado pelo mesmo critério.
- `ReceiptItem.index` é 1-based na ordem em que os itens aparecem no HTML; código repetido gera itens distintos (nunca soma).
- `description`: texto antes de `<small>`, com `html.unescape`, espaços colapsados/aparados, **sem** alterar caixa.
- `quantity`, `unit_price`, `total_price`: via `parse_decimal_br` — nunca `replace(",", ".")` na linha inteira.
- `unit`: via `normalize_sale_unit(raw, description=..., source=source)`.
- Cabeçalho: `store_legal_name` = texto do primeiro `<div class="col" style="font-weight: bold;">` dentro do card `heading1`; `store_cnpj` = `digits_only` do trecho após `CNPJ:` (14 dígitos); `access_key` = `digits_only` do `<p class="h6">` que segue `Chave de acesso:` (44 dígitos); `issued_at` = data/hora após `Emissão:` convertida de `DD/MM/AAAA HH:MM:SS` para `AAAA-MM-DDTHH:MM:SS`. Nunca usar "Data/Hora da Consulta".
- Cross-check: o número em "Qtd. total de itens" deve ser igual à contagem de itens extraídos.

### Validação e erros
- Qualquer campo de cabeçalho ausente, zero itens, CNPJ ≠ 14 dígitos, chave ≠ 44 dígitos ou cross-check divergente → `ReceiptParseError` com mensagem citando o campo e `source`.
- Unidade fora de `UNIT_MAP` → deixa `UnknownUnitError` propagar (já traz código, descrição e `source`).
- Sem I/O: `parse` recebe string; ler arquivo é responsabilidade de quem chama.

## Especificação técnica

### Arquivos
```
criar     julius/parsers/df.py
modificar julius/parsers/__init__.py      # + ReceiptParseError
criar     tests/test_parser_df.py
copiar    tests/fixtures/qrcode-4.html, tests/fixtures/qrcode-5.html
```

### Valores que os testes fixam

| fixture | `store_legal_name` | `store_cnpj` | itens | SKUs distintos | `issued_at` | códigos de unidade brutos |
|---|---|---|---|---|---|---|
| `qrcode.html` | FL 3 COSTA MULTICANAL S A | 27289076001379 | 20 | 15 | 2026-09-12T13:09:16 | `UN1`, `KG1` |
| `qrcode-2.html` | COMERCIAL DE ALIMENTOS HTP LTDA | 20209736000181 | 1 | 1 | 2026-09-05T16:50:34 | `KG` |
| `qrcode-3.html` | DONA DE CASA S/A | 11832478000285 | 6 | 5 | 2026-09-07T18:18:30 | `UN`, `KG` |
| `qrcode-4.html` | DONA DE CASA S/A | 11832478000366 | 12 | 10 | 2026-09-10T10:03:56 | `UN`, `KG` |
| `qrcode-5.html` | SENDAS DISTRIBUIDORA S/A | 06057223052643 | 47 | — | 2026-09-04T17:51:40 | `Un`, `Kg`, `PC`, `Gf` |

Chaves: `qrcode.html` → `53260927289076001379652060002038951930768277`; `qrcode-5.html` → `53260906057223052643650110001955171111265303` (as outras estão no próprio HTML, no bloco "Chave de acesso").

## Testes obrigatórios (`tests/test_parser_df.py`)

1. `test_item_count_matches_receipt_total` — parametrizado nos 5 fixtures: `len(receipt.items)` igual à coluna "itens".
2. `test_header_fields` — parametrizado: nome, CNPJ, `issued_at`, chave com 44 dígitos.
3. `test_repeated_code_yields_distinct_items` — `qrcode.html` cód. 14578 aparece 3× com `index` diferentes; `qrcode-4.html` cód. 29507 3×.
4. `test_units_are_normalized_across_all_spellings` — `qrcode-5.html` só tem `unit in {"UN","KG"}`; `AC MASC F TER ES 1kg` (cód. 1057154) tem `unit == "UN"` e `unit_price == 14.85`; `MANGA ROSA kg` tem `unit == "KG"`.
5. `test_decimal_separators_do_not_leak_between_fields` — `qrcode-2.html`: `quantity == 1.532`, `unit_price == 53.99`, `total_price == 82.71`.
6. `test_weighed_item` — `qrcode.html` `LING FGO RESF AURORA kg` (1ª ocorrência): `quantity == 0.578`, `unit == "KG"`, `total_price == 17.33`.
7. `test_issued_at_is_not_the_consultation_timestamp` — nenhum `issued_at` termina com o horário de "Data/Hora da Consulta" do rodapé do respectivo arquivo.
8. `test_summary_blocks_are_not_items` — nenhuma `description` contém "Valor a pagar", "Qtd. total", "Forma de pagamento" ou "Tributos".
9. `test_unknown_unit_raises_with_source` — HTML mínimo sintético (string no teste) com `UN: LT` → `UnknownUnitError` cuja mensagem contém `'LT'` e o `source`.
10. `test_missing_header_raises_parse_error` — HTML sem bloco "Chave de acesso" → `ReceiptParseError` citando o campo.
11. `test_no_items_raises_parse_error` — HTML só com cabeçalho → `ReceiptParseError`.
12. `test_item_count_mismatch_raises` — fixture real com o número de "Qtd. total de itens" alterado por `str.replace` → `ReceiptParseError`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `parse` não faz I/O; `julius/parsers/df.py` importa só `re`, `html`, `julius.domain.*`, `julius.parsers`.
- [ ] Nenhum identificador em português no código; mensagens de erro podem ser em português.

## Notas para o agente
- Use `re.DOTALL` e âncoras de conteúdo (`(Cód:`, `Qtde.:`), nunca posição de `<ul>`.
- `qrcode-5.html` tem 1851 linhas; abra por trechos se precisar inspecionar.
- Não "melhore" `UNIT_MAP` para passar teste — se um código real não estiver lá, é bug de dado a reportar, não de mapa.
