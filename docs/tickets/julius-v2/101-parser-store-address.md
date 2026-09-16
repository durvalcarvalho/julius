# 101: Parser — endereço do mercado

> `DFReceiptParser` extrai o endereço impresso no cabeçalho da nota e o devolve em `Receipt.store_address`.

## Contexto

O usuário quer saber **onde** cada preço foi pago ("para saber onde ir pegar o preço barato"). Hoje a nota só rende razão social e CNPJ. Prova de que endereço distingue filiais: Dona de Casa `0002-85` fica na QUADRA QE 30, Guará II; `0003-66` na QUADRA QR 5, Candangolândia. Leia `docs/design/ai-v2.md` §0 (linha "Endereço"), §4.1 e §4.8 (tabela dos 5 endereços já medidos).

Sem dependências. Regras comuns: `index.md`.

## Escopo

### Dentro
- `julius/domain/models.py`: `Receipt.store_address: str | None = None` (último campo — dataclass frozen com default depois dos obrigatórios).
- `julius/parsers/df.py`: `_ADDRESS` e uso em `parse`.
- `tests/test_parser_df.py`.

### Fora
- Gravar no banco (→ 102). Mostrar na CLI (→ 111). Heurística de bairro (não existe: o texto inteiro é guardado). Qualquer outra mudança no parser.

## Requisitos

### Funcionais
- `_ADDRESS = re.compile(r"CNPJ:\s*[\d./-]+\s*</div>\s*<div>(.*?)</div>", re.DOTALL)` — o `<div>` imediatamente após o do CNPJ no cabeçalho (`#heading1`). Grupo 1 passa por `_clean` (unescape + colapsar espaços), resultado tipo `QUADRA QE 30, 02/39, LJS 02/39, GUARA II, BRASILIA, DF`.
- Sem match, ou string vazia após `_clean` → `store_address=None`, **sem** `ReceiptParseError`: endereço é conforto, nunca pode parar um import.
- Não normalizar caixa, vírgulas duplas (`", ,"`) nem acentos: `Q SMAS Trecho 03, 0, , St Complementares, Brasilia, DF` fica exatamente assim. É texto de exibição, não chave.

### Validação e erros
- Nenhuma além das acima. Os demais campos continuam obrigatórios como hoje.

## Especificação técnica

```
modificar julius/domain/models.py     (Receipt.store_address)
modificar julius/parsers/df.py        (_ADDRESS; store_address=... no construtor de Receipt)
modificar tests/test_parser_df.py
```

Valores esperados (medidos com o regex acima, `_clean` aplicado):

| fixture | `store_address` |
|---|---|
| `qrcode.html` | `A ADE CONJUNTO 31 LOTE 01 SALA 1, S /N, LOTE 01, AGUAS CLARAS, BRASILIA, DF` |
| `qrcode-2.html` | `Q. QE 15 LOTE A, 0, , GUARA II, BRASILIA, DF` |
| `qrcode-3.html` | `QUADRA QE 30, 02/39, LJS 02/39, GUARA II, BRASILIA, DF` |
| `qrcode-4.html` | `QUADRA QR 5, 05 MU 05, , CANDANGOLANDIA, BRASILIA, DF` |
| `qrcode-5.html` | `Q SMAS Trecho 03, 0, , St Complementares, Brasilia, DF` |

## Testes obrigatórios (`tests/test_parser_df.py`)

1. `test_store_address_matches_each_real_receipt` — parametrizado nos 5 fixtures com a tabela acima.
2. `test_store_address_is_none_when_header_block_is_missing` — pegue `qrcode-3.html`, remova por `str.replace` o `<div>` do endereço (deixe o do CNPJ), parseie: `store_address is None` e `len(items) == 6`.
3. `test_store_address_unescapes_and_collapses_whitespace` — substitua o endereço de `qrcode-3.html` por `"RUA A &amp; B,\n   10"` → `"RUA A & B, 10"`.
4. `test_synthetic_fixture_still_parses` — `synthetic_eggs.html` parseia sem erro (o valor de `store_address` é o que o fixture tiver; a asserção é só não quebrar).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (253 + novos).
- [ ] `grep -n "store_address" julius/parsers/df.py julius/domain/models.py` mostra o campo e o uso; nenhum outro arquivo de `julius/` tocado.

## Notas para o agente
- Não troque regex por BeautifulSoup nem "melhore" outros regexes do parser — fora de escopo.
- O campo tem default `None` porque `Receipt` é frozen e outros construtores (testes de repositórios) o instanciam sem endereço.
