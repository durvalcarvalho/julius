# Julius v1 — Tickets de implementação

> Gerado a partir de: `CLAUDE.md` (design v1, seções "Design (v1)" e "Design de testes")
> Gerado em: 2026-09-15 · Estado do código no commit `ace2cdf`

## Visão geral

Julius é um CLI pessoal que importa recibos NFC-e (HTML salvo da Receita/DF), guarda cada item comprado num SQLite e responde "esse preço tá caro?" listando o histórico por produto e por mercado. As camadas-folha já existem e estão testadas (`config`, `domain`, `infra/db`, os `Protocol`s, o `app` Typer vazio). Estes tickets preenchem o resto **como uma DAG**: primeiro nós sem dependência interna (parser, repositórios), depois serviços, depois CLI, depois a camada opcional de IA, e por fim um teste ponta a ponta.

Trilha única — o projeto não tem frontend. A ordem numérica já respeita as dependências: um ticket só depende de números menores.

## Decisões aplicadas (vêm do `CLAUDE.md`, não rediscutir dentro de ticket)

- Identificadores em inglês; português só em nomes de comando do CLI, `--help` e mensagens.
- Repositórios são **funções** `(conn, ...)` em módulos por agregado — sem classes, sem ABC. Serviços são funções. `Protocol` só em `ReceiptParser` e `LlmClient`.
- Regras de negócio (nunca misturar UN com KG, `highlight` por unidade, normalização de tag/conteúdo) vivem em `services/`, nunca em `repositories/` nem em `cli/`.
- IA nunca lança exceção, nunca roda em `consultar`, só em `importar` e `produtos comparar`.
- Import é **por arquivo**: `import_receipt(conn, path, parser)`; a CLI itera.
- Nenhum stub `NotImplementedError` — o que não existe, não existe.

## Regras comuns a todo ticket

1. Leia `CLAUDE.md` inteiro antes de começar; as seções citadas em cada ticket são o mínimo.
2. Só toque nos arquivos listados no ticket. Se precisar de algo de outra camada que não existe, **pare e anote** — não crie fora do escopo.
3. Respeite `tests/test_architecture.py` (regras de import entre camadas). Se ele falhar, o desenho está errado, não o teste.
4. Teste de caminho feliz **e** triste para cada função pública. SQLite real em `tmp_path` (fixtures `db_path`/`conn` de `tests/conftest.py`); rede sempre substituída por fake.
5. Sem comentários narrando código; docstring só quando o *porquê* não é óbvio.
6. Aceite = `.venv/bin/pytest -q` totalmente verde (suíte inteira, não só o arquivo novo) + `grep -rn NotImplementedError julius` vazio.
7. Ao terminar, marque o ticket como `feito` na tabela abaixo e faça um commit só dele.

## Trilha

| # | Ticket | Depende de | Esforço | Estado | Entrega |
|---|---|---|---|---|---|
| 001 | [Parser DF](001-parser-df.md) | — | M | feito | `parsers/df.py` lendo os 5 HTMLs reais |
| 002 | [Repositório stores](002-repository-stores.md) | — | S | feito | `repositories/stores.py` |
| 003 | [Repositório products](003-repository-products.md) | — | M | feito | `repositories/products.py` (SKUs, tags, conteúdo) |
| 004 | [Repositório prices](004-repository-prices.md) | 002, 003 | S | feito | `repositories/prices.py` (inserção idempotente, consulta, export) |
| 005 | [Serviço importing](005-service-importing.md) | 001–004 | M | feito | `services/importing.py` |
| 006 | [Serviço search](006-service-search.md) | 003, 004 | M | feito (cutoff 70) | `services/search.py` (rapidfuzz, highlight por unidade) |
| 007 | [Serviço catalog](007-service-catalog.md) | 002–004 | M | feito (sem compare_products → 013) | `services/catalog.py` (renomear, fundir, tag, conteúdo) |
| 008 | [Serviço export](008-service-export.md) | 004 | S | feito | `services/export.py` |
| 009 | [CLI recibos](009-cli-receipts.md) | 005, 006, 008 | M | feito | `julius importar / consultar / exportar` |
| 010 | [CLI catálogo](010-cli-catalog.md) | 007 | S | feito | `julius mercados … / produtos …` |
| 011 | [Cliente HTTP de LLM](011-llm-http-client.md) | — | S | feito | `infra/llm_client.py` → `HttpLlmClient` |
| 012 | [Serviço suggestions](012-service-suggestions.md) | 011 | M | feito | `services/suggestions.py` + `repositories/ai_usage.py` |
| 013 | [Comparar produtos](013-compare-products.md) | 007, 010, 012 | S | feito | `catalog.compare_products` + `julius produtos comparar` |
| 014 | [Ponta a ponta](014-e2e-content-price.md) | 009, 010, 013 | M | feito | fixture sintético + fluxos completos via CLI |
| 015 | [Serviço guidance](015-service-guidance.md) | 005, 006 | M | pendente | `Hint`/`HintKind`, `guidance.py`, `search.closest_names`, `ImportResult.new_product_ids` |
| 016 | [CLI dicas](016-cli-hints.md) | 015 | S | pendente | `cli/_hints.py` + dicas em `consultar`, `importar`, `comparar` |

Esforço: S ≈ até 1h, M ≈ 1–3h de trabalho humano equivalente.

## DAG

```
001 parser ─────────┐
002 stores ──┐      ├─► 005 importing ─┐
003 products ┼─► 004 prices            ├─► 009 cli-receipts ─┐
             │      ├─► 006 search ────┘                     │
             │      └─► 008 export ────┘                     ├─► 014 e2e
             └─────────► 007 catalog ──► 010 cli-catalog ────┤
011 llm-http ──► 012 suggestions ──► 013 compare ────────────┘
```

Paralelizável: {001, 002, 003, 011} desde o início; {006, 007, 008} após 004; 012 após 011.

## Caminho crítico

001 → 004 → 005 → 009 → 014 (importar e consultar funcionando de ponta a ponta). Tudo de IA (011–013) é opcional para o produto funcionar.

## Fases

- **A — folhas**: 001, 002, 003, 004
- **B — serviços**: 005, 006, 007, 008
- **C — CLI utilizável**: 009, 010
- **D — IA opcional**: 011, 012, 013
- **E — integração**: 014
- **v1.1 — dicas de uso** (ver `CLAUDE.md` § "Dicas de uso"): 015 → 016

## Riscos e mitigações

- **Layout do HTML da Receita muda** → parser regex quebra. Mitigação: `ReceiptParseError` claro + cross-check com "Qtd. total de itens" (001); fixtures reais versionados.
- **Código de unidade novo** (`LT`, `CX`…) → `UnknownUnitError` para o import inteiro daquele arquivo, nada gravado; corrigir é uma linha em `UNIT_MAP` (já implementado).
- **Fuzzy match com cutoff errado** → resultados demais ou de menos. Mitigação: cutoff é constante nomeada com testes de "pcanha" acha e "hortifruti" não acha (006).
- **Orçamento de IA estourar** → contador persistido em `ai_usage`, checado antes de cada chamada (012).
- **Agente "conserta" arquitetura para passar** → `test_architecture.py` é intocável; regra 3.

## Questões em aberto (assumidas assim nos tickets)

- `julius produtos pendentes` — **não incluído**; adicionar depois se fizer falta.
- Dica automática via padrão `C/<n>` no import — **não incluída**; 012 deixa `suggest_content` pronta para ser chamada, mas ninguém a chama no import ainda.
- Provedor/modelo de LLM — não fixado; `HttpLlmClient` fala `/chat/completions` genérico, configuração toda por env.
- Cutoff do rapidfuzz — chute inicial 75 em 006; o teste decide.
