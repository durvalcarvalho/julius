# 166: `Deps.client` e a fiação do `HttpLlmClient` em `app.py`

> O bot ganha o mesmo cliente de IA que a curadoria já usa, construído uma vez na partida — sem isso, `narrate` (163) não tem como ser chamado a partir do turno.

## Contexto

Parte do design v2.7. Independente de 163–165 (não usa `narrate`, só prepara o transporte); os tickets 167 e 168 dependem deste.

`julius/bot/agent.py` já constrói um `Model` do `pydantic_ai` a partir da `Config` (`build_model`) para o roteamento — isso não muda. O que falta é o cliente `LlmClient` (protocolo de `infra/llm_client.py`) que `services/suggestions.py` usa, que o bot nunca precisou até agora.

## Escopo

### Dentro
- `julius/bot/actions.py::Deps` ganha um quarto campo: `client: LlmClient | None = None` (import de `julius.infra.llm_client`).
- `julius/bot/app.py::build_application` cria `application.bot_data["client"] = HttpLlmClient.from_config(settings)`.
- `julius/bot/app.py::on_text` passa `client=context.bot_data.get("client")` ao construir `Deps`.

### Fora
- `on_tap` não precisa do client (a execução de escrita não narra nada neste ticket — narrar o resultado da escrita é o 168, que reaproveita este mesmo campo).
- Qualquer chamada a `narrate`/`_narrate` (→ 167, 168) — este ticket só prepara o transporte, não o usa.
- Mudar `bot/agent.py` — o `Model` do roteamento e o `LlmClient` da narração são objetos diferentes, construídos de formas diferentes, e continuam assim.

## Requisitos

### Funcionais
- `Deps` continua um dataclass `frozen=True`; o campo novo tem default `None`, então toda construção existente (`Deps(conn=..., config=...)`, em produção e em teste) continua válida sem mudança.
- `HttpLlmClient.from_config(settings)` devolve `None` quando `settings.ai_configured` é falso — mas `check_startup` já exige IA configurada antes do bot subir, então na prática o client é sempre não-`None` em produção; o campo aceita `None` porque testes constroem `Deps` sem client, e porque "sem client" precisa continuar sendo um estado válido (equivalente a "IA não configurada", mesmo padrão do resto do bot).

### Validação e erros
- Nenhum comportamento observável muda para quem não usa o campo novo — é aditivo.

## Especificação técnica

```
modificar julius/bot/actions.py — import LlmClient; campo Deps.client
modificar julius/bot/app.py     — import HttpLlmClient; bot_data["client"]; Deps(..., client=...) em on_text
modificar tests/test_bot_app.py — client presente em build_application
```

### Padrão a seguir
- `HttpLlmClient.from_config` (`julius/infra/llm_client.py`) já existe e é usado pela CLI; não criar uma segunda forma de construir o cliente.
- `_settings_and_agent` (mesmo arquivo) é o precedente de "ler algo de `bot_data`" — não precisa mudar essa função; leia `context.bot_data.get("client")` direto em `on_text`, como o padrão mínimo pede.

## Testes obrigatórios

1. `test_build_application_stores_a_client_when_ai_is_configured` — `application.bot_data["client"]` é uma instância de `HttpLlmClient`.
2. `test_deps_client_defaults_to_none` — `Deps(conn=conn, config=cfg).client is None`.
3. Suíte de `test_bot_app.py`/`test_bot_turn.py` já existente continua verde sem edição (a prova de que o campo é aditivo).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `tests/test_bot_app.py::test_the_bot_reads_no_environment_of_its_own` continua verde (nenhum `os.environ`/`getenv` novo em `bot/`).
- [ ] `tests/test_bot_app.py::test_importing_the_app_has_no_side_effects_on_disk` continua verde.

## Notas para o agente

- Não construa o `HttpLlmClient` dentro de `on_text` a cada mensagem — uma vez em `build_application`, igual ao `agent`.
- Não toque `on_tap`: a confirmação de escrita sem comentário de personagem (ticket 168) não precisa do client no momento do tap propriamente dito, só no momento de montar a resposta depois — mas isso já é escopo do 168, não deste.
