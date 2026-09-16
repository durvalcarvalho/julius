# 120: Prompt `enrich` v2 — a IA passa a propor o tipo do produto

> Acrescenta `kind` ao enriquecimento, com a instrução de granularidade que os grupos medidos exigiram: `leite uht` ≠ `leite condensado`, e marca/sabor/tamanho ficam fora do tipo.

## Contexto

`docs/design/comparability-v2.2.md` §4.6 (prompt e contrato). Requisito RF2 de `docs/requirements/comparability-closure.md`.

O agrupamento por primeira palavra do nome, medido em `comparability-closure.md` §2, produziu grupos inutilizáveis por **heterogeneidade de tipo**, não de tamanho: `Leite [UN]` juntou leite UHT com leite condensado; `Pao [UN]` juntou pão de forma, pão de alho e pão de queijo. Nenhum cálculo salva esses grupos — só um nome de tipo na granularidade certa, e é por isso que quem nomeia é a IA e não um heurístico de texto. No sentido oposto, marca e variedade **não** podem entrar no tipo: é o que faz `uva branca` e `uva green dreams` caírem no mesmo grupo e aparecerem lado a lado (R$ 6,99 contra R$ 14,99 pela mesma bandeja de 500g), que é o resultado desejado.

Depende de **117** (`Product.kind`, `products.all_kinds`).

## Escopo

### Dentro
- `julius/domain/models.py`: `ProductEnrichment.kind`.
- `julius/services/suggestions.py`: bullet novo em `SYSTEM_PROMPTS["enrich"]`, `PROMPT_VERSIONS["enrich"] = "2"`, parâmetro `known_kinds` em `enrich_products`, linha `tipos:` no `user_prompt`, validação do campo.
- Testes: `tests/test_services_suggestions.py`.

### Fora
- `curation.propose`/`apply` (→ 121) — este ticket só faz a IA **devolver** o tipo; ninguém grava nada ainda.
- `_review`, CLI, log de ações (→ 122, 123).
- `SYSTEM_PROMPTS["merge"]` e `["match"]` — intocados, e suas versões não mudam.
- Estreitar `duplicate_candidates` por tipo — decidido contra no design §9.

## Requisitos

### Funcionais

- `ProductEnrichment` ganha `kind: str | None` (sem default, para o construtor falhar alto se alguém esquecer de preencher; é dataclass interna, todos os pontos de construção estão neste módulo).

- `PROMPT_VERSIONS["enrich"]` vai de `"1"` para `"2"`. A versão vai para o log de chamadas e é o que permite diferenciar respostas dos dois prompts no `ai_calls.jsonl`.

- Bullet novo no `SYSTEM_PROMPTS["enrich"]`, depois do de `content`:
  ```
  - "kind": o TIPO da coisa, em minúsculas, para comparar preço entre lojas. Deve ser
    específico o bastante para que dois produtos do mesmo tipo sejam alternativas de compra
    um do outro: "leite uht" e "leite condensado" são tipos DIFERENTES; "pão de forma",
    "pão de alho" e "pão de queijo" também. Marca, fornecedor, sabor e tamanho NÃO entram no
    tipo ("tomate", não "tomate italiano união"; "uva", não "uva green dreams"). Prefira um
    tipo da lista "tipos" quando servir.
  ```

- O formato de resposta declarado no prompt ganha o campo, e os itens do few-shot existente passam a incluí-lo — pelo menos:
  ```json
  {"id": 1, "readable_name": "Linguiça de frango resfriada Aurora", "tags": ["carnes"], "content": null, "kind": "linguiça"}
  {"id": 2, "readable_name": "Refrigerante Antarctica Guaraná PET 1,5L", "tags": ["bebidas"], "content": {"quantity": 1.5, "unit": "L"}, "kind": "refrigerante"}
  ```
  Mantenha os 4 itens do few-shot atual (incluindo o negativo `AC MASC F TER ES 1kg`) e só acrescente `kind` a cada um.

- `enrich_products(conn, config, client, products, known_tags, known_kinds) -> dict[int, ProductEnrichment]` — parâmetro novo posicional depois de `known_tags`. O `user_prompt` de cada lote ganha uma linha `tipos: [...]` no mesmo formato JSON da linha `categorias:` que já existe, **antes** de `produtos:`. Lista vazia → `tipos: []` (não omitir a linha: o modelo precisa saber que não há vocabulário ainda).

- Validação do campo no validador de item de enrich (junto de `_valid_content`): `kind` ausente, `null`, não-string, ou string vazia depois de `strip()` → `None`. String válida → `strip().lower()`. **Nunca lança** — mantém a invariante do módulo.

- `max_tokens` por lote sobe de `120 * len(batch) + 200` para `140 * len(batch) + 200` — o campo novo custa tokens de saída, e resposta truncada é erro cobrado (`finish_reason length`).

### Validação e erros
- Resposta sem `kind` em alguns itens e com em outros: cada item é validado sozinho; um `kind` inválido não descarta o resto do item (nome/tags/conteúdo continuam valendo).
- Lote que falha continua perdendo só aquele lote, como hoje.

## Especificação técnica

```
modificar julius/domain/models.py              — ProductEnrichment.kind
modificar julius/services/suggestions.py       — prompt, versão, known_kinds, user_prompt, validação, max_tokens
modificar tests/test_services_suggestions.py
```

### Padrão a seguir
- `known_kinds` chega de `products.all_kinds(conn)` — mas **quem chama é o 121**; aqui o parâmetro só existe e é usado no prompt.
- A linha `categorias:` já existente é o modelo exato de formatação da linha `tipos:` (`suggestions.py`, montagem do `user_prompt` de `enrich_products`).
- Rede sempre substituída por `tests/_fakes.py::ScriptedLlmClient`; nenhum teste toca a API real.

## Testes obrigatórios

1. `test_enrich_parses_kind` — resposta com `"kind": "Tomate"` → `ProductEnrichment.kind == "tomate"` (minúsculo).
2. `test_enrich_kind_missing_is_none` — item sem a chave `kind` → `kind is None`, e `readable_name`/`tags`/`content` do mesmo item continuam preenchidos.
3. `test_enrich_kind_invalid_types_are_none` — `null`, `""`, `"   "`, `123` e `[]` todos viram `None` sem lançar.
4. `test_enrich_prompt_includes_known_kinds` — inspecionando o `user_prompt` capturado pelo `ScriptedLlmClient`: contém `tipos:` com os tipos passados; com lista vazia, contém `tipos: []`.
5. `test_enrich_prompt_version_is_2` — a linha gravada em `ai_calls.jsonl` traz a versão `"2"` do prompt de enrich.
6. `test_enrich_batches_still_isolate_failures` — teste já existente de lote continua verde com o parâmetro novo (um lote que falha não derruba os outros).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -n "kind" julius/services/curation.py julius/cli/` vazio — nada grava tipo neste ticket.
- [ ] `SYSTEM_PROMPTS["merge"]` e `PROMPT_VERSIONS["merge"]` sem diff.

## Notas para o agente
- A instrução de granularidade do bullet não é redação: cada metade dela vem de um grupo medido (`Leite`/`Pao` obrigam a parte "tipos diferentes"; `uva` obriga a parte "marca e tamanho fora"). Não resuma nem "melhore" o texto.
- Não acrescente exemplo novo ao few-shot além do campo nos que já existem: mais exemplo é mais token de entrada em toda chamada.
- Se o modelo devolver um tipo com acento (`linguiça`, `açaí`), está correto — a normalização de grafia é do repositório (117), não do prompt.
