# Design: o bot nunca mais afirma algo que não checou, e por que ele às vezes escolhe não checar

> Direto de um incidente real, 2026-09-19 22:00 — sem brainstorm separado, a pedido explícito do usuário ("quero resolver esse problema, para ele nunca mais mentir... e além disso quero resolver o motivo da falha"). Screenshot: "qual mercado é mais barato pra tomate e cebola?" voltou *"Não consegui ver os resultados — as buscas voltaram vazias, sem nenhum dado de preço. Isso costuma acontecer quando o histórico de cupons ainda não foi importado (ou a importação falhou)."* — falso: o banco tem 133 produtos, 169 preços, e a mesmíssima pergunta tinha funcionado 68 minutos antes, na mesma conversa de bot, com `compare_stores` achando tomate e cebola sem problema.

## Achado que decide o design inteiro

**Medido, não suposto — o banco não zerou e o código de hoje não é a causa.** `SELECT count(*)` contra `~/.local/share/julius/prices.db` no momento do incidente: 7 mercados, 133 produtos, 169 preços — mais dado do que a última vez que medimos, não menos. `ps` no processo (`julius-bot`, PID 302138) mostra `STARTED 19:26:01` — rodando desde **antes** de qualquer correção da sessão de `/sc:implement` de hoje (`match_kind`, categoria, `check_price`, ordem da resposta). Nada disso está em produção ainda; o processo em pé é o código de ontem.

**O log do modelo prova que ele mentiu, não que ele errou uma conta.** `ai_calls.jsonl`, 2026-09-19T22:00:16, `call_kind: bot_turn`, `raw_response: "text"` — o modelo **não chamou ação nenhuma**. Comparando com a mesma pergunta, mesma sessão de bot, 20:52:41: `raw_response: "ShoppingComparison"` (chamou `compare_stores`, achou os dois itens, respondeu certo). Uma única chamada HTTP em cada caso (confirmado pelo stdout do bot que o usuário colou: um `POST .../chat/completions` por mensagem, sem retry). **Mesma pergunta, mesmo código, mesmo banco, duas decisões de roteamento diferentes** — isso é a assinatura de não-determinismo do modelo na escolha da ação, não um bug determinístico no código.

**Duas coisas pedidas, duas causas diferentes, dois remédios diferentes:**
1. "Nunca mais mentir" / "lidar com a falha graciosamente" → o problema não é o modelo errar a rota às vezes (isso o projeto já mede e aceita, `MIN_ROUTING_HITS = 0.7` em `test_real_ai.py`) — é que, quando erra pra texto livre, **nada impede o texto de inventar um motivo**. O caminho de ação (`ALL_ACTIONS`) é auto-limitado: uma ação só pode relatar o que o banco realmente devolveu. O caminho de texto livre (`str` em `BotOutput`) não tem nenhuma guarda — é a mesma assimetria que a guarda de dinheiro (`narrate()`/`_money_values`) já resolveu para a persona, só que nunca foi replicada pro agente.
2. "Resolver o motivo da falha" → `build_model`/`build_agent` (`bot/agent.py`) não define `temperature` nenhuma. A própria documentação do `pydantic_ai` (`ModelSettings.temperature`) recomenda: *"Use temperature closer to 0.0 for analytical / multiple choice"* — exatamente a forma da decisão aqui (escolher 1 entre 15 ações, ou texto). Sem isso, o provedor usa o default dele (tipicamente 1.0), e a escolha de rota fica sujeita a variação de amostragem — o motivo mais provável, e o único que explica duas respostas diferentes pra a mesma entrada.

## Decisão 1 — guarda: texto livre nunca afirma o que só uma ação pode confirmar

**Mecanismo testado nesta sessão, não só lido na documentação** — dois experimentos com `FunctionModel`, reproduzindo exatamente a forma do bot real (`output_type=[str, ...]`, `retries=2`):

```python
@agent.output_validator
def no_unlicensed_data_claims(ctx: RunContext[Deps], data: BotOutput) -> BotOutput:
    if isinstance(data, str) and _claims_unchecked_data(data):
        raise ModelRetry(
            "Sua resposta afirmou algo sobre busca, importação ou catálogo sem ter chamado "
            "nenhuma ação -- isso não pode ser verdade se nenhuma ação rodou. Chame agora a ação "
            "certa (search_prices, compare_stores, list_products ou list_stores) pra essa "
            "pergunta e responda com o resultado de verdade."
        )
    return data
```

**A mensagem do retry tem UMA saída só, de propósito — corrigido depois de revisão.** A primeira versão desta decisão oferecia duas ("chame a ação certa, ou responda sem essa afirmação") — a segunda opção é a mais barata pro modelo, e um modelo que acabou de inventar "as buscas voltaram vazias" pode simplesmente tirar as palavras proibidas e devolver "Não consegui te ajudar com isso agora": passa pela lista de frases, chega ao usuário, e continua sendo uma não-resposta pra uma pergunta que `compare_stores` teria respondido — mentira removida, falha mantida, uma chamada a mais gasta à toa. A mensagem final não dá esse escape: ou o modelo chama a ação, ou esgota os `retries` e cai na Decisão 2, que já é honesta sobre não ter conseguido.

Resultado medido: com um `FunctionModel` que responde a frase da captura de tela na primeira tentativa e uma resposta limpa na segunda, **2 chamadas ao modelo, saída final limpa** — o `ModelRetry` consumiu 1 dos 2 `retries` já configurados em `build_agent`, sem nenhuma mudança de config. Com um `FunctionModel` que insiste na frase proibida em toda tentativa: `UnexpectedModelBehavior: Exceeded maximum output retries (2)` — uma exceção, nunca a frase mentirosa chegando ao usuário.

`isinstance(data, str)` é obrigatório e suficiente: `OutputValidator.validate()` (lido na fonte do `pydantic_ai` instalado, `_output.py`) chama a função com o resultado **de qualquer tipo do `output_type`**, sem filtrar por type hint — a guarda que decide o que checar é a nossa, exatamente como o `isinstance`/regex de `_money_values` já faz na persona.

**`_claims_unchecked_data`, o sinal que decide quando barrar — estreito de propósito, não um classificador de tópico.** Não tenta adivinhar se a PERGUNTA do usuário merecia uma ação (isso exigiria reimplementar o roteamento pra checar o roteamento). Em vez disso, olha só a RESPOSTA do modelo: relatar estado do sistema (busca vazia, importação falhou, catálogo sem dado) é exatamente o que só uma ação tem licença de fazer.

**Por frase, não por palavra solta — corrigido depois de revisão, e por um motivo medido, não por cautela genérica.** A primeira versão desta decisão usava palavras soltas ("busca", "resultado", "importa", "cadastr"). Não dá pra confirmar que isso é seguro contra o comportamento correto mais importante deste bot — a pergunta de esclarecimento ("qual mercado tá mais barato?" sozinho → texto perguntando o que a pessoa quer comprar, RF1 de `docs/design/shopping-list-conversation-context.md`) — porque **essa frase exata nunca foi logada**: `bot/turn.py::_output_kind` (linha ~95) colapsa toda saída de texto livre pra string fixa `"text"` antes de gravar em `ai_calls.jsonl`; o único texto livre real que temos por escrito é o desta captura de tela, coincidência de o usuário ter mandado print. Palavra solta arriscava pegar "busca"/"resultado" numa resposta de esclarecimento legítima que use essas palavras à toa; frase inteira, tirada literalmente da única fabricação real observada, não:

```python
_UNLICENSED_DATA_CLAIMS = (
    "buscas voltaram vazias", "busca voltou vazia", "não consegui ver os resultados",
    "sem nenhum dado de preço", "histórico de cupons", "não foi importado", "importação falhou",
    "não está cadastrado no banco", "banco de dados",
)
```

Nenhuma dessas frases tem por que aparecer numa pergunta curta tipo "o que você quer comprar?" ou numa recusa educada de assunto fora do catálogo. Lista deliberadamente pequena e literal ao caso real — mesma disciplina de todo cutoff deste projeto (nasce de UM caso, cresce com o próximo, nunca generaliza sem evidência nova).

**A lacuna de log que impediu medir isso direito vale fechar junto.** `bot/turn.py::_charge` grava `raw_response=_output_kind(result.output)` — pra texto livre, sempre a string fixa `"text"`, nunca o conteúdo. É por isso que hoje não existe corpus de respostas em texto livre reais pra calibrar `_UNLICENSED_DATA_CLAIMS` contra nada além deste único incidente. `_charge` passa a gravar o texto de verdade quando `isinstance(result.output, str)` (mesmo campo `raw_response`, sem mudar o schema do log) — barato (o texto já existe em memória) e é exatamente o que faltou pra investigar este incidente sem precisar reconstruir tudo a partir de uma captura de tela.

## Decisão 2 — quando a guarda esgota as tentativas, a queda já é graciosa (confirmar, não construir)

`UnexpectedModelBehavior` é `RuntimeError` → `Exception`. `bot/turn.py::handle_text` já envolve `await agent.run(...)` num `try/except Exception`, devolvendo `AI_UNREACHABLE` ("Não consegui falar com a IA agora. Tente de novo em instantes.") — testado nesta sessão, é exatamente o que acontece quando a Decisão 1 esgota os retries. Nenhuma mudança de código é necessária pra "nunca mostrar a mentira": ela já não chegaria à pessoa.

**Melhoria opcional, não bloqueante**: `AI_UNREACHABLE` sugere problema de rede, que não é a causa aqui. Distinguir `UnexpectedModelBehavior` do erro genérico (`except UnexpectedModelBehavior: return Reply(f"{prefix}{COULD_NOT_CONFIRM}")`, uma frase nova tipo "Não consegui confirmar isso com segurança — tenta perguntar de novo, mais direto?") é mais honesto sobre a causa, mas não é o que impede a mentira — isso já está resolvido pela guarda existir. Fica como refinamento de UX pro `/sc:implement` decidir.

## Decisão 3 — causa raiz: `temperature` baixa para uma decisão de múltipla escolha

`build_agent` (`bot/agent.py`) ganha `temperature` em `ModelSettings`, ao lado de `max_tokens`:

```python
ROUTING_TEMPERATURE = 0.0
"""Escolher 1 de 15 ações é 'analytical / multiple choice' -- a própria documentação do
ModelSettings.temperature do pydantic_ai recomenda 0.0 para esse tipo de tarefa, sem ressalva
nenhuma a favor de uma margem acima disso; sem `temperature` nenhuma (o estado de hoje), o
provider usa o default dele, tipicamente 1.0. A mesma documentação avisa que 'mesmo com
temperature 0.0 os resultados não são totalmente determinísticos' -- é por isso que a Decisão 1
continua obrigatória mesmo depois desta mudança, não uma rede de segurança descartável. Medir o
efeito real via `tests/test_real_ai.py --real-ai` (MIN_ROUTING_HITS) antes/depois."""
settings = ModelSettings(max_tokens=MAX_OUTPUT_TOKENS, temperature=ROUTING_TEMPERATURE)
```

**Isto reduz a frequência do problema, não o elimina** — é exatamente por isso que a Decisão 1 continua sendo a peça obrigatória, não uma rede de segurança descartável depois que isto entrar no ar.

## Achado colateral: as duas versões do `pydantic-ai` não são a mesma

O banner do bot em produção mostra `pydantic-ai v2.45.0`; o `.venv` de desenvolvimento/teste deste repositório tem `v2.44.0`. `pyproject.toml` não fixa versão nenhuma (`"pydantic-ai-slim[openai]"`, sem `==`/`>=`) — os dois ambientes simplesmente instalaram o que era mais recente no dia em que cada um rodou `pip install`. Não há evidência de que isso causou o incidente (o mecanismo de `output_validator`/`ModelSettings.temperature` existe nas duas versões), mas é uma lacuna de reprodutibilidade real: um teste verde no `.venv` não garante o mesmo comportamento em produção. Fixar uma versão exata (`pydantic-ai-slim[openai]==2.45.0`, a que já está rodando de verdade) e alinhar o `.venv` de dev a ela é higiene básica, não parte do incidente — mas vale fazer junto, já que foi descoberto no caminho.

## O que muda, arquivo por arquivo

| Arquivo | Mudança |
|---|---|
| `julius/bot/agent.py` | `ROUTING_TEMPERATURE = 0.0` em `ModelSettings` (Decisão 3). `build_agent` ganha `@agent.output_validator` com a guarda da Decisão 1. `SYSTEM_PROMPT` ganha uma frase proibindo afirmar estado de busca/catálogo/importação em texto livre sem ter chamado a ação correspondente (reforço em paralelo à guarda de código, mesma disciplina da guarda de dinheiro na persona). |
| `julius/bot/turn.py` | `_charge` grava o texto real quando a saída é `str` (fecha a lacuna de log da Decisão 1). Opcional (Decisão 2): capturar `UnexpectedModelBehavior` separado do `Exception` genérico, mensagem própria. |
| `pyproject.toml` | Fixar `pydantic-ai-slim[openai]==2.45.0` (achado colateral). |
| `tests/test_bot_agent.py` | Teste novo: `FunctionModel` que devolve texto com palavra proibida na 1ª tentativa e texto limpo na 2ª → saída final limpa, 2 chamadas ao modelo (reproduz o experimento desta sessão). Teste novo: `FunctionModel` que insiste sempre → `UnexpectedModelBehavior` capturada por `handle_text`, nunca a frase proibida no `Reply`. |

Nenhuma migração de banco. Nenhuma dependência nova (o mecanismo já existe na biblioteca instalada).

## O que NÃO está sendo decidido aqui

- Lista definitiva de `_UNLICENSED_DATA_CLAIMS` — nasce de 1 caso real, cresce com o próximo (agora logado de verdade), mesma disciplina de `NEAR_MISS_CUTOFF`.
- Detectar "a pergunta do usuário merecia uma ação" (analisar a pergunta, não a resposta) — mais caro, mais frágil, e o sinal na resposta já resolve o caso medido.
- Recalibrar `ROUTING_TEMPERATURE` pra cima de 0.0 — só se `MIN_ROUTING_HITS` de `test_real_ai.py --real-ai` piorar por algum motivo inesperado; a recomendação da própria biblioteca já é o valor final, não um palpite a ajustar por padrão.
- Mensagem final de `UnexpectedModelBehavior` (Decisão 2) — texto exato fica para `/sc:implement`.
- Alinhar `.venv` de dev à versão de produção além de fixar o pin — mecânica de reinstalar, não design.

## Próximo passo

`/sc:implement`: Decisão 1 (guarda) e Decisão 3 (temperatura) primeiro, testadas com `FunctionModel` (já esboçado e comprovado nesta sessão); Decisão 2 (mensagem de queda) e o pin de versão depois. Medir `MIN_ROUTING_HITS` antes/depois com `tests/test_real_ai.py --real-ai` é o que fecha "resolver o motivo da falha" com número, não só com teoria.
