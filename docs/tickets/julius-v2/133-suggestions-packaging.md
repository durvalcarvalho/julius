# 133: `suggestions.suggest_packaging` — a intuição de varejo, numa chamada separada

> Uma segunda chamada de IA que responde "como isso é vendido no Brasil" e devolve candidatos de conteúdo. Ninguém grava nada com ela.

## Contexto

`docs/design/review-scope-v2.3.md` §4 (por que duas chamadas), §8.3 (contrato). Requisito RF6 de `docs/requirements/review-scope-v2.3.md`.

Os dois enquadramentos foram medidos no mesmo modelo, no mesmo dia:

| Prompt | Comportamento |
|---|---|
| `enrich` de produção: "preencha `content` só quando a descrição deixa inequívoco" | recusa corretamente — `null` certo em **6 de 6** |
| Sonda: "diga a forma e dê até 3 candidatos" | **nunca** recusa — 9 de 9 com palpite, inclusive `500 KG` de bacon e `30 UN` de filme PVC |

A recusa honesta do primeiro é o único sinal de incerteza confiável que este projeto já mediu, depois de `confidence` (v2), número de tags e auto-avaliação de certeza falharem. **Por isso são duas chamadas**: misturar "recuse quando não for inequívoco" com "dê candidatos plausíveis" no mesmo prompt arrisca o ativo que funciona. Custo da separação: US$ 0,0007 por rodada.

Independente de tudo. Pode rodar em paralelo com 131/132.

## Escopo

### Dentro
- `julius/domain/models.py`: `PackagingForm`, `PackagingHint`.
- `julius/services/suggestions.py`: `SYSTEM_PROMPTS["packaging"]`, `PROMPT_VERSIONS["packaging"] = "1"`, `suggest_packaging`, validação.
- `tests/_fakes.py`: marcador `"packaging"` em `_KIND_MARKERS`.
- `tests/test_services_suggestions.py`.

### Fora
- Chamar `suggest_packaging` (→ 135). Ninguém o consome neste ticket.
- Gravar conteúdo a partir de `PackagingHint`, em qualquer circunstância (RF6).
- Tocar em `SYSTEM_PROMPTS["enrich"]`, `["merge"]`, `["match"]` ou em suas versões.
- Pedir ao modelo qualquer forma de auto-avaliação de certeza — reprovada três vezes.
- Limite numérico de sanidade nos candidatos (design §8.3).

## Requisitos

### Funcionais

- Domínio:
  ```python
  PackagingForm = Literal["unit", "pack", "weight", "volume", "unknown"]

  @dataclass(frozen=True)
  class PackagingHint:
      form: PackagingForm
      candidates: tuple[ContentSuggestion, ...]  # best first, at most 3; empty when the model had none
  ```

- `PROMPT_VERSIONS["packaging"] = "1"`. As outras três versões não mudam.

- `SYSTEM_PROMPTS["packaging"]` — chaves JSON em inglês, instruções em português, como os três já existentes. **Texto exatamente como medido na sonda** (design §4.3):
  ```
  Você conhece o varejo de supermercado brasileiro. Para cada produto, diga COMO ele é vendido,
  usando conhecimento de mercado — não só o que está escrito no nome.
  - "form": "unit" (a embalagem É a unidade de compra, ex.: uma alface, uma espátula),
    "pack" (vem N unidades juntas), "weight" (vendido a granel ou por peso),
    "volume" (líquido) ou "unknown".
  - "candidates": de 1 a 3 valores de conteúdo plausíveis, o mais provável primeiro, no formato
    {"quantity": número, "unit": "L"|"KG"|"UN"}. Lista vazia quando você não tiver palpite.
  Responda somente com json, um item por produto recebido, mesmos ids:
  {"packaging": [{"id": 1, "form": "unit", "candidates": [{"quantity": 1, "unit": "UN"}]}]}
  ```
  Sem few-shot: a sonda foi medida sem exemplos e funcionou. Acrescentar exemplo muda o que foi medido e custa token de entrada em toda chamada.

- `suggest_packaging(conn, config, client, products: Sequence[Product], month=None) -> dict[int, PackagingHint]`
  - `user_prompt`: `"produtos:\n"` seguido de uma linha `"{id} | {canonical_name}"` por produto — mesmo formato de `enrich_products`, **sem** as linhas `categorias:`/`tipos:`.
  - Lotes de `ENRICH_BATCH_SIZE` (constante que já existe; não crie outra).
  - `max_tokens = 70 * len(batch) + 200`. A sonda gastou 509 tokens de saída para 9 produtos.
  - `products` vazio → `{}` sem chamar nada.
  - Lote que falha perde só aquele lote, como `enrich_products`.

- Validação por item:
  - `id` ausente, não-inteiro, booleano ou fora do lote → item descartado.
  - `form` ausente ou fora do enum → `"unknown"`.
  - Cada candidato passa por `_valid_content` (que já existe e já normaliza `unit` para maiúscula); candidato inválido é descartado **individualmente**, sem derrubar o item.
  - No máximo 3 candidatos, preservando a ordem recebida.
  - Item sem nenhum candidato válido → `PackagingHint(form, ())`. Não é erro.

### Validação e erros
- **Nunca lança** — invariante do módulo. Chave ausente, JSON malformado, orçamento estourado: `{}` ou item ausente.
- Sem preços por token configurados, ou orçamento do mês esgotado: `_ask` já devolve `None` e a função devolve `{}`.

## Especificação técnica

```
modificar julius/domain/models.py            — PackagingForm, PackagingHint
modificar julius/services/suggestions.py     — prompt, versão, suggest_packaging, validador
modificar tests/_fakes.py                    — '"packaging"': "packaging" em _KIND_MARKERS
modificar tests/test_services_suggestions.py
```

### Padrão a seguir
- `enrich_products` é o molde exato: laço de lotes, `try/except: continue` por lote, `_ask(...)`, `data.get(<chave raiz>)`, validação por item, dicionário por id.
- `_valid_content` **já existe** — reaproveite, não escreva uma segunda validação de conteúdo.
- `_KIND_MARKERS` em `tests/_fakes.py` detecta o tipo da chamada pela chave raiz citada no system prompt. `"packaging"` é distinta de `"products"`, `"pairs"` e `"ids"`, então basta acrescentar a entrada.

## Testes obrigatórios

1. `test_packaging_parses_form_and_candidates` — resposta com `form: "pack"` e dois candidatos → `PackagingHint("pack", (ContentSuggestion(10,"UN"), ContentSuggestion(20,"UN")))`.
2. `test_packaging_unknown_form_falls_back` — `form` ausente, `"tray"`, `123` e `null` → todos viram `"unknown"`, sem lançar.
3. `test_packaging_drops_invalid_candidate_keeps_the_rest` — lista com um candidato bom, um com `unit: "OZ"` e um com `quantity: 0` → sobra só o bom.
4. `test_packaging_caps_at_three_candidates` — 5 candidatos válidos → 3, na ordem recebida.
5. `test_packaging_empty_candidates_is_valid` — `candidates: []` → `PackagingHint(form, ())`, item presente no dicionário.
6. `test_packaging_ignores_unknown_id` — item com id fora do lote é descartado, os outros permanecem.
7. `test_packaging_prompt_lists_id_and_name_only` — o `user_prompt` capturado tem `"60 | LING FGO RESF AURORA kg"` e **não** contém `categorias:` nem `tipos:`.
8. `test_packaging_prompt_version_is_1` — a linha em `ai_calls.jsonl` traz `prompt_version == "1"` e `call_kind == "packaging"`.
9. `test_packaging_max_tokens_formula` — 6 produtos → `max_tokens == 620`.
10. `test_packaging_batches_isolate_failures` — 30 produtos com o primeiro lote falhando: os do segundo lote chegam.
11. `test_packaging_unavailable_returns_empty_dict_without_calls` — sem chave configurada → `{}` e `client.calls == []`.
12. `test_packaging_never_raises_on_garbage` — `LlmResponse` com texto que não é JSON, e outro com `{"packaging": "x"}` → `{}` nos dois, sem exceção.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `git diff julius/services/suggestions.py` **não** mostra mudança em `SYSTEM_PROMPTS["enrich"]`, `["merge"]`, `["match"]` nem nas suas versões.
- [ ] `grep -rn "suggest_packaging" julius/cli julius/services/curation.py` **vazio** — ninguém consome ainda.
- [ ] Nenhum teste toca a API real; rede sempre via `ScriptedLlmClient`.

## Notas para o agente
- **Não tente consertar o caso `Filme PVC 30m x 28cm → 30 UN` no prompt.** Esse erro é conhecido, está medido, e a proteção contra ele é o humano escolher (ticket 135), não engenharia de prompt. Mexer no texto invalida a medição que autorizou esta chamada a existir.
- **Não** acrescente bound de sanidade (`quantity < 100` e afins) para filtrar `500 KG` de bacon. Seria constante nova sem medição; quem tira isso da tela é a supressão por `form == "weight"` no 135.
- `form` é dado, não texto de interface. Não escreva aqui nenhuma tradução para português — a CLI faz isso no 135.
