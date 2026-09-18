# 164: `bot/render.py` — os fatos que a narração pode citar

<!-- status:done -->
<!-- adjustments: revisado em 18/09/2026 a partir de feedback real do usuário -- records_facts e
comparison_facts ganharam (a) a unidade de venda por extenso em cada linha ("o quilo"/"a
unidade"/"o litro", dict _UNIT_PHRASES) porque a IA não tinha como afirmar isso com confiança sem
o dado explícito, e (b) uma linha final com a diferença entre o mais barato e o mais caro, já
calculada aqui em Python -- é o que permite ao prompt v2 (ticket 163) citar essa diferença sem
fazer conta nova. search_fallback_line/compare_fallback_line (165) ganharam a mesma unidade e
diferença, por consistência e porque é uma subtração determinística, sem custo de IA. -->

> Para cada saída de leitura, uma função irmã de `render_X` que devolve texto plano (sem HTML, sem `<pre>`) com só os valores já calculados — é o material que `narrate` (ticket 163) recebe e contra o qual a guarda de dinheiro compara.

## Contexto

Parte do design "voz do Julius no bot (v2.7)". Independente do 163 (não chama IA, não importa `suggestions`) e do 165 (frases-molde são função separada) — pode ser feito em paralelo com os dois.

`render.py` já segue esse padrão de "duas saídas, mesmos dados" (é o próprio motivo do arquivo existir, ver seu docstring). Este ticket estende o padrão às quatro leituras.

## Escopo

### Dentro
- `records_facts(records: Sequence[PriceRecord], *, today: date | None = None) -> str` — uma linha por registro: `"{nome} · {preço}[ · {preço por conteúdo}][ (mais barato|mais caro)] · {data} ({idade relativa}) · {mercado}"`. Sem HTML, sem agrupar por unidade (quem decide se usa isso é o ticket 167).
- `comparison_facts(comparison: StoreComparison, *, today: date | None = None) -> str` — uma linha por grupo por entrada: `"{tipo} · {mercado} · {preço} · {data} ({idade relativa})"`, reaproveitando `_MARKERS`-equivalente em texto (`"(mais barato)"`/`"(mais caro)"` no lugar de ▼/▲) por grupo, como `_comparison_block` já faz para o HTML.
- `products_facts(products: Sequence[Product]) -> str` — uma linha: `"{n} produtos no catálogo"` (mais, se fizer sentido sem inflar o prompt, contagem de quantos têm tipo/conteúdo definidos — não é obrigatório).
- `stores_facts(stores: Sequence[Store]) -> str` — uma linha: `"{n} mercados importados"`.
- Todas as quatro devolvem `""` para entrada vazia (nunca `"Nenhum resultado."` nem qualquer outra frase — isso é responsabilidade de `render_X`, não de `_facts`).

### Fora
- Frases-molde determinísticas de fallback (→ 165).
- Qualquer chamada a `narrate`/`suggestions` (→ 167, 168) — este módulo não pode importar `pydantic_ai` nem `suggestions` (o próprio docstring do arquivo já proíbe `pydantic_ai`; `suggestions` também não deve entrar aqui, a chamada de IA é responsabilidade de `turn.py`).
- Mudar qualquer `render_X` existente.

## Requisitos

### Funcionais
- Texto plano: nenhuma das quatro funções chama `escape()` — não vai para o Telegram diretamente, só para dentro de um prompt.
- `records_facts`/`comparison_facts` aceitam `today` pela mesma razão que `render_records`/`render_comparison` aceitam: teste de faixa de `relative_age` não pode depender do dia em que roda.
- `comparison_facts` usa a mesma base de comparação que `_comparison_block` já decidiu (`group.basis`, `group.entries` ordenados) — não recalcula nada, só reformata em texto.

### Validação e erros
- Nenhuma das quatro lança para entrada vazia; todas devolvem `""`.
- `records_facts`/`comparison_facts` não quebram com `price_per_content is None` (mesmo condicional que `_record_line` já usa).

## Especificação técnica

```
modificar julius/bot/render.py       — records_facts, comparison_facts, products_facts, stores_facts
modificar tests/test_bot_render.py   — testes das quatro
```

### Padrão a seguir
- `_record_line`/`_comparison_block` (mesmo arquivo): mesma fonte de dados, reformatada em texto puro em vez de HTML — não recalcule `highlight`/`basis`, eles já vêm prontos em `PriceRecord`/`KindComparison`.
- `money`/`br_date`/`relative_age` de `domain/formatting.py`, já importados neste arquivo.

## Testes obrigatórios

1. `test_records_facts_one_line_per_record_no_html` — uma linha, sem `<`/`>`, com marcador `(mais barato)` quando `highlight="lowest"`.
2. `test_records_facts_carries_content_price` — `price_per_content` aparece como `"R$ X,XX/UN"` quando definido.
3. `test_records_facts_empty_is_empty_string`.
4. `test_comparison_facts_one_line_per_entry_with_markers` — cheapest/dearest marcados, meio sem marca.
5. `test_comparison_facts_empty_is_empty_string` (`comparisons=()`).
6. `test_products_facts_counts` / `test_stores_facts_counts` — `"N produtos no catálogo"` / `"N mercados importados"`; lista vazia → `""`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "^import pydantic_ai\|^from pydantic_ai" julius/bot/render.py` **vazio** (regra que já existia, continua valendo).
- [ ] `grep -n "^from julius.services\|^import julius.services" julius/bot/render.py` **vazio**.

## Notas para o agente

- Não agrupe `records_facts` por unidade (UN/KG) como `render_records` faz — quem decide se narra tudo junto ou separa por tamanho de resultado é o ticket 167, não este.
- `products_facts`/`stores_facts` de propósito não listam nome por nome — narrar um catálogo de 100+ itens em prosa é o problema que o design já descartou (Modo B existe justamente para não tentar isso).
