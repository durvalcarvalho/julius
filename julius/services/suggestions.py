from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime

from julius.config import Config
from julius.domain.models import ContentSuggestion, MergeSuggestion
from julius.infra.llm_client import LlmClient
from julius.repositories import ai_usage

_JSON_BLOCK = re.compile(r"[\[{].*[\]}]", re.DOTALL)
_CONTENT_UNITS = ("L", "KG", "UN")
_MAX_TAGS = 3

_SYSTEM_PROMPT = (
    "Você ajuda a organizar um catálogo pessoal de compras de supermercado brasileiro. "
    "As descrições vêm de cupons fiscais: maiúsculas, sem acento, abreviadas. "
    "Responda somente com JSON válido, sem texto antes ou depois."
)


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def is_available(conn: sqlite3.Connection, config: Config, month: str | None = None) -> bool:
    try:
        if not config.ai_configured:
            return False
        if config.ai_input_price_usd_per_1m is None or config.ai_output_price_usd_per_1m is None:
            return False
        return ai_usage.spent_in_month(conn, month or _current_month()) < config.ai_budget_usd
    except Exception:
        return False


def _ask(conn: sqlite3.Connection, config: Config, client: LlmClient, user_prompt: str, month: str | None):
    """Returns the parsed JSON payload, or None. Cost is recorded before parsing: we paid either way."""
    if not is_available(conn, config, month):
        return None
    response = client.complete(_SYSTEM_PROMPT, user_prompt)
    if response is None:
        return None
    cost = (
        response.input_tokens / 1e6 * config.ai_input_price_usd_per_1m  # type: ignore[operator]
        + response.output_tokens / 1e6 * config.ai_output_price_usd_per_1m  # type: ignore[operator]
    )
    with conn:
        ai_usage.add_spent(conn, month or _current_month(), cost)
    blocks = _JSON_BLOCK.findall(response.text)
    return json.loads(blocks[0]) if blocks else None


def suggest_merge(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    description_a: str,
    description_b: str,
    month: str | None = None,
) -> MergeSuggestion | None:
    prompt = (
        "Estas duas descrições de cupom fiscal referem-se ao MESMO produto (mesma marca, sabor e tamanho)? "
        f'A: "{description_a}"  B: "{description_b}". '
        'Responda {"same_product": true|false, "confidence": 0..1, "rationale": "uma frase"}.'
    )
    try:
        data = _ask(conn, config, client, prompt, month)
        return MergeSuggestion(
            same_product=bool(data["same_product"]),
            confidence=float(data["confidence"]),
            rationale=str(data["rationale"]),
        )
    except Exception:
        return None


def suggest_content(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    description: str,
    month: str | None = None,
) -> ContentSuggestion | None:
    prompt = (
        f'Qual o conteúdo total da embalagem descrita como "{description}"? '
        'Responda {"quantity": número, "unit": "L"|"KG"|"UN", "confidence": 0..1}. '
        "Converta gramas para KG e mililitros para L. Se não souber, confidence 0."
    )
    try:
        data = _ask(conn, config, client, prompt, month)
        quantity = float(data["quantity"])
        unit = str(data["unit"]).strip().upper()
        if quantity <= 0 or unit not in _CONTENT_UNITS:
            return None
        return ContentSuggestion(quantity=quantity, unit=unit, confidence=float(data["confidence"]))  # type: ignore[arg-type]
    except Exception:
        return None


def suggest_tags(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    description: str,
    existing_tags: list[str],
    month: str | None = None,
) -> list[str]:
    prompt = (
        f'Sugira até {_MAX_TAGS} categorias curtas (minúsculas, uma palavra) para o produto "{description}". '
        f"Prefira reutilizar estas já existentes quando fizer sentido: {existing_tags}. "
        'Responda apenas uma lista JSON de strings, ex.: ["hortifruti", "limpeza"].'
    )
    try:
        data = _ask(conn, config, client, prompt, month)
        if not isinstance(data, list):
            return []
        tags: list[str] = []
        for item in data:
            tag = str(item).strip().lower()
            if tag and tag not in tags:
                tags.append(tag)
        return tags[:_MAX_TAGS]
    except Exception:
        return []
