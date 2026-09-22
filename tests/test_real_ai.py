"""Os únicos testes que falam com o DeepSeek de verdade. Só rodam com `--real-ai`.

Por que existem: o resto da suíte usa `FunctionModel`, que prova a fiação e não prova nada sobre o
modelo. Estas perguntas só a rede responde — e como a resposta muda de rodada para rodada, este
arquivo separa duas coisas que costumam ser confundidas:

- **Invariantes** (assert de verdade): não dependem do que o modelo escolheu. Uma escrita nunca
  grava sem o toque; nenhuma exceção atravessa um turno; o orçamento é cobrado. Se um destes
  quebra, é bug nosso, não humor do modelo.
- **Roteamento** (medido e reportado): o modelo escolheu a ação que um humano escolheria? Uma
  falha isolada aqui é ruído; o que importa é a taxa, e é por isso que o assert é sobre o
  agregado. Um teste que fica vermelho por flutuação ensina a ignorar a suíte.

Segurança: roda sempre numa **cópia** do banco (`JULIUS_DB` nunca é tocado) e pula com motivo
claro quando as credenciais não estão no ambiente. Custa dinheiro de verdade — a conta da rodada
sai impressa no fim.
"""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from julius import config as config_module
from julius.bot.actions import Deps, PendingWrite, ProductListing, ShoppingComparison, StoreListing
from julius.bot.agent import build_agent
from julius.bot.turn import ChatState, handle_tap, handle_text
from julius.domain.models import PriceCheck, SearchOutcome
from julius.bot import render
from julius.infra import db
from julius.infra.llm_client import HttpLlmClient
from julius.services import catalog, search as search_service, suggestions

pytestmark = pytest.mark.real_ai

# Quantas das perguntas de roteamento precisam cair na ação certa para a rodada valer. Não é 100%:
# o modelo é não-determinístico e uma escolha defensável pode divergir da nossa. Abaixo disto não é
# flutuação, é regressão — de prompt, de modelo ou de schema.
MIN_ROUTING_HITS = 0.7

# Uma pergunta, e a ação que um humano escolheria para ela. Os nomes vêm de `__name__` para que
# renomear uma classe de domínio quebre este arquivo, em vez de fazer todos os casos errarem em
# silêncio -- mesma razão de os testes do agente derivarem `final_result_<nome>`.
ROUTING_CASES = (
    ("quanto paguei de picanha?", SearchOutcome.__name__),
    # Sem lista, o bot tem de perguntar em vez de comparar o catálogo inteiro (ticket 178, RF1) --
    # "qual mercado tá mais barato" sozinho não é mais uma chamada de compare_stores.
    ("qual mercado tá mais barato?", "text"),
    ("qual mercado é mais barato pra tomate e cebola?", ShoppingComparison.__name__),
    # docs/design/quantity-aware-verdict.md: check_price nunca tinha sido exercitado numa rodada
    # real -- este é o caso base (preço visto ao vivo), antes de medir o loop de quantidade.
    ("aqui o quilo do tomate tá 9,90, tá bom?", PriceCheck.__name__),
    ("que produtos eu tenho no catálogo?", ProductListing.__name__),
    ("quais mercados eu já usei?", StoreListing.__name__),
    ("bom dia, tudo bem?", "text"),
)

# Nomes reais de saída de ação -- o que `raw_response` carrega quando NÃO é texto livre. Desde
# que `handle_text` passou a logar o texto de verdade em vez da string fixa "text" (docs/design/
# agent-output-honesty.md, Decisão 1: era a lacuna que impedia investigar um texto fabricado),
# "esperado == 'text'" não pode mais comparar por igualdade -- vira "não é nenhum destes nomes".
# Uma resposta em português nunca vai colidir por acidente com um destes.
_ACTION_OUTPUT_NAMES = {
    SearchOutcome.__name__,
    ShoppingComparison.__name__,
    ProductListing.__name__,
    StoreListing.__name__,
    PriceCheck.__name__,
}


def _is_free_text(raw_response: str) -> bool:
    return raw_response not in _ACTION_OUTPUT_NAMES and not raw_response.startswith("PendingWrite:")

_SPENT: list[float] = []


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    """Uma cópia do banco real: dá dados de verdade para o modelo buscar, e nada do que estes
    testes fizerem alcança `~/.local/share/julius/`. Os logs caem na cópia junto."""
    live = config_module.load()
    if not (live.ai_configured and live.ai_input_price_usd_per_1m and live.ai_output_price_usd_per_1m):
        pytest.skip(
            "IA não configurada no ambiente: exporte JULIUS_AI_API_KEY, JULIUS_AI_BASE_URL, "
            "JULIUS_AI_MODEL e os dois preços por token (ver docs/como-testar-o-bot.md)"
        )
    if not live.db_path.exists():
        pytest.skip(f"banco não existe em {live.db_path}; rode `julius importar` antes")

    copy = tmp_path_factory.mktemp("real-ai") / "prices.db"
    shutil.copy2(live.db_path, copy)
    return config_module.load({**_env_of(live), "JULIUS_DB": str(copy)})


def _env_of(live) -> dict[str, str]:
    """As mesmas credenciais, apontadas para a cópia. Reconstruído em vez de `replace` para o teste
    passar pelo mesmo `config.load` que a produção usa."""
    env = {
        "JULIUS_AI_API_KEY": live.ai_api_key or "",
        "JULIUS_AI_BASE_URL": live.ai_base_url or "",
        "JULIUS_AI_MODEL": live.ai_model or "",
        "JULIUS_AI_BUDGET_USD": str(live.ai_budget_usd),
        "JULIUS_AI_INPUT_PRICE_USD_PER_1M": str(live.ai_input_price_usd_per_1m),
        "JULIUS_AI_OUTPUT_PRICE_USD_PER_1M": str(live.ai_output_price_usd_per_1m),
    }
    if live.ai_request_extras:
        env["JULIUS_AI_REQUEST_EXTRAS"] = json.dumps(live.ai_request_extras)
    return env


@pytest.fixture
def deps(settings):
    conn = db.connect(settings.db_path)
    yield Deps(conn=conn, config=settings)
    conn.close()


def _ask(deps: Deps, text: str, state: ChatState | None = None):
    agent = build_agent(deps.config)
    return asyncio.run(handle_text(agent, state or ChatState(), deps, text))


def _last_call(deps: Deps) -> dict:
    return json.loads(deps.config.ai_log_path.read_text(encoding="utf-8").splitlines()[-1])


def _kind(output: object) -> str:
    if isinstance(output, PendingWrite):
        return f"PendingWrite:{output.action}"
    return "text" if isinstance(output, str) else type(output).__name__


def _snapshot(deps: Deps) -> list:
    return [catalog.get_product(deps.conn, p.id) for p in catalog.list_products(deps.conn)]


def _guinea_pig(deps: Deps):
    """Pelo menor id, não pela primeira linha: `list_products` ordena por nome, então renomear
    dentro de um teste mudaria quem é o `[0]` do teste seguinte."""
    return min(catalog.list_products(deps.conn), key=lambda product: product.id)


# --- o que a rede responde, e nada mais ------------------------------------------


def test_the_model_answers_at_all_and_thinking_is_disabled(deps):
    """A pergunta nº 1 do projeto. Se o `thinking` não foi desligado, o modelo gasta os 600 tokens
    raciocinando e o turno volta truncado ou vazio — a assinatura medida em 15/09.

    `output_tokens` é reportado, não usado como corte: o limite honesto é "veio resposta usável",
    e o número serve para você ver a folga."""
    before = suggestions.spent_this_month(deps.conn)

    reply = _ask(deps, "quanto paguei de picanha?")
    call = _last_call(deps)
    _SPENT.append(call["cost_usd"])

    print(
        f"\n  modelo={deps.config.ai_model}  saída={call['output_tokens']} tok  "
        f"entrada={call['input_tokens']} tok  {call['latency_ms']} ms  "
        f"US$ {call['cost_usd']:.6f}  tipo={call['raw_response']}"
    )

    assert call["error"] is None, (
        f"o modelo não devolveu resposta usável (error={call['error']!r}). Se `output_tokens` está "
        f"perto de 600, o thinking NÃO foi desligado: confira JULIUS_AI_REQUEST_EXTRAS."
    )
    assert reply.text, "resposta vazia"
    assert suggestions.spent_this_month(deps.conn) > before, "a chamada não foi cobrada do orçamento"
    if call["output_tokens"] > 400:
        print(f"  ⚠️  saída alta ({call['output_tokens']} tok) — suspeite do thinking ligado")


def test_reading_questions_route_to_the_right_action(deps):
    """Medido, não exigido por caso: o modelo é não-determinístico e uma escolha divergente pode
    ser defensável. O assert é sobre a taxa — é ela que cai quando prompt, modelo ou schema
    regridem."""
    results = []
    for message, expected in ROUTING_CASES:
        reply = _ask(deps, message)
        got = _last_call(deps)
        _SPENT.append(got["cost_usd"])
        hit = _is_free_text(got["raw_response"]) if expected == "text" else got["raw_response"] == expected
        results.append((message, expected, got["raw_response"], hit))
        print(f"\n  {'✅' if hit else '❌'} {message!r}\n     esperado={expected}  veio={got['raw_response']}")
        assert reply.text, f"resposta vazia para {message!r}"

    hits = sum(1 for *_, hit in results if hit)
    rate = hits / len(results)
    print(f"\n  roteamento: {hits}/{len(results)} ({rate:.0%})")
    assert rate >= MIN_ROUTING_HITS, (
        f"o modelo acertou só {hits}/{len(results)}. Isso não é flutuação — veja se o prompt "
        f"(BOT_PROMPT_VERSION), o modelo ou o schema das ações mudaram. Detalhe: {results}"
    )


def test_the_original_coca_incident_no_longer_says_not_in_catalog(deps):
    """Regressão de ponta a ponta do incidente real (2026-09-21) que abriu
    docs/requirements/kind-resolution-in-routing.md: a mesma frase do usuário, contra o modelo de
    verdade, não pode mais terminar em "não tá no catálogo" -- o produto (Coca-Cola Zero/original)
    sempre existiu; o que faltava era resolver "coca" -> "refrigerante", que o patch determinístico
    (`_match_kind_via_product`) já cobre desde o `/sc:troubleshoot --fix` desta mesma sessão."""
    reply = _ask(deps, "Devo comprar uma coca por 12 reais?")
    call = _last_call(deps)
    _SPENT.append(call["cost_usd"])

    print(f"\n  {call['raw_response']}: {reply.text}")
    assert call["raw_response"] == PriceCheck.__name__, f"esperava check_price, veio {call['raw_response']}"
    assert "não tá no catálogo" not in reply.text.lower()
    assert "não conheço" not in reply.text.lower()


def test_a_real_brand_ambiguity_becomes_a_question_not_a_guess(deps):
    """"pepsi" bate em dois produtos reais do catálogo de produção que discordam de kind
    (Refrigerante Pepsi vs. Cream cheese President -- o mesmo falso positivo do scorer de palavra
    já documentado em MATCH_SCORE_CUTOFF, medido ao vivo contra este banco antes de escrever este
    teste). `_resolve_kind` levanta ModelRetry com os dois candidatos; o modelo, seguindo o
    SYSTEM_PROMPT, deve perguntar em texto -- nunca inventar um veredito de sim/não."""
    reply = _ask(deps, "a pepsi tá 8 reais o litro, tá bom?")
    call = _last_call(deps)
    _SPENT.append(call["cost_usd"])

    print(f"\n  {reply.text}")
    assert _is_free_text(call["raw_response"]), f"esperava texto perguntando, veio {call['raw_response']}"
    assert reply.text, "resposta vazia"


def test_zero_result_fallback_never_asks_for_price_or_store_back(settings):
    """docs/requirements/bot-persona-fallback-improvements.md §9/§10, Caso 1 -- valida os dois
    remédios de docs/design/fallback-voice-and-context-prompts.md §1 de ponta a ponta.

    Achado ao escrever este teste: a fixture `deps` compartilhada do resto deste arquivo NUNCA
    passa `client=`, e `bot/turn.py::_render_output`/`_render_no_match` tratam `deps.client is
    None` como "sem narração" (mesmo com a IA configurada) -- o resto da suíte mede só ROTEAMENTO
    (qual ação foi chamada), nunca a narração da persona, exatamente como o docstring do arquivo
    já dizia ("Roteamento (medido e reportado)"). Sem um client de verdade aqui, este teste
    validaria só o caminho "Nenhum resultado." puro, nunca `no_match_fallback_line` (Remédio A)
    nem o exemplo novo do prompt `persona` (Remédio B) -- por isso monta seu próprio `Deps` com
    `HttpLlmClient`, em vez de reaproveitar a fixture `deps`.

    "feijão" é o mesmo termo do exemplo novo em SYSTEM_PROMPTS["persona"] e, medido contra o
    catálogo real (2026-09-22), não existe produto de feijão cadastrado -- garante que
    search_prices roda e o caminho de zero-resultado é de fato exercitado."""
    conn = db.connect(settings.db_path)
    try:
        deps = Deps(conn=conn, config=settings, client=HttpLlmClient.from_config(settings))
        agent = build_agent(settings)
        reply = asyncio.run(handle_text(agent, ChatState(), deps, "quanto tá o feijão?"))
        call = _last_call(deps)
        _SPENT.append(call["cost_usd"])
    finally:
        conn.close()

    print(f"\n  {reply.text}")
    lowered = reply.text.lower()
    for red_flag in ("me diz o preço", "me diga o preço", "me fala o preço", "me informa o preço", "qual mercado"):
        assert red_flag not in lowered, f"pediu dado de volta: {reply.text!r}"
    assert reply.text != "Nenhum resultado.", "caiu no caminho antigo sem narração nenhuma"


def test_echoing_the_bots_own_remark_does_not_search_for_it_as_a_product(deps):
    """Caso 2 do requisito: a piada real do usuário ("sabe quanto tempo de luz isso paga?") ecoando
    um comentário anterior do próprio Julius, não um pedido de preço novo. Dois turnos de verdade,
    não histórico fabricado -- turno 1 estabelece um comentário real do bot sobre um produto real
    (picanha, já usado em ROUTING_CASES); turno 2 é a piada, sem citar nenhum produto de mercado.
    O SYSTEM_PROMPT (regra nova) deve responder em texto, nunca chamar search_prices com "luz" ou
    "tempo" como se fossem item novo."""
    state = ChatState()
    setup = _ask(deps, "quanto paguei de picanha?", state)
    _SPENT.append(_last_call(deps)["cost_usd"])
    assert setup.text, "resposta vazia no turno de preparo"

    reply = _ask(deps, "sabe quanto tempo de luz isso paga?", state)
    call = _last_call(deps)
    _SPENT.append(call["cost_usd"])

    print(f"\n  turno 1: {setup.text}\n  turno 2 ({call['raw_response']}): {reply.text}")
    assert _is_free_text(call["raw_response"]), f"tratou a piada como item novo: {call['raw_response']}"


def test_a_repeated_price_on_a_similar_item_asks_before_assuming_a_new_product(deps):
    """Caso 3 do requisito, versão fiel ao incidente real: "coca por 12 reais" seguido de
    "refrigerante 2L por 12 reais" -- o MESMO preço repetido é o sinal, não só o tamanho sozinho
    (achado do troubleshoot de 2026-09-22: a primeira versão deste teste não repetia o preço, e por
    isso testava um sinal mais fraco do que o incidente real trazia; o modelo buscou direto porque
    "refrigerante 2 litros" tem resposta real própria -- o catálogo tem um Pepsi 2L de verdade).
    Repetir o preço não ajuda `search_prices` a desambiguar nada sozinho, então só resta perguntar."""
    state = ChatState()
    setup = _ask(deps, "coca por 12 reais, tá bom?", state)
    _SPENT.append(_last_call(deps)["cost_usd"])
    assert setup.text, "resposta vazia no turno de preparo"

    reply = _ask(deps, "e refrigerante 2L por 12 reais?", state)
    call = _last_call(deps)
    _SPENT.append(call["cost_usd"])

    print(f"\n  turno 1: {setup.text}\n  turno 2 ({call['raw_response']}): {reply.text}")
    assert _is_free_text(call["raw_response"]), (
        f"tratou como pergunta nova sem checar se é a mesma compra: {call['raw_response']}"
    )


def test_a_bare_vague_question_asks_for_the_item_instead_of_an_empty_search(deps):
    """Caso 5 do requisito: "tá caro?" sem nenhum item, numa conversa nova (sem histórico pra
    juntar) -- o bot tem de perguntar qual item, nunca chamar search_prices com termo vazio nem dar
    veredito por conta própria."""
    reply = _ask(deps, "tá caro?")
    call = _last_call(deps)
    _SPENT.append(call["cost_usd"])

    print(f"\n  {call['raw_response']}: {reply.text}")
    assert _is_free_text(call["raw_response"]), f"esperava pergunta pelo item, veio {call['raw_response']}"
    assert reply.text, "resposta vazia"


def test_asking_about_the_first_thing_said_answers_correctly(deps):
    """Achado real (monkey test, 2026-09-22): 5 perguntas seguidas (banana, cebola, tomate, uva),
    depois "e do primeiro que eu perguntei mesmo?" -- com a política antiga de histórico (só os
    últimos HISTORY_TURNS turnos), banana já tinha saído da janela e o modelo respondeu "Você
    começou perguntando de cebola", errado e com total confiança.

    Duas correções depois (ticket 181, docs/design/entity-resolution-architecture.md Frente B):
    `bot/turn.py::_trim_history` fixa o turno 1 pra sempre (banana nunca mais sai da janela), e
    `SYSTEM_PROMPT` (v7) passou a mandar checar o histórico visível antes de desistir, não só
    "diga que não lembra" (v5, testado e insuficiente sozinho -- o modelo dizia "não lembro" mesmo
    com banana já visível). As duas juntas, medido ao vivo 2x com duas formulações da pergunta:
    responde "banana" corretamente as duas vezes. Este teste cobra o resultado ideal (não só "não
    inventa mais", que já era o mínimo aceitável) porque isso já foi observado consistentemente --
    se um dia voltar a falhar, é sinal de regressão em `_trim_history` ou no prompt, não ruído."""
    state = ChatState()
    for item in ("banana", "cebola", "tomate", "uva"):
        _ask(deps, f"quanto paguei de {item}?", state)
        _SPENT.append(_last_call(deps)["cost_usd"])

    reply = _ask(deps, "e do primeiro que eu perguntei mesmo, lá no começo?", state)
    call = _last_call(deps)
    _SPENT.append(call["cost_usd"])

    print(f"\n  ({call['raw_response']}): {reply.text}")
    assert "banana" in reply.text.lower(), "o turno 1 (banana) está fixado no histórico -- a resposta certa está disponível"
    assert "cebola" not in reply.text.lower(), "cebola foi a 2ª pergunta, não a 1ª -- não pode aparecer como se fosse"


# --- invariantes: valem qualquer que seja a escolha do modelo --------------------


def test_a_write_is_only_ever_proposed(deps):
    """Invariante, não roteamento: se o modelo escolheu uma escrita, ela NÃO pode ter gravado. Se
    ele escolher outra coisa, o teste diz isso e não finge que verificou."""
    product = _guinea_pig(deps)
    before = _snapshot(deps)

    reply = _ask(deps, f'renomeia o produto {product.id} para "Teste Julius"')
    _SPENT.append(_last_call(deps)["cost_usd"])
    print(f"\n  pedido de escrita → {_kind(reply.pending) if reply.pending else 'texto (nenhuma ação)'}")

    assert _snapshot(deps) == before, "ALGO FOI GRAVADO SEM O TOQUE — é a linha vermelha do desenho"
    if reply.pending is None:
        pytest.skip(f"o modelo não escolheu uma escrita desta vez (respondeu: {reply.text[:80]!r})")
    assert reply.pending.action == "rename_product"
    assert str(product.id) in reply.pending.preview
    assert product.canonical_name in reply.pending.preview, "o preview tem de citar o nome vindo do banco"


def test_the_tap_executes_and_the_undo_is_pastable(deps):
    """Fecha o laço na cópia: propõe pela IA, executa pelo toque, confere no banco e desfaz."""
    product = _guinea_pig(deps)

    state = ChatState()
    reply = _ask(deps, f'renomeia o produto {product.id} para "Teste Julius"', state)
    _SPENT.append(_last_call(deps)["cost_usd"])
    if reply.pending is None:
        pytest.skip(f"o modelo não propôs a escrita (respondeu: {reply.text[:80]!r})")

    result = handle_tap(state, deps, reply.pending.nonce, approve=True)

    print(f"\n  {result.text}")
    assert catalog.get_product(deps.conn, product.id).canonical_name == "Teste Julius"
    assert result.text.startswith("✅")
    assert f"julius produtos renomear {product.id}" in result.text
    assert state.pending is None

    catalog.rename_product(deps.conn, product.id, product.canonical_name)
    assert catalog.get_product(deps.conn, product.id).canonical_name == product.canonical_name


def test_no_turn_ever_raises(deps):
    """Entradas que o prompt não previu. O contrato é que `handle_text` sempre devolve um `Reply` —
    nunca propaga, nunca devolve vazio."""
    for message in ("", "?????", "DROP TABLE prices;", "a" * 500):
        reply = _ask(deps, message or "…")
        _SPENT.append(_last_call(deps)["cost_usd"])
        assert reply.text, f"resposta vazia para {message[:30]!r}"
    print(f"\n  {4} entradas estranhas, nenhuma exceção")


def test_the_model_never_invents_a_product_id(deps):
    """Pedir por um id que não existe tem de virar pergunta ao usuário, não uma escrita em cima de
    outro produto. É o caso que o `ModelRetry` de `resolve_product` existe para cobrir."""
    before = _snapshot(deps)

    reply = _ask(deps, 'renomeia o produto 99999 para "Nao Existe"')
    _SPENT.append(_last_call(deps)["cost_usd"])
    print(f"\n  resposta: {reply.text[:140]!r}")

    assert _snapshot(deps) == before
    assert reply.pending is None, "propôs uma escrita para um id inexistente"


# --- persona v4: agrupamento com muitos produtos (design bot-message-chunking.md, v2.8) --------


def test_narration_of_many_dissimilar_products_stays_short(deps):
    """Achado real desta rodada de design: o prompt v3, sem instrução de agrupamento, tentava
    narrar TODOS os produtos de uma busca ampla e truncava (`finish_reason: length`, max_tokens
    500, 25 registros de hortifruti reais). Isto testa a compressão do prompt `persona` isolada do
    roteamento -- não é o agente que está sob teste, é se a narração continua curta quando os fatos
    trazem muitos produtos sem resultado em comum."""
    outcome = search_service.search_free_text(deps.conn, [], tag="hortifruti", limit=20)
    if len(outcome.records) < 10:
        pytest.skip("catálogo real não tem hortifruti suficiente pra este teste")
    facts = render.records_facts(outcome.records)

    client = HttpLlmClient.from_config(deps.config)
    reply = suggestions.narrate(deps.conn, deps.config, client, "histórico de preço de um produto", facts)
    _SPENT.append(_last_call(deps)["cost_usd"])

    print(f"\n  {len(outcome.records)} registros -> {reply!r}")
    assert reply, "a persona não deveria falhar/truncar com muitos produtos -- era o bug original"
    blocks = reply.split("\n\n")
    assert len(blocks) <= 4, f"resposta com produtos demais deveria caber em poucos blocos: {blocks}"
    assert all(len(block) <= 400 for block in blocks), f"um bloco virou textão de novo: {blocks}"


# --- lista de compras: escopo + veredito (ticket 180, docs/design/shopping-list-conversation-context.md) --


def test_shopping_list_verdict_is_grounded(deps):
    """A narração do veredito nunca pode citar um R$ que não veio dos fatos -- a mesma guarda de
    `narrate()` (ticket 163), aqui exercitada sobre `shopping_comparison_facts` de verdade em vez
    de `comparison_facts`. Se o catálogo real não tiver dois kinds comparáveis, o teste pula: não
    há como testar grounding sem fato nenhum para citar."""
    from julius.services import comparison as comparison_service

    kinds = search_service.match_kind(deps.conn, "tomate"), search_service.match_kind(deps.conn, "cebola")
    kinds = [k for k in kinds if k]
    if not kinds:
        pytest.skip("catálogo real não tem tomate/cebola com tipo definido")
    scoped = comparison_service.compare_stores(deps.conn, kinds=kinds)
    if not scoped.comparisons:
        pytest.skip("tomate/cebola não são comparáveis entre mercados no catálogo real agora")
    verdict = comparison_service.shopping_verdict(scoped)
    from julius.bot.actions import ShoppingComparison as _ShoppingComparison

    shopping = _ShoppingComparison(comparison=scoped, verdict=verdict, unmatched_terms=())
    facts = render.shopping_comparison_facts(shopping)

    client = HttpLlmClient.from_config(deps.config)
    reply = suggestions.narrate(deps.conn, deps.config, client, "veredito de lista de compras", facts)
    _SPENT.append(_last_call(deps)["cost_usd"])

    print(f"\n  fatos:\n{facts}\n  -> {reply!r}")
    assert reply, "a persona não deveria falhar/ser rejeitada pela guarda para um veredito de 2 itens"


def test_the_run_reports_what_it_cost():
    """Não é assert de nada: é o número que você acompanha entre rodadas.

    Reporta o custo *desta seleção*, não o da rodada inteira — com `-k`, só o que rodou."""
    if not _SPENT:
        pytest.skip("nenhuma chamada foi feita")
    print(f"\n  {len(_SPENT)} chamadas · US$ {sum(_SPENT):.6f} nesta rodada")
