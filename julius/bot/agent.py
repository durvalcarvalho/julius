"""The agent: fifteen actions offered as a closed menu, and the same three JULIUS_AI_* variables
the curation already uses turned into a PydanticAI model.

The actions are output functions, so choosing one ends the run and its return value never goes
back to the model -- what the user reads is rendered from the real result, not from the model's
account of it.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from julius.bot.actions import ALL_ACTIONS, Deps, PendingWrite, ProductListing, ShoppingComparison, StoreListing
from julius.bot.render import WRITE_REFUSED_LINE
from julius.config import Config
from julius.domain.models import PriceCheck, SearchOutcome, StoreComparison
from julius.services import search as search_service

log = logging.getLogger("julius.bot")

BOT_PROMPT_VERSION = "6"
MAX_OUTPUT_TOKENS = 600

ROUTING_TEMPERATURE = 0.0
"""Escolher 1 de 15 ações é "analytical / multiple choice" -- a própria documentação do
`ModelSettings.temperature` do pydantic_ai recomenda 0.0 para esse tipo de tarefa, sem ressalva a
favor de uma margem acima disso. Sem `temperature` nenhuma (o estado antes desta constante), o
provedor usa o próprio default, tipicamente 1.0 -- a causa mais provável de duas respostas
diferentes para a mesma pergunta, mesma conversa, medida em produção em 2026-09-19 (ver
docs/design/agent-output-honesty.md). A mesma documentação avisa que "mesmo com temperature 0.0
os resultados não são totalmente determinísticos" -- é por isso que `_claims_unchecked_data`
abaixo continua obrigatória, não uma rede de segurança descartável."""

_UNLICENSED_DATA_CLAIMS = (
    "buscas voltaram vazias",
    "busca voltou vazia",
    "não consegui ver os resultados",
    "sem nenhum dado de preço",
    "histórico de cupons",
    "não foi importado",
    "importação falhou",
    "não está cadastrado no banco",
    "banco de dados",
)
"""Frases que só fazem sentido se uma ação de leitura realmente rodou e voltou vazia -- nunca um
palpite legítimo de texto livre (pergunta de esclarecimento, recusa de assunto fora do catálogo).
Por frase inteira, não por palavra solta: tirada literalmente do único caso real observado (o
bot afirmou "as buscas voltaram vazias... histórico de cupons ainda não foi importado" sem ter
chamado search_prices nem compare_stores -- banco intacto, 133 produtos, a mesma pergunta tinha
funcionado 68 minutos antes). Lista nasce de UM caso, cresce com o próximo -- ver
docs/design/agent-output-honesty.md, Decisão 1."""


def _claims_unchecked_data(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _UNLICENSED_DATA_CLAIMS)

BotOutput = (
    str | SearchOutcome | StoreComparison | ShoppingComparison | ProductListing | StoreListing | PendingWrite | PriceCheck
)
BotAgent = Agent[Deps, BotOutput]

SYSTEM_PROMPT = """Você é o Julius, a memória de preços de supermercado de UMA pessoa, montada a
partir dos cupons fiscais que ela já importou. Você responde pelo Telegram, em português, curto.

Como você trabalha: para cada mensagem, escolha EXATAMENTE UMA ação da lista, ou responda em texto
quando nenhuma serve. Se o pedido tiver duas coisas, faça a primeira e use o parâmetro `note` da
própria ação (todas as ações de leitura têm um) pra dizer, em texto curto, que a segunda vem na
próxima mensagem -- NUNCA tente escrever isso como texto solto além da chamada da ação, porque as
duas coisas não cabem juntas na mesma resposta.

Leitura:
- pergunta sobre preço, histórico ou "quanto custou" → search_prices.
- "qual mercado é mais barato", comparar mercados → compare_stores, mas só com uma lista de itens
  concreta. Se a pessoa não disse o que quer comprar — nem nesta mensagem, nem nas últimas da
  conversa — NÃO chame compare_stores: responda em texto perguntando o que ela quer comprar. Ao
  montar a lista de itens, junte o que foi mencionado nas últimas mensagens da conversa, não só
  na mais recente.
- "que produtos eu tenho", "quais mercados" → list_products ou list_stores.
- "está caro?" sem nenhum preço dito não é um veredito seu: chame search_prices e deixe a pessoa
  decidir olhando o histórico. Você mostra o que foi pago; nunca diz se um preço é caro ou barato.
  Se nem a mensagem atual nem as últimas mensagens da conversa citarem QUAL item, não chame
  search_prices com um termo vazio: pergunte em texto qual item, antes de qualquer ação.
- Exceção: a pessoa está no mercado agora e diz o preço que ela mesma está vendo ("os ovos tão a
  14 reais, tá bom?", "aqui o tomate tá 9,90 o quilo") → check_price, com esse valor. Só nesse
  caso — preço visto ao vivo, não uma nota importada — você compara e responde sim ou não. NUNCA
  informe quantity nessa primeira chamada, nem para assumir "1" — deixe o parâmetro de fora; é
  check_price quem decide se precisa perguntar (reason="quantity_needed").
- Se check_price responder pedindo quantidade (reason="quantity_needed"), pergunte quanto a
  pessoa vai comprar, na mesma unidade que a resposta já deu. Quando ela responder, chame
  check_price de novo com o mesmo item e preço mais essa quantidade. Se a resposta não ajudar
  depois de perguntar uma segunda vez, chame de novo com uma quantidade pequena (ex.: 1) em vez de
  insistir — a conversa nunca fica travada numa pergunta sem resposta.
- Se check_price responder reason="ambiguous_unit", pergunte se o preço é por peso (quilo) ou por
  unidade. Quando ela responder, chame check_price de novo com o mesmo item/price mais
  unit="KG" ou unit="UN".
- Se a sua última mensagem nesta conversa foi uma pergunta, trate a próxima mensagem da pessoa
  como resposta a ela antes de cogitar qualquer outra ação — mesmo que a resposta seja curta.
- Se check_price/compare_stores recusar por ambiguidade de tipo, PERGUNTE à pessoa qual das opções
  listadas, do mesmo jeito que já faz para produto/mercado ambíguo — nunca escolha sozinho.
- Se a sua última mensagem nesta conversa foi um COMENTÁRIO seu (não uma pergunta de dado) —
  brincadeira, pergunta retórica, opinião — e a mensagem nova reage a esse comentário sem citar
  nenhum produto de mercado nem preço, responda em texto reconhecendo a piada/comentário. NÃO
  chame search_prices tentando tratar palavras do seu próprio comentário anterior (ex.: "luz",
  "tempo") como se fossem um produto novo. Só chame uma ação se a pessoa citar um item de mercado
  de verdade, mesmo que fora do catálogo.
- Se o produto que a pessoa citou agora é muito parecido com o que ela citou na mensagem anterior
  — mesma marca/categoria, só com variação de tamanho/embalagem — pergunte em texto se é o mesmo
  item antes de tratar como pergunta nova, especialmente quando o PREÇO citado agora é igual (ou
  muito perto) do preço citado na mensagem anterior: preço repetido pra um "produto novo" é o
  sinal mais forte de que é a MESMA compra, descrita de duas formas (ex.: "coca por 12 reais",
  depois "refrigerante 2L por 12 reais" — mesmo preço, provavelmente a mesma garrafa). NUNCA trate
  dois nomes parecidos como o mesmo produto quando eles podem ser tipos diferentes (ex.: "guaraná"
  e "guaraná zero" continuam produtos distintos até a pessoa confirmar) — só pergunte, nunca
  decida sozinho.
- Você só vê as últimas mensagens desta conversa, não a conversa inteira. Se a pessoa perguntar
  sobre algo de antes do que você consegue ver (ex.: "o que eu perguntei primeiro", "lá no
  começo"), NUNCA afirme que a mensagem mais antiga que você vê foi a primeira coisa que ela
  disse — você não tem como saber isso. Diga que não lembra tão longe na conversa, em vez de
  arriscar um fato errado sobre o que ela perguntou.

Escrita (renomear, marcar, tipo, conteúdo, fundir, desfundir):
- passe o produto ou o mercado pelo id quando a pessoa deu um id; senão, pelo nome como ela falou.
- se a ação responder que há ambiguidade ou que não existe, PERGUNTE à pessoa, em texto, listando
  as opções que a ação devolveu. Nunca escolha por conta própria e nunca invente um id.
- NUNCA afirme que algo foi feito. Uma ação de escrita apenas propõe: quem executa é o sistema,
  depois de a pessoa tocar em confirmar. Não descreva o efeito como se já tivesse acontecido.

Mensagem que não tem a ver com compras ou com o catálogo: responda curto, em português, sem chamar
ação nenhuma.

Ids, nomes e valores: use só os que vieram das ações ou da própria pessoa. Não invente nenhum.

NUNCA, em texto livre, afirme que uma busca voltou vazia, que uma importação falhou ou que o
catálogo/banco não tem dado — isso só pode vir do resultado real de uma ação. Se a pergunta pede
preço, histórico, comparação ou catálogo, chame a ação; texto livre é só para o que não tem
relação nenhuma com isso."""


def build_model(config: Config) -> OpenAIChatModel:
    """The endpoint is whatever JULIUS_AI_BASE_URL points at. No vendor-specific provider class:
    the base URL is the whole provider abstraction this project wants, same as the curation's
    HTTP client."""
    if not config.ai_configured:
        raise ValueError(
            "IA não configurada: defina JULIUS_AI_API_KEY, JULIUS_AI_BASE_URL e JULIUS_AI_MODEL"
        )
    return OpenAIChatModel(
        config.ai_model,
        provider=OpenAIProvider(base_url=config.ai_base_url, api_key=config.ai_api_key),
    )


def build_agent(config: Config, model: Model | None = None) -> BotAgent:
    """`model` is injectable for tests only -- nothing in production passes it."""
    settings = ModelSettings(max_tokens=MAX_OUTPUT_TOKENS, temperature=ROUTING_TEMPERATURE)
    if config.ai_request_extras:
        # deepseek-flash reasons by default and never converges; disabling it lives here.
        settings = ModelSettings(
            max_tokens=MAX_OUTPUT_TOKENS, temperature=ROUTING_TEMPERATURE, extra_body=config.ai_request_extras
        )
    agent: BotAgent = Agent(
        model or build_model(config),
        deps_type=Deps,
        output_type=[str, *ALL_ACTIONS],
        system_prompt=SYSTEM_PROMPT,
        model_settings=settings,
        retries=2,
    )

    @agent.system_prompt(dynamic=True)
    async def kind_vocabulary(ctx: RunContext[Deps]) -> str:
        """`dynamic=True` is load-bearing, not the default: `bot/turn.py::handle_text` always
        reuses `message_history`, and with the default (`dynamic=False`) a system-prompt function
        only runs on a chat's first turn -- its text gets baked into that first `ModelRequest` and
        every later turn in the same chat replays it verbatim, never seeing a `kind` registered
        afterwards by `julius importar`/`produtos revisar` running in the other process. Verified
        with `FunctionModel` (docs/design/kind-resolution-in-routing.md, Decisão 1): without the
        flag, a counter inside this function advanced once across three `run()` calls sharing
        history; with it, three times, one per call.

        `async def`, not a plain `def`, for the same reason `narrate()` is called directly instead
        of through `asyncio.to_thread` (v2.7, see CLAUDE.md "O achado real do smoke automatizado"):
        `pydantic_ai._system_prompt.SystemPromptRunner` offloads a *sync* function to a worker
        thread via `anyio.to_thread`, and `sqlite3.Connection` refuses to be touched outside the
        thread that opened it (`check_same_thread`, on by default) -- confirmed by reproducing the
        exact `ProgrammingError` with a sync version of this function before marking it `async`.
        An async function is awaited in place, no thread involved, even though nothing here
        actually needs to await."""
        kinds = search_service.known_kinds(ctx.deps.conn)
        if not kinds:
            return ""
        return (
            "Tipos (kind) já cadastrados, para os argumentos de check_price/compare_stores: "
            + ", ".join(kinds)
            + ". Quando o pedido corresponder a um destes, use exatamente esta grafia; senão, use "
            "o texto da pessoa mesmo assim -- outra camada resolve marca e erro de digitação depois."
        )

    @agent.output_validator
    def no_unlicensed_data_claims(ctx: RunContext[Deps], data: BotOutput) -> BotOutput:
        """Texto livre nunca afirma o que só uma ação pode confirmar (docs/design/
        agent-output-honesty.md, Decisão 1). Uma saída só: chamar a ação certa -- nunca a de
        reformular sem as palavras banidas, que manteria a falha e só trocaria a mentira por uma
        não-resposta igualmente inútil.

        Só dispara quando NENHUMA ação foi chamada nesta rodada (`ctx.messages` sem
        `ToolCallPart`) -- achado de revisão: o próprio prompt manda relatar em texto uma recusa
        de `resolve_product`/`resolve_store` ("Nenhum produto chamado «X»", que pode incluir
        "banco de dados" na frase de verdade), e essa fala é legítima porque uma ação REALMENTE
        rodou e devolveu isso. Sem essa checagem, a guarda barraria uma resposta correta."""
        if any(isinstance(part, ToolCallPart) for message in ctx.messages for part in getattr(message, "parts", [])):
            return data
        if isinstance(data, str) and _claims_unchecked_data(data):
            raise ModelRetry(
                "Sua resposta afirmou algo sobre busca, importação ou catálogo sem ter chamado "
                "nenhuma ação -- isso não pode ser verdade se nenhuma ação rodou. Chame agora a "
                "ação certa (search_prices, compare_stores, list_products ou list_stores) pra "
                "essa pergunta e responda com o resultado de verdade."
            )
        return data

    @agent.output_validator
    def no_write_without_permission(ctx: RunContext[Deps], data: BotOutput) -> BotOutput:
        """docs/design/bot-read-only-tier.md: fecha RF2/RF3 do requisito -- quem não é confiável
        nunca vê o teclado de confirmar. A ação já rodou (só leu o banco pra montar o preview,
        nada foi gravado) e esta troca de tipo acontece antes de bot/turn.py decidir se mostra o
        botão. Sem chamada de modelo extra: a troca acontece sobre a resposta que já chegou."""
        if isinstance(data, PendingWrite) and not ctx.deps.can_write:
            log.info("chat_id=%s tentou escrever sem permissão: %s", ctx.deps.chat_id, data.action)
            return WRITE_REFUSED_LINE
        return data

    return agent
