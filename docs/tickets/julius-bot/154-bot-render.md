# 154: `bot/render.py` — os dados do Julius em texto de celular

> A regra de negócio chega pronta de `services`; este módulo só decide como ela aparece numa tela de 40 colunas sem cor.

## Contexto

`docs/design/telegram-bot.md` §6 e §2 (módulo `render`). A CLI renderiza tabelas `rich` de seis colunas; o Telegram é HTML mínimo (`<b>`, `<i>`, `<code>`, `<pre>`), sem cor, 4096 caracteres por mensagem. Renderização diferente é feature, não duplicação: `highlight`, `price_per_content`, base de comparação e colapso de linhas já vêm resolvidos nos objetos de `domain`.

Depende de **150** (`domain.formatting`) e **153** (pacote `julius/bot/`). Não usa nada de `pydantic_ai`/`telegram` — é texto puro, testável sem nenhum dos dois.

## Escopo

### Dentro
- `julius/bot/render.py`: `escape`, `render_records`, `render_comparison`, `render_products`, `render_stores`, `fit` (teto de 4096) e a constante `MAX_MESSAGE_CHARS = 4096`.
- `tests/test_bot_render.py`.

### Fora
- Renderizar pendência/resultado de escrita (`render_pending`, `render_result`, `render_failure` → **156**, junto do dataclass que eles renderizam).
- Paginação, botões de "mais", formatação de tabela com alinhamento por coluna.
- Qualquer chamada a `services` ou ao banco — as funções recebem objetos de `domain` prontos.

## Requisitos

### Funcionais

- `escape(text: str) -> str` — `html.escape(text, quote=False)`. **Todo** texto vindo do banco (nome de produto, apelido, endereço, tipo, tag) passa por aqui antes de entrar na mensagem; um `AÇÚCAR & CIA` sem escape quebra a mensagem em silêncio.

- `render_records(records: Sequence[PriceRecord], *, today: date | None = None) -> str`
  - Vazio → `"Nenhum resultado."`.
  - Um bloco por `unit`, na ordem em que `records` vem (já vem agrupado e ordenado por `services.search`): cabeçalho `<b>Preços por {unit}</b>` e um `<pre>` com uma linha por registro:
    `{marca}{br_date} · {relative_age} · {money(unit_price)}{por_conteudo} · {nome} · {mercado}`
    - `marca`: `"▼ "` se `highlight == "lowest"`, `"▲ "` se `"highest"`, `"  "` (dois espaços) senão — as linhas ficam alinhadas.
    - `por_conteudo`: `f" · {money(price_per_content)}/{content_unit}"` quando `price_per_content is not None`, senão `""`.
    - `mercado`: `store_nickname`, mais ` — {store_place(store_address)}` quando há endereço e `store_place` devolve algo (`domain.normalization.store_place`, o mesmo bairro que a v2.5 usa no apelido).
    - `relative_age` recebe `today` (injetável — teste de faixa nunca depende do dia).
  - Depois do bloco de uma unidade, a linha `<i>Mais barato por {palavra}: {nome} a {money}/{unidade} — contra {money}/{unidade} de {nome}.</i>` com **exatamente** a regra de `cli/receipts.py::_print_cheapest_per_content` (`comparison_basis`, ≥ 2 participantes, preços diferentes; `{"L": "litro", "KG": "quilo", "UN": "unidade"}`). Copie a regra; não a chame de `cli`.

- `render_comparison(comparison: StoreComparison, *, today: date | None = None) -> str`
  - Sem grupos e `kinds_total == 0` → `"Nenhum produto tem tipo ainda. Rode: julius produtos revisar"`; sem grupos com tipos → `"Nenhum tipo de produto foi comprado em dois mercados ainda — sem base para comparar."` + `\n<i>Cobertura: {coverage_text}.</i>` — os mesmos textos de `cli/stores.py::compare_stores`.
  - Por grupo: `<b>{kind} · por {unit}</b>` (ou `por {content_unit} (por conteúdo)` quando `basis == "price_per_content"`) e um `<pre>` com `{marca}{label} · {money(price)} · {product_name} · {br_date} ({relative_age})`, `▼` no menor preço e `▲` no maior (regra de `_comparison_table`: igualdade com o primeiro/último). `label` vem de `domain.formatting.store_labels(comparison)`.
  - Depois dos grupos, uma linha por mercado, ordenada como a CLI (`-wins/total`, depois label): `{label}: mais barato em {wins} de {total} {plural_groups(total)}`.
  - Rodapé: `base: {n} {plural_groups(n)} · {br_date(first)} a {br_date(last)}` (+ ` · {coverage_text}` se `kinds_single_store`), e `<i>Período largo: parte da diferença pode ser variação de preço no mês, não o mercado.</i>`.

- `render_products(products: Sequence[Product]) -> str` — vazio → `"Nenhum produto importado ainda."`; senão `<pre>` com `{id} · {name} · {kind ou "—"} · {content_text ou "—"} · {tags separadas por ", " ou "—"}`.

- `render_stores(stores: Sequence[Store]) -> str` — vazio → `"Nenhum mercado importado ainda."`; senão `<pre>` com `{cnpj} · {nickname}` + ` · {store_place(address)}` quando houver.

- `fit(text: str) -> str` — se `len(text) <= MAX_MESSAGE_CHARS`, devolve igual. Senão corta na **última quebra de linha** que caiba junto com o sufixo, fecha `</pre>` se um `<pre>` ficou aberto, e termina com `\n… +{n} linhas não mostradas — peça um limite menor ou uma tag.` (`n` = linhas descartadas). Todas as `render_*` devolvem `fit(...)`.

### Validação e erros
- Nenhuma função lança para entrada vazia ou campo `None`; data inválida vira `""` (é o que `br_date`/`relative_age` já fazem).
- O resultado de `fit` **nunca** excede 4096 caracteres e nunca deixa `<pre>` aberto.

## Especificação técnica

```
criar julius/bot/render.py
criar tests/test_bot_render.py
```

Imports permitidos: `html`, `datetime`, `julius.domain.formatting`, `julius.domain.models`, `julius.domain.comparison_basis`, `julius.domain.normalization`. Nada de `julius.cli`, `julius.services`, `telegram`, `pydantic_ai`.

### Padrão a seguir
- `cli/receipts.py::_table`/`_print_cheapest_per_content` e `cli/stores.py::compare_stores`/`_comparison_table` são a **fonte da regra**; este módulo é outra saída para a mesma regra.
- Construa `PriceRecord`/`StoreComparison` diretamente nos testes (são `frozen dataclasses`) — não precisa de banco.

## Testes obrigatórios

Todos com `TODAY = date(2026, 9, 17)` injetado.

1. `test_render_records_empty` — `"Nenhum resultado."`.
2. `test_render_records_one_block_per_unit_in_input_order` — UN e KG → dois `<b>Preços por …</b>`, na ordem dada.
3. `test_render_records_markers` — `lowest` → linha começa com `▼ `, `highest` → `▲ `, sem destaque → dois espaços.
4. `test_render_records_per_content_and_cheapest_line` — o caso dos ovos (20 UN a 12,00 e 30 UN a 16,50, `price_per_content` 0,60 e 0,55, `content_unit="UN"`): coluna `/UN` presente e a linha `Mais barato por unidade: … a R$ 0,55/UN — contra R$ 0,60/UN de …`.
5. `test_render_records_no_cheapest_line_for_kg_group` — grupo KG (`basis == unit_price`) → sem a linha.
6. `test_render_records_escapes_html` — nome `AÇÚCAR & CIA <2kg>` → `&amp;` e `&lt;` no texto, nenhum `<2kg>` cru.
7. `test_render_records_store_place` — com endereço `…, GUARA II, BRASILIA, DF` → `Dona de Casa — GUARA II`; sem endereço → só o apelido.
8. `test_render_comparison_empty_messages` — os dois textos de vazio (com e sem tipos).
9. `test_render_comparison_groups_wins_and_footer` — dois grupos, dois mercados: marcadores, linhas de "mais barato em", rodapé `base:` e a nota de período.
10. `test_render_comparison_duplicated_nickname_gets_cnpj` — duas filiais com o mesmo apelido → labels com ` · {cnpj}`.
11. `test_fit_truncates_at_a_line_and_closes_pre` — 300 registros → `len <= 4096`, termina com a nota `+N linhas não mostradas`, contagem de `<pre>` igual à de `</pre>`.
12. `test_render_products_and_stores` — vazio e um item cada; `—` nos campos ausentes.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q tests/test_bot_render.py` verde; suíte inteira verde.
- [ ] `tests/test_architecture.py` verde (o módulo importa só `domain`).
- [ ] `grep -n "from julius.cli\|from julius.services\|import telegram\|pydantic_ai" julius/bot/render.py` **vazio**.

## Notas para o agente

- Não use `rich` para "exportar como texto": a linha de celular é um layout diferente, não a tabela achatada.
- `store_place` pode devolver `None`/vazio para endereço fora do padrão — trate como "sem lugar".
- Emojis só os dois marcadores ▼/▲ (são setas de texto, não emoji) — o projeto não usa emoji em saída.
