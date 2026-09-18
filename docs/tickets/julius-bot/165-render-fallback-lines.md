# 165: `bot/render.py` — frase-molde do Julius sem IA (fallback do Modo A)

<!-- status:done -->
<!-- adjustments: ver ticket 164 -- as duas funções ganharam a unidade por extenso e a diferença
já calculada, mesmo ajuste de 18/09/2026, pra ficarem consistentes com records_facts/comparison_facts
e com o prompt v2 que a IA usa quando está disponível. -->

> Quando a IA não responde (sem orçamento, sem configuração, guarda rejeitou, erro de rede), busca e comparação pequenas ainda precisam soar como o Julius — nunca voltar à tabela crua. Este ticket escreve essa frase, sem chamar IA nenhuma.

## Contexto

Parte do design v2.7, decisão RF4: "fallback sempre com tom, nunca a tabela crua" — mas só para o Modo A (busca/comparação **pequenas**; ver ticket 167 para o corte de tamanho). Independente dos tickets 163 e 164.

## Escopo

### Dentro
- `search_fallback_line(records: Sequence[PriceRecord], *, today: date | None = None) -> str`:
  - 0 registros: não é chamada (quem decide "sem resultado" continua sendo `render_records`/o chamador) — mas se vier vazia mesmo assim, devolve `"Nenhum resultado."` por segurança.
  - 1 registro: uma frase citando produto, preço, mercado e idade relativa.
  - 2+ registros: uma frase citando o mais barato e o mais caro (usa `highlight` já calculado, não recalcula min/max) e uma linha de fechamento no tom do personagem.
- `compare_fallback_line(comparison: StoreComparison, *, today: date | None = None) -> str`: uma frase por grupo (nome do tipo, mercado mais barato e o preço), concatenadas; sem grupo comparável, mesma mensagem que `render_comparison` já usa hoje (`"Nenhum tipo de produto foi comprado em dois mercados ainda..."`).
- Nenhuma das duas usa `<pre>`/`<b>`/marcadores ▼▲ — são frases, não tabela.

### Fora
- Decidir **quando** usar essas frases em vez da tabela ou da IA — isso é o ticket 167 (corte de tamanho, orquestração).
- Qualquer molde para listagens de produto/mercado ou para escrita — o design não exige fallback com tom aí (Modo B degrada para "sem comentário", não para uma frase nova).

## Requisitos

### Funcionais
- Determinístico: mesma entrada, mesma saída — sem `random`, sem depender de hora do sistema além de `today` (injetável, mesma disciplina de `relative_age`).
- Usa só dados já presentes em `PriceRecord`/`StoreComparison`/`KindComparison` — nenhum cálculo novo de mínimo/máximo (reaproveita `highlight` e a ordenação que `comparison_basis`/`compare_stores` já produziram).
- Texto plano, sem HTML — é a resposta final da mensagem (vai para `escape()` no `turn.py`, ticket 167, se precisar).

### Validação e erros
- `search_fallback_line([])` não lança.
- `compare_fallback_line` com `comparison.comparisons == ()` não lança.

## Especificação técnica

```
modificar julius/bot/render.py       — search_fallback_line, compare_fallback_line
modificar tests/test_bot_render.py   — testes das duas
```

### Padrão a seguir
- `_cheapest_per_content_line` (mesmo arquivo): mesmo estilo de frase curta com "contra" no lugar de artigo, para não presumir gênero do nome do produto.
- `render_comparison`: a mensagem de "nenhum grupo comparável" é reaproveitada literalmente, não reescrita.

## Testes obrigatórios

1. `test_search_fallback_line_one_record` — cita produto, preço, mercado.
2. `test_search_fallback_line_marks_cheapest_and_dearest` — dois+ registros com `highlight` definido.
3. `test_search_fallback_line_empty` — `"Nenhum resultado."`.
4. `test_compare_fallback_line_one_line_per_group`.
5. `test_compare_fallback_line_no_comparable_groups` — mesma mensagem de `render_comparison` para `comparisons=()`.
6. Nenhuma das saídas contém `<` ou `>`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] As duas funções não importam nada de `services` nem `pydantic_ai`.

## Notas para o agente

- Não tente cobrir período extenso (o aviso de "período largo pode ser variação de preço" que `render_comparison` mostra) — é informação de rodapé, não cabe numa frase curta; se fizer falta, é ajuste do ticket 169 (smoke), não deste.
- A voz é a mesma que o ticket 163 pede à IA, mas escrita à mão, sem chamar nada — não copie o prompt do 163 aqui, escreva a frase diretamente em português.
