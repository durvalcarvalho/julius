# Requisitos: resolver item/tipo na própria chamada de roteamento, não mais em listas de exceção

> Descoberta via `/sc:brainstorm`, 2026-09-21, depois de um `/sc:troubleshoot --fix` no mesmo dia ter corrigido um incidente real (usuário perguntou "Devo comprar uma coca por 12 reais?", Julius respondeu "esse item ainda não tá no catálogo" apesar de Coca-Cola Zero e original estarem cadastradas). O usuário rejeitou o corretivo como "resolvendo o específico" e pediu explicitamente "o definitivo generalista que vai funcionar em larga escala".

## Causa raiz — por que o corretivo pontual não basta

`services/search.py::match_kind` resolve `item`/`kind` comparando string contra o vocabulário de `kind` (98 valores hoje) com `_name_score`, que exige que **toda** palavra do termo ache par na string do kind. Cada forma nova de falar quebra isso de um jeito novo, e cada correção até hoje foi uma lista de exceção nova:

| forma de falar | quebrou em | correção aplicada |
|---|---|---|
| conectivo ("suco **de** uva") | v2.8 | `CONNECTIVE_WORDS` |
| artigo/quantidade ("**uma** coca", "refrigerante **de 2 litros**") | hoje (patch já aplicado) | `KIND_NOISE_WORDS` + `_QUANTITY_TOKEN` |
| marca sem `kind` próprio ("coca", "pepsi") | hoje (patch já aplicado) | `_match_kind_via_product` (fallback por nome de produto) |
| coincidência de letras na borda do corte ("coca" ≈ "cacau em pó", score 75 exato) | hoje (patch já aplicado) | override quando o score empata exatamente no `KIND_MATCH_CUTOFF` |

Quatro listas/regras de exceção em três rodadas, todas do mesmo formato: alguém fala de um jeito que o vocabulário fechado + string matching não previu, e o sistema devolve "não conheço" mesmo quando o dado existe. Isso não escala — nem para novas formas de falar (robustez de frase) nem para um catálogo maior (mais marcas, mais `kind`s).

## O que já existe no próprio sistema e aponta pra saída

`services/search.py::search_free_text`/`suggestions.match_products` já usam a IA como **fallback**, só quando a busca determinística (`search_prices`) vem vazia — mesma disciplina de "IA só em ponto de baixa frequência" documentada em todo o projeto. `check_price`/`compare_stores` (que dependem de `match_kind`) são os únicos caminhos de resolução de item que ficaram de fora dessa disciplina: hoje é string matching puro, sem escape para IA.

O bot já paga uma chamada de IA por mensagem para *rotear* (escolher qual das 14 ações chamar). Essa mesma chamada já vê o texto da pessoa inteiro — a ideia validada nesta sessão é: em vez de o modelo extrair um `item` em texto livre que o código tenta casar depois, o modelo já resolve o `kind`, escolhendo dentro do vocabulário conhecido que o próprio prompt de roteamento carrega. Zero chamada de IA nova.

## Objetivo esclarecido (decisões tomadas nesta sessão, com o usuário)

1. **Escala = as duas coisas ao mesmo tempo** — robustez a qualquer forma de falar **e** um catálogo que pode crescer bastante (mais marcas, mais mercados). A solução não pode assumir que o vocabulário fica pequeno para sempre.
2. **A resolução acontece na chamada que já roteia**, não numa chamada de IA extra — o modelo recebe o vocabulário de `kind` conhecido e já devolve o valor resolvido (ou nenhum) como argumento da ação, em vez de uma string livre.
3. **Ambiguidade real vira pergunta, não recusa.** Quando dois ou mais tipos são candidatos plausíveis, o Julius pergunta qual dos dois numa mensagem separada, em vez de dizer "não conheço" — isto puxa o gatilho de estado de pergunta pendente que três rodadas anteriores (v2.10 Decisão 4, v2.11 RF4, v2.13) já registraram e adiaram por falta de caso medido. Este é o caso medido.
4. **O patch determinístico já aplicado (`KIND_NOISE_WORDS`, `_match_kind_via_product`, override de borda) permanece** — como o caminho da CLI (`julius mercados comparar`, sem IA) e como validação/atalho rápido e grátis dentro das ações do bot antes/depois de consultar o modelo, não como código morto.

## O que separa em duas escalas diferentes, e por que isso resolve a tensão de custo

Duas famílias de termo que hoje se confundem no mesmo mecanismo, e que crescem em ritmos diferentes:

- **Categoria/tipo** (`kind`: "tomate", "leite uht", "refrigerante") — vocabulário curado, cresce devagar mesmo com o catálogo crescendo em ordens de grandeza (produto novo de um tipo já existente reaproveita o `kind`, não cria um novo). Medido hoje: **98 `kind`s, ~1.178 caracteres, ~294 tokens** — **~11% do prompt de roteamento atual** (2.728 tokens de entrada). Cabe no prompt de roteamento sem custo desproporcional.
- **Marca/produto** (`canonical_name`: "Refrigerante Coca-Cola Zero PET 1,5L") — cresce no ritmo do catálogo (SKU a SKU), sem limite natural. **Nunca deve ir para o prompt de roteamento** — é exatamente o que `_match_kind_via_product` já resolve hoje, do lado do código, sem custo por mensagem.

Essa separação é o que permite dizer "sim" às duas exigências de escala ao mesmo tempo: o vocabulário que entra no prompt (kind) é o que cresce devagar; o vocabulário que cresce rápido (produto/marca) nunca entra no prompt, fica só na validação determinística do código.

## Requisitos funcionais

**RF1 — o prompt de roteamento do bot passa a carregar o vocabulário de `kind` conhecido**, para que o próprio modelo, ao decidir chamar `check_price`/`compare_stores`, já prefira devolver um valor que bate com um `kind` existente, em vez de uma frase livre.

**RF2 — o valor que o modelo devolve é sempre validado contra `products.all_kinds()` antes de qualquer uso.** Um valor fora do vocabulário conhecido nunca é tratado como `kind` válido — cai para o caminho de resolução determinística (RF4) exatamente como hoje. Mesma disciplina já usada para categoria automática (v2.3: "a primeira candidata que já existe no vocabulário"): a IA nunca inventa `kind` novo por este caminho.

**RF3 — ambiguidade real (dois ou mais `kind`s candidatos, sem um vencedor claro) vira pergunta ao usuário, numa mensagem separada, antes do veredito.** Isto exige um estado de pergunta pendente que sobrevive entre turnos — o mecanismo que v2.10/v2.11/v2.13 já descreveram e adiaram. Ao responder, o Julius rechama a ação com o `kind` escolhido.

**RF4 — o caminho determinístico (`match_kind` com `KIND_NOISE_WORDS`, `_match_kind_via_product`, override de borda — já implementado) continua existindo**, com dois papéis: (a) único mecanismo da CLI, que não tem IA no meio; (b) validação/atalho dentro das ações do bot — cobre o caso do modelo devolver texto livre (item não bate em nenhum `kind` conhecido, ex. marca nova) sem precisar de pergunta nova nem de vocabulário de produto no prompt.

**RF5 — cobre os dois consumidores de `match_kind` no bot: `check_price` e `compare_stores`** (lista de compras). A CLI (`julius mercados comparar`) não muda — continua 100% determinística, sem IA.

## Requisitos não funcionais

**RNF1 — o payload de vocabulário no prompt de roteamento é limitado pelo número de `kind`s distintos, não pelo número de produtos.** Medido hoje: 98 `kind`s para 133 produtos (proporção ~1:1,4, e a proporção só tende a cair com o tempo, já que produto novo de tipo conhecido não cria `kind` novo). Se `all_kinds()` algum dia se aproximar de uma ordem de grandeza maior (centenas a mais, na casa de 1000+), reavaliar — nesse ponto o custo por mensagem deixa de ser desprezível e um mecanismo de shortlist (achar candidatos por `rapidfuzz` primeiro, mandar só os N mais prováveis pro prompt) substitui "vocabulário inteiro sempre".

**RNF2 — a IA nunca decide sozinha um `kind` fora do vocabulário conhecido (RF2), e nunca inventa preço/quantidade** — mesma guarda de dinheiro de sempre neste projeto (`domain/formatting`, `check_price`, `shopping_verdict`).

**RNF3 — `ROUTING_TEMPERATURE = 0.0` (v2.12) continua valendo** para esta escolha — é uma decisão de "múltipla escolha" como as outras 14 ações, mesmo raciocínio que já justificou temperatura zero.

**RNF4 — isto reabre a pendência de estado de pergunta explícita, adiada em v2.10 (Decisão 4), v2.11 (RF4) e v2.13 (Decisão mais cara da rodada).** Não é mais um "se aparecer caso real, reabrir" — este é o caso real. O mecanismo (quantas tentativas, TTL, como o toque/resposta seguinte religa à pergunta) é decisão de `/sc:design`, mas o requisito de existir deixa de ser hipotético.

**RNF5 — não regride o caminho CLI.** `julius mercados comparar` e qualquer uso de `match_kind` fora do bot continuam funcionando sem IA, exatamente como hoje (RF4).

## Histórias de usuário

- **Como usuário falando naturalmente** ("uma coca", "um refrigerante de 2 litros", "aquele biscoito recheado"), quero que o Julius entenda o tipo certo sem eu precisar saber o nome exato como está cadastrado.
- **Como usuário**, se o que eu disse bate em mais de um tipo com chance real (ex. duas marcas do mesmo termo), quero que o Julius pergunte qual dos dois, em vez de dizer que não conhece.
- **Como usuário**, quero que isso continue funcionando conforme eu importar mais notas e o catálogo crescer, sem o sistema ficar mais lento ou mais caro por mensagem.

## Critérios de aceite (rascunho, para o `/sc:design` refinar)

- Reproduzir e manter corrigidos os 3 casos do incidente real: "uma coca", "um refrigerante de 2 litros", "guaraná" — todos resolvem para `refrigerante` (ou o `kind` correto).
- Um termo que bate em 2+ `kind`s sem vencedor claro gera uma pergunta, não uma recusa; a resposta da pessoa fecha o veredito na ação certa.
- Um `kind` fabricado/alucinado pelo modelo (fora de `all_kinds()`) nunca chega a `check_price`/`compare_stores` como se fosse válido.
- `julius mercados comparar` (CLI) continua passando nos testes existentes sem nenhuma chamada de IA.
- Medir o tamanho do prompt de roteamento antes/depois de adicionar o vocabulário de `kind`, e registrar a proporção (hoje: ~11% de aumento) — não estimar, medir contra o catálogo real como todo cutoff deste projeto já faz.

## Questões em aberto para a próxima fase (`/sc:design`)

1. **Mecanismo exato de pergunta pendente (RNF4).** Estado novo em `ChatState` (irmão de `PendingWrite`)? Quantas tentativas antes de desistir? Isso afeta só `check_price`/`compare_stores` ou é genérico o suficiente para as outras vezes que este projeto cogitou e adiou o mesmo mecanismo?
2. **Como o roteamento decide "ambíguo" vs. "resolvido".** O modelo relata a ambiguidade sozinho (arriscado — mesma classe de problema que v2.12 já tratou como "não confiar no auto-relato do modelo"), ou o código decide comparando a resposta do modelo contra `matching_product_ids`/`match_kind` rodando em paralelo como segunda opinião?
3. **Onde mora o vocabulário de `kind` no prompt** — dentro do docstring de `check_price`/`compare_stores` (por ação) ou uma seção própria do `SYSTEM_PROMPT` (compartilhada pelas duas ações que precisam)?
4. **O que muda no formato de `ai_calls.jsonl`/`query_log.jsonl`** para dar visibilidade a isto (hoje não há registro de qual `kind` o modelo escolheu nem de quando uma ambiguidade disparou pergunta) — mesma lição já registrada em v2.12 sobre um log que não guarda o suficiente para investigar incidente.
5. **Extensão a `search_prices`/`consultar`.** Este documento cobre só `check_price`/`compare_stores` (RF5). `consultar` já tem fallback de IA separado (`match_products`, pós-resultado-vazio) — vale unificar sob o mesmo mecanismo (vocabulário no prompt de roteamento) ou os dois fallbacks continuam coexistindo por serem gatilhos diferentes (bot vs. CLI, kind vs. produto)? Não decidido aqui.
