# 155: `bot/actions.py` — `Deps`, resolução por nome e as ações de leitura

> As primeiras funções que a IA pode escolher: só leitura, e um jeito de transformar "o tomate" num id sem a IA adivinhar.

## Contexto

`docs/design/telegram-bot.md` §3 (3.1 leitura, 3.2 contrato, 3.3 resolução) e §4.3 (*output functions*). Uma ação é uma função Python com type hints e docstring; o PydanticAI gera o schema a partir disso e a chamada **encerra o run** — o retorno é o que o bot renderiza. A IA nunca vê `conn`, `config` nem `chat_id`: eles chegam por `RunContext[Deps]`.

Depende de **153**. Não depende de 154 (render) — as ações devolvem objetos de `domain`; quem renderiza é o turno (159).

## Escopo

### Dentro
- `julius/bot/actions.py`: `Deps`, `ProductListing`, `StoreListing`, `resolve_product`, `resolve_store`, e as quatro ações de leitura: `search_prices`, `compare_stores`, `list_products`, `list_stores`; `READ_ACTIONS`.
- `julius/services/search.py`: `_matching_ids` passa a se chamar `matching_product_ids` (pública), com as chamadas internas atualizadas — uma renomeação.
- `tests/test_bot_actions_read.py`.

### Fora
- Qualquer ação de escrita e `PendingWrite` (→ 156, 157).
- O agente, o prompt e o modelo (→ 158).
- Chamar `guidance` (as dicas são da CLI; o bot não as imprime nesta rodada).

## Requisitos

### Funcionais

```python
@dataclass(frozen=True)
class Deps:
    conn: sqlite3.Connection
    config: Config

@dataclass(frozen=True)
class ProductListing:
    products: tuple[Product, ...]
    containing: str | None = None

@dataclass(frozen=True)
class StoreListing:
    stores: tuple[Store, ...]
```
Os dois *listings* existem para o turno (159) saber o que renderizar quando a lista vem **vazia** — `list[Product]` e `list[Store]` vazios são indistinguíveis.

- `resolve_product(conn, reference: str) -> Product` — nunca devolve `None`; toda saída ruim é `ModelRetry` (a mensagem vai **ao modelo**, que pergunta ao usuário ou corrige):
  - `reference.strip()` só dígitos → `catalog.get_product(conn, int(...))`; `None` → `ModelRetry(f"Não existe produto com id {n}. Pergunte ao usuário ou use list_products.")`.
  - senão → `search.matching_product_ids(conn, reference)` (a busca palavra a palavra que `consultar` usa):
    - 1 id → o produto;
    - vários → `ModelRetry("Mais de um produto combina com «{ref}»: {id} · {nome}; {id} · {nome}… Pergunte ao usuário qual, e chame de novo com o id.")`, no máximo 8 candidatos, ordenados por id;
    - nenhum → se `search.closest_names(conn, reference)` devolver algo: `ModelRetry("Nenhum produto chamado «{ref}». Parecidos: {nomes}. Confirme com o usuário.")`; senão `ModelRetry("Nenhum produto chamado «{ref}». Use list_products para ver o catálogo.")`.
- `resolve_store(conn, reference: str) -> Store` — `digits_only(reference)` com 14 dígitos → busca por CNPJ em `catalog.list_stores`; senão `normalize_text(reference) in normalize_text(nickname)` **ou** `in normalize_text(legal_name)`; 1/vários/nenhum com as mesmas três formas de mensagem (`list_stores` no lugar de `list_products`).

Ações (todas `async def`, primeiro parâmetro `ctx: RunContext[Deps]`, docstring em **português** no estilo Google — o PydanticAI copia a descrição de cada parâmetro para o schema):

- `search_prices(ctx, words: str, tag: str | None = None, limit: int = 20) -> SearchOutcome`
  `words.split()`; vazio e `tag is None` → `ModelRetry("Informe um termo de busca ou uma tag.")`; `limit < 1` → `ModelRetry`; `tag` em minúsculas; devolve `search_service.search_free_text(conn, palavras, tag=tag, limit=limit)`.
- `compare_stores(ctx) -> StoreComparison` — `comparison.compare_stores(conn)`.
- `list_products(ctx, containing: str | None = None) -> ProductListing` — `catalog.list_products`; com `containing`, filtra por `normalize_text(containing) in normalize_text(canonical_name)`.
- `list_stores(ctx) -> StoreListing` — `catalog.list_stores`.
- `READ_ACTIONS: tuple = (search_prices, compare_stores, list_products, list_stores)`.

### Validação e erros
- Nenhuma ação deixa exceção de `services` escapar: `ValueError` vira `ModelRetry(str(error))`.
- Nenhum parâmetro de ação se chama `chat_id`, `conn` ou `config` (RF9).

## Especificação técnica

```
criar     julius/bot/actions.py
modificar julius/services/search.py     — _matching_ids → matching_product_ids (renomear, atualizar chamadas)
criar     tests/test_bot_actions_read.py
```

Imports permitidos em `actions.py`: `pydantic_ai` (`RunContext`, `ModelRetry`), `julius.config`, `julius.domain.*`, `julius.services.{catalog, search, comparison}`.

### Padrão a seguir
- Testar uma ação **pelo agente**, com um modelo falso que chama a ação com argumentos escolhidos — é para isso que `FunctionModel` existe:
  ```python
  from pydantic_ai import Agent
  from pydantic_ai.messages import ModelResponse, ToolCallPart
  from pydantic_ai.models.function import FunctionModel

  def calls(tool_name, args):
      def model(messages, info):
          return ModelResponse(parts=[ToolCallPart(tool_name, args)])
      return FunctionModel(model)

  agent = Agent(calls("search_prices", {"words": "picanha"}), deps_type=Deps, output_type=[str, *READ_ACTIONS])
  result = agent.run_sync("x", deps=Deps(conn, config))
  assert isinstance(result.output, SearchOutcome)
  ```
  `run_sync`, não `await`: a suíte não tem `pytest-asyncio`.
- Para `ModelRetry`, o modelo falso olha a última mensagem: se contém um `RetryPromptPart`, devolve texto (`ModelResponse(parts=[TextPart("...")])`) e o teste afirma que a segunda chamada aconteceu e que o `RetryPromptPart.content` traz a mensagem esperada.
- Popular o banco: `importing.import_receipt(conn, path, DFReceiptParser())` sobre `copied_fixtures(tmp_path)`, como `tests/test_services_search.py` faz.

## Testes obrigatórios

Resolução (chamadas diretas, com o `conn` das fixtures reais importadas):
1. `test_resolve_product_by_id` — pegue o id de um produto em `catalog.list_products` (são autoincrement; não use o código do cupom) e passe como string; devolve o `Product`.
2. `test_resolve_product_unknown_id_retries` — `"99999"` → `ModelRetry` com "Não existe produto com id 99999".
3. `test_resolve_product_by_unique_name` — `"picanha"` → o produto certo.
4. `test_resolve_product_ambiguous_name_lists_candidates` — `"tomate"` com `qrcode.html` + `qrcode-3.html` importados → `ModelRetry` citando os dois `id · nome`.
5. `test_resolve_product_no_match_suggests_or_points_to_listing` — `"pikana"` → mensagem com "Parecidos:"; `"xyzabc"` → mensagem com "list_products".
6. `test_resolve_store_by_cnpj_and_by_nickname` — `"27.289.076/0013-79"` e `"costa"` → a mesma loja; `"zzz"` → `ModelRetry`.

Ações (pelo agente, `FunctionModel`):
7. `test_search_prices_returns_outcome` — `SearchOutcome` com registros de picanha; `words` com tag detectada ("picanha carnes" depois de marcar a tag) preenche `outcome.tag`.
8. `test_search_prices_without_words_or_tag_retries` — `{"words": ""}` → `RetryPromptPart` com "Informe um termo".
9. `test_compare_stores_returns_comparison` — `StoreComparison`.
10. `test_list_products_filters_by_containing` — `{"containing": "tomate"}` → só tomates; sem filtro → todos; catálogo vazio → `ProductListing(products=())`.
11. `test_list_stores_returns_listing` — três lojas das fixtures.
12. `test_matching_product_ids_is_public_and_unchanged` — `search.matching_product_ids(conn, "picanha")` devolve o mesmo que `consultar` acha; `grep` não encontra `_matching_ids`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (inclusive `tests/test_services_search.py`, que só muda se referenciava `_matching_ids`).
- [ ] `tests/test_architecture.py` verde: `actions.py` importa só `domain`, `config`, `services`.
- [ ] `grep -n "chat_id" julius/bot/actions.py` **vazio**.
- [ ] Toda ação tem docstring em português com seção `Args:` descrevendo cada parâmetro.

## Notas para o agente

- `ModelRetry` é a **única** forma de recusa: nunca devolva `None`, string de erro ou lista vazia para "não achei" numa resolução — o modelo precisa do motivo para perguntar direito ao usuário.
- As mensagens de `ModelRetry` são lidas pelo **modelo**, não pelo usuário — podem citar nomes de ações (`list_products`) e ids; escreva em português como os prompts do projeto.
- Não transforme `resolve_*` em ações registradas: são helpers das ações de escrita (156/157); a IA só lista/pesquisa pelas quatro de leitura.
