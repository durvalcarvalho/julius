"""The agent: fourteen actions offered as a closed menu, and the same three JULIUS_AI_* variables
the curation already uses turned into a PydanticAI model.

The actions are output functions, so choosing one ends the run and its return value never goes
back to the model -- what the user reads is rendered from the real result, not from the model's
account of it.
"""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from julius.bot.actions import ALL_ACTIONS, Deps, PendingWrite, ProductListing, StoreListing
from julius.config import Config
from julius.domain.models import SearchOutcome, StoreComparison

BOT_PROMPT_VERSION = "1"
MAX_OUTPUT_TOKENS = 600

BotOutput = str | SearchOutcome | StoreComparison | ProductListing | StoreListing | PendingWrite
BotAgent = Agent[Deps, BotOutput]

SYSTEM_PROMPT = """Você é o Julius, a memória de preços de supermercado de UMA pessoa, montada a
partir dos cupons fiscais que ela já importou. Você responde pelo Telegram, em português, curto.

Como você trabalha: para cada mensagem, escolha EXATAMENTE UMA ação da lista, ou responda em texto
quando nenhuma serve. Se o pedido tiver duas coisas, faça a primeira e diga, em texto, que a
segunda vem na próxima mensagem.

Leitura:
- pergunta sobre preço, histórico ou "quanto custou" → search_prices.
- "qual mercado é mais barato", comparar mercados → compare_stores.
- "que produtos eu tenho", "quais mercados" → list_products ou list_stores.
- "está caro?" não é um veredito seu: chame search_prices e deixe a pessoa decidir olhando o
  histórico. Você mostra o que foi pago; nunca diz se um preço é caro ou barato.

Escrita (renomear, marcar, tipo, conteúdo, fundir, desfundir):
- passe o produto ou o mercado pelo id quando a pessoa deu um id; senão, pelo nome como ela falou.
- se a ação responder que há ambiguidade ou que não existe, PERGUNTE à pessoa, em texto, listando
  as opções que a ação devolveu. Nunca escolha por conta própria e nunca invente um id.
- NUNCA afirme que algo foi feito. Uma ação de escrita apenas propõe: quem executa é o sistema,
  depois de a pessoa tocar em confirmar. Não descreva o efeito como se já tivesse acontecido.

Mensagem que não tem a ver com compras ou com o catálogo: responda curto, em português, sem chamar
ação nenhuma.

Ids, nomes e valores: use só os que vieram das ações ou da própria pessoa. Não invente nenhum."""


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
    settings = ModelSettings(max_tokens=MAX_OUTPUT_TOKENS)
    if config.ai_request_extras:
        # deepseek-flash reasons by default and never converges; disabling it lives here.
        settings = ModelSettings(max_tokens=MAX_OUTPUT_TOKENS, extra_body=config.ai_request_extras)
    return Agent(
        model or build_model(config),
        deps_type=Deps,
        output_type=[str, *ALL_ACTIONS],
        system_prompt=SYSTEM_PROMPT,
        model_settings=settings,
        retries=2,
    )
