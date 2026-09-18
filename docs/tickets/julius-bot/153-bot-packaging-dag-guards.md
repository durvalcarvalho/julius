# 153: Dependências do bot, a linha `bot` na DAG e as guardas de teste

<!-- status:done implemented:2026-09-17 commit:4a759ac -->
<!-- adjustments: guarda de modelo em tests/test_bot_guards.py, uma das duas opções do próprio ticket -->

> Antes de existir código do bot, o projeto passa a saber que ele existe: o que ele pode importar, o que ninguém pode importar dele, e que nenhum teste fala com um modelo de verdade.

## Contexto

`docs/design/telegram-bot.md` §1 e §7. A camada nova precisa entrar em `tests/test_architecture.py::ALLOWED_IMPORTS` (senão `test_every_module_belongs_to_a_declared_layer` falha no primeiro módulo de 154), as dependências precisam estar instaláveis para os testes rodarem, e a mesma disciplina do `_no_cnpj_lookup` vale para a IA: **nenhum teste toca a API**.

Não depende de nenhum ticket. Tudo de 154 em diante depende deste.

## Escopo

### Dentro
- `pyproject.toml`: extra `bot`; o extra `dev` passa a incluir as mesmas duas dependências (a suíte importa `pydantic_ai` e `telegram`).
- `julius/bot/__init__.py` — pacote vazio, com docstring de uma linha dizendo o que a camada é.
- `tests/test_architecture.py`: `"bot": {"domain", "config", "infra", "services"}`.
- `tests/test_cli.py`: teste de que `import julius.cli` não carrega `telegram` nem `pydantic_ai`.
- `tests/conftest.py`: autouse `_no_model_requests` (`pydantic_ai.models.ALLOW_MODEL_REQUESTS = False`).
- `Makefile`: nada neste ticket (o alvo `install-bot` vem com o executável, → 161).

### Fora
- `[project.scripts] julius-bot` (→ 161: só existe quando `main()` existir — regra do `CLAUDE.md`: nada registrado antes do que ele chama).
- Qualquer módulo além do `__init__.py` vazio.
- Pinar versão exata de biblioteca.

## Requisitos

### Funcionais
- `pyproject.toml`:
  ```toml
  [project.optional-dependencies]
  dev = ["pytest", "python-telegram-bot>=21", "pydantic-ai-slim[openai]"]
  bot = ["python-telegram-bot>=21", "pydantic-ai-slim[openai]"]
  ```
  `>=21` porque a API assíncrona (`Application`, `filters`) é a da v20+, e 21 é a primeira sem avisos de depreciação relevantes. `pydantic-ai-slim[openai]`, não `pydantic-ai`: só o provider OpenAI-compatível (formato da API do DeepSeek), sem os outros vendors.
- `ALLOWED_IMPORTS["bot"] = {"domain", "config", "infra", "services"}` — sem `parsers` (o bot não lê recibo), sem `repositories`, sem `cli`. A linha de `cli` **não** muda (cli não pode importar bot).
- `julius/bot/__init__.py` importa nada de terceiro (o guarda de `test_cli.py` não é afetado por ele, mas o hábito começa aqui).
- `conftest.py`:
  ```python
  @pytest.fixture(autouse=True)
  def _no_model_requests(monkeypatch):
      """Nenhum teste fala com um modelo de verdade — irmão de _no_cnpj_lookup."""
      from pydantic_ai import models
      monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
  ```

### Validação e erros
- `python -c "import julius.cli"` continua sem efeito em disco (teste existente) **e** sem `telegram`/`pydantic_ai` em `sys.modules`.

## Especificação técnica

```
modificar pyproject.toml              — extras dev e bot
criar     julius/bot/__init__.py      — vazio (docstring)
modificar tests/test_architecture.py  — linha "bot" em ALLOWED_IMPORTS
modificar tests/test_cli.py           — teste de import sem dependências do bot
modificar tests/conftest.py           — _no_model_requests autouse
```

### Padrão a seguir
- `tests/test_cli.py::test_importing_the_cli_has_no_side_effects_on_disk` — mesmo `subprocess.run([sys.executable, "-c", ...])`; o código a rodar: `import julius.cli, sys; assert "telegram" not in sys.modules and "pydantic_ai" not in sys.modules`.
- `conftest.py::_no_cnpj_lookup` — mesma forma (autouse + monkeypatch + docstring com o porquê).

## Testes obrigatórios

1. `test_importing_the_cli_does_not_load_bot_dependencies` (em `test_cli.py`) — subprocess como descrito; `check=True`.
2. `test_model_requests_are_blocked_in_the_suite` (em `tests/test_architecture.py` ou novo `tests/test_bot_guards.py`) — `from pydantic_ai import models; assert models.ALLOW_MODEL_REQUESTS is False`.
3. `tests/test_architecture.py` continua verde com o pacote `julius/bot/` vazio presente (prova que a linha nova está lá).

## Critérios de aceite
- [ ] `.venv/bin/pip install -e '.[dev]'` instala `pydantic-ai-slim` e `python-telegram-bot` (o alvo `make test` já roda esse comando ao criar o `.venv`; num `.venv` existente, rode-o à mão).
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n '"bot"' tests/test_architecture.py` mostra a linha com exatamente os quatro nomes.
- [ ] `grep -n "julius-bot" pyproject.toml` **vazio** (o script é do 161).

## Notas para o agente

- Não adicione `pydantic_ai`/`telegram` a nenhum módulo fora de `julius/bot/` — nem em `conftest.py` no nível do módulo (o import fica dentro da fixture, para a suíte continuar importável num ambiente sem o extra `bot`... que não existe mais depois deste ticket, mas o hábito é o mesmo do `cnpj_client`).
- Se `pip` reclamar da sintaxe do extra `pydantic-ai-slim[openai]` dentro de uma lista, as aspas estão certas — o problema é outro; não troque para `pydantic-ai` completo.
