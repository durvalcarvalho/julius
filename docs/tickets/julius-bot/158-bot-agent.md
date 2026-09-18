# 158: `bot/agent.py` — o agente, o modelo e o prompt

<!-- status:done implemented:2026-09-17 commit:61af069 -->
<!-- adjustments: teste do menu compara nomes sem o prefixo final_result_ e afirma o prefixo -->

> Onde as catorze ações viram um menu fechado para a IA, e onde as três variáveis `JULIUS_AI_*` de sempre viram o modelo do PydanticAI.

## Contexto

`docs/design/telegram-bot.md` §4.3 (*output functions*: `output_type=[str, *ações]` — a chamada encerra o run e o resultado **não volta ao modelo**), §5.2 (modelo pelas mesmas variáveis; `JULIUS_AI_REQUEST_EXTRAS` precisa chegar ao corpo do request) e §9.4 (o prompt nasce versionado). Confirmado na documentação do PydanticAI durante o design: `ModelSettings` tem `extra_body` ("Extra body to send to the model"); `OpenAIChatModel(nome, provider=OpenAIProvider(base_url=…, api_key=…))` é a forma de apontar para um endpoint compatível.

Depende de **155**, **156**, **157** (`ALL_ACTIONS`, `Deps`).

## Escopo

### Dentro
- `julius/bot/agent.py`: `BOT_PROMPT_VERSION`, `SYSTEM_PROMPT`, `MAX_OUTPUT_TOKENS`, `build_model`, `build_agent`, o alias de tipo `BotAgent`.
- `tests/test_bot_agent.py`.

### Fora
- O turno (orçamento, histórico, render → 159/160).
- Medir o prompt contra frases reais (→ checklist manual do 162; aqui ele nasce com os requisitos abaixo e uma versão).
- Qualquer provider além do OpenAI-compatível; fallback de modelo.

## Requisitos

### Funcionais

```python
BOT_PROMPT_VERSION = "1"
MAX_OUTPUT_TOKENS = 600
SYSTEM_PROMPT = """…"""   # português, ver conteúdo obrigatório abaixo

BotOutput = str | SearchOutcome | StoreComparison | ProductListing | StoreListing | PendingWrite
BotAgent = Agent[Deps, BotOutput]

def build_model(config: Config) -> OpenAIChatModel
def build_agent(config: Config, model: Model | None = None) -> BotAgent
```

- `build_model`: `config.ai_configured` falso → `ValueError("IA não configurada: defina JULIUS_AI_API_KEY, JULIUS_AI_BASE_URL e JULIUS_AI_MODEL")`. Senão `OpenAIChatModel(config.ai_model, provider=OpenAIProvider(base_url=config.ai_base_url, api_key=config.ai_api_key))`. **Não** use `DeepSeekProvider`: a `base_url` já aponta para o DeepSeek, e essa é toda a abstração de provedor que o projeto quer (mesma decisão do client da curadoria).
- `build_agent(config, model=None)`:
  ```python
  Agent(
      model or build_model(config),
      deps_type=Deps,
      output_type=[str, *ALL_ACTIONS],
      system_prompt=SYSTEM_PROMPT,
      model_settings=ModelSettings(max_tokens=MAX_OUTPUT_TOKENS, extra_body=config.ai_request_extras) if config.ai_request_extras else ModelSettings(max_tokens=MAX_OUTPUT_TOKENS),
      retries=2,
  )
  ```
  `model` injetável existe para os testes (e só para eles) passarem um `FunctionModel`.
- **Conteúdo obrigatório do `SYSTEM_PROMPT`** (português; no máximo ~40 linhas; a redação é do agente implementador, os pontos não):
  1. Quem é: o Julius, memória pessoal de preços de supermercado de **um** usuário, a partir de cupons já importados; responde pelo Telegram.
  2. Escolher **exatamente uma** ação por mensagem; se o pedido tiver duas, fazer a primeira e dizer em texto que a segunda vem em outra mensagem.
  3. Leitura: perguntas de preço/histórico → `search_prices`; "qual mercado é mais barato" → `compare_stores`; "que produtos/mercados existem" → as listagens.
  4. Escrita: passar produto/mercado pelo **id** quando o usuário deu um; senão pelo nome. Se a ação responder que há ambiguidade ou que não existe, **perguntar ao usuário** em texto (listando as opções que a ação devolveu), nunca escolher por conta própria nem inventar id.
  5. **Nunca afirmar que algo foi feito**: uma ação de escrita só propõe; quem executa é o sistema depois de o usuário confirmar. Não descrever efeitos.
  6. Não dar veredito de "caro/barato" (o Julius mostra o histórico; quem decide é o usuário) — para "está caro?" chamar `search_prices`.
  7. Mensagem sem relação com o catálogo → resposta curta em português, sem ação.
  8. Ids e valores só os que vieram das ações ou do usuário; nada inventado.

### Validação e erros
- `build_agent` não abre banco, não lê ambiente (recebe `Config`), não faz rede.
- O conjunto de nomes das *output tools* que o modelo vê é **exatamente** `{a.__name__ for a in ALL_ACTIONS}` — nenhuma a mais (nenhuma tool registrada por `@agent.tool`), nenhuma a menos.

## Especificação técnica

```
criar julius/bot/agent.py
criar tests/test_bot_agent.py
```

Imports: `pydantic_ai` (`Agent`, `ModelSettings`/`settings`, `models.openai`, `providers.openai`), `julius.config`, `julius.domain.models`, `julius.bot.actions`.

### Padrão a seguir
- `SYSTEM_PROMPTS` em `services/suggestions.py`: prompt como constante, em português, com versão ao lado — aqui a versão é `BOT_PROMPT_VERSION` (o bot passa explicitamente em `record_usage`, ticket 152; **não** entre em `PROMPT_VERSIONS`).
- `FunctionModel` recebe `(messages, info: AgentInfo)`; `info.output_tools` lista as *output tools* com nome — é como o teste 1 vê o menu.

## Testes obrigatórios

1. `test_agent_exposes_exactly_the_actions_as_output_tools` — `FunctionModel` que guarda `info.output_tools` e devolve texto; `{t.name for t in seen} == {a.__name__ for a in ALL_ACTIONS}` e `info.function_tools == []`.
2. `test_text_output_when_no_action_fits` — modelo devolve `TextPart("Oi!")` → `result.output == "Oi!"` (str).
3. `test_output_function_ends_the_run_without_a_second_model_call` — modelo chama `list_stores`; contador de chamadas do `FunctionModel` == 1 e `result.output` é `StoreListing`.
4. `test_retry_reaches_the_model_and_a_second_call_happens` — 1ª chamada: `rename_product` com `product="99999"`; 2ª (vendo `RetryPromptPart`): texto → 2 chamadas, `output` é str, e o `RetryPromptPart.content` contém "Não existe produto com id 99999".
5. `test_build_model_uses_the_configured_endpoint` — `Config` com `ai_base_url="https://api.example/v1"`, `ai_model="m"` → `model.model_name == "m"` e a `base_url` do provider começa com o valor (consulte `model.client.base_url` ou o atributo do provider; nenhuma rede).
6. `test_build_model_requires_ai_config` — `Config` sem chave → `ValueError` citando `JULIUS_AI_API_KEY`.
7. `test_model_settings_carry_request_extras` — `ai_request_extras={"thinking": {"type": "disabled"}}` → `agent.model_settings["extra_body"] == {...}`; sem extras → sem a chave `extra_body`; `max_tokens == 600` nos dois casos.
8. `test_system_prompt_has_version_and_the_eight_rules` — `BOT_PROMPT_VERSION == "1"`; o texto contém (case-insensitive) "uma ação", "id", "confirmar"/"confirmação", "não afirme"/"nunca afirme", e cita `search_prices` e `compare_stores`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; `tests/test_architecture.py` verde (`agent.py` importa `config`, `domain`, `bot`).
- [ ] `grep -n "DeepSeekProvider\|@agent.tool" julius/bot/agent.py` **vazio**.
- [ ] `grep -n "PROMPT_VERSIONS" julius/bot/` **vazio**.

## Notas para o agente

- O nome exato do modelo (`deepseek-flash` vs `deepseek-v4-flash`) **não** é decidido aqui — vem de `JULIUS_AI_MODEL`, como hoje. O smoke test real (162) é quem confirma.
- Se `ModelSettings` na versão instalada não aceitar `extra_body` como chave (é um `TypedDict`), a construção com `**` continua válida; não invente um wrapper.
- Não registre `resolve_product`/`resolve_store` como ferramentas — são helpers.
