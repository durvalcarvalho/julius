from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Sequence
from datetime import datetime

from julius.config import Config
from julius.domain.models import MergeSuggestion
from julius.infra import ai_log
from julius.infra.llm_client import LlmClient, LlmResponse
from julius.repositories import ai_usage

MAX_ATTEMPTS = 2  # one retry on transport error, empty response, or invalid JSON

PROMPT_VERSIONS: dict[str, str] = {"merge": "2"}

SYSTEM_PROMPTS: dict[str, str] = {
    "merge": (
        "Você compara pares de descrições de produtos de supermercado brasileiro (maiúsculas, sem acento, "
        "abreviadas) e decide se cada par é o MESMO produto para fins de comparar preço. Sabor, tamanho e tipo "
        "diferentes tornam produtos diferentes mesmo com nome-base igual. Marca/fornecedor diferente em "
        "hortifruti (tomate, cebola) não torna diferente. Responda somente com json neste formato, mesmos ids, "
        'escrevendo o "rationale" ANTES da decisão:\n'
        '{"pairs": [{"id": 1, "rationale": "até 20 palavras", "same_product": true, "confidence": 0.7}]}\n'
        "\n"
        "Exemplo de entrada:\n"
        "1 | A: TOMATE ITALIANO kg | B: TOMATE ITALIANO UNIAO kg\n"
        "2 | A: REFRI PEPSI PET 2L | B: REFRI ANT GUARANA PET 1.5L\n"
        "3 | A: AVEIA QUAK 450G FINO | B: AVEIA QUAK 450G REGU\n"
        "Exemplo de saída:\n"
        '{"pairs": [\n'
        ' {"id": 1, "rationale": "mesma variedade; UNIAO é só o fornecedor", "same_product": true, "confidence": 0.7},\n'
        ' {"id": 2, "rationale": "sabor e tamanho diferentes", "same_product": false, "confidence": 0.95},\n'
        ' {"id": 3, "rationale": "mesma marca e peso, mas flocos finos e regulares são produtos distintos", '
        '"same_product": false, "confidence": 0.85}\n'
        "]}"
    ),
}


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _configured_with_prices(config: Config) -> bool:
    return (
        config.ai_configured
        and config.ai_input_price_usd_per_1m is not None
        and config.ai_output_price_usd_per_1m is not None
    )


def is_available(conn: sqlite3.Connection, config: Config, month: str | None = None) -> bool:
    try:
        if not _configured_with_prices(config):
            return False
        return ai_usage.spent_in_month(conn, month or _current_month()) < config.ai_budget_usd
    except Exception:
        return False


def spent_this_month(conn: sqlite3.Connection, month: str | None = None) -> float:
    return ai_usage.spent_in_month(conn, month or _current_month())


def _log(
    config: Config,
    call_kind: str,
    *,
    attempt: int,
    user_prompt: str,
    raw_response: str | None,
    parsed_ok: bool,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    latency_ms: int,
    error: str | None,
) -> None:
    ai_log.append(
        config.ai_log_path,
        {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "call_kind": call_kind,
            "prompt_version": PROMPT_VERSIONS.get(call_kind, ""),
            "model": config.ai_model,
            "attempt": attempt,
            "user_prompt": user_prompt,
            "raw_response": raw_response,
            "parsed_ok": parsed_ok,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "error": error,
        },
    )


def _ask(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    call_kind: str,
    user_prompt: str,
    *,
    max_tokens: int,
    month: str | None = None,
) -> object | None:
    """Checks budget, tries up to MAX_ATTEMPTS times, charges and logs every attempt, returns parsed JSON or None."""
    month = month or _current_month()
    if not _configured_with_prices(config):
        return None
    if ai_usage.spent_in_month(conn, month) >= config.ai_budget_usd:
        _log(
            config,
            call_kind,
            attempt=0,
            user_prompt=user_prompt,
            raw_response=None,
            parsed_ok=False,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
            error="budget_exhausted",
        )
        return None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            response = client.complete(SYSTEM_PROMPTS[call_kind], user_prompt, max_tokens=max_tokens)
        except Exception as exc:
            response = LlmResponse("", 0, 0, error=f"client raised {type(exc).__name__}")
        latency_ms = int((time.monotonic() - started) * 1000)
        cost = (
            response.input_tokens / 1e6 * config.ai_input_price_usd_per_1m  # type: ignore[operator]
            + response.output_tokens / 1e6 * config.ai_output_price_usd_per_1m  # type: ignore[operator]
        )
        if cost > 0:
            with conn:
                ai_usage.add_spent(conn, month, cost)
        parsed: object | None = None
        parsed_ok = False
        error = response.error
        if error is None:
            try:
                parsed = json.loads(response.text)
                parsed_ok = True
            except ValueError:
                error = "invalid json"
        _log(
            config,
            call_kind,
            attempt=attempt,
            user_prompt=user_prompt,
            raw_response=response.text,
            parsed_ok=parsed_ok,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            error=error,
        )
        if error is None:
            return parsed
    return None


def _valid_merge_item(item: object, seen: int) -> MergeSuggestion | None:
    if not isinstance(item, dict):
        return None
    same_product = item.get("same_product")
    confidence = item.get("confidence")
    rationale = item.get("rationale")
    if not isinstance(same_product, bool):
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if not (0 <= confidence <= 1):
        return None
    if not isinstance(rationale, str):
        return None
    return MergeSuggestion(same_product=same_product, confidence=float(confidence), rationale=rationale)


def suggest_merges(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    pairs: Sequence[tuple[str, str]],
    month: str | None = None,
) -> list[MergeSuggestion | None]:
    if not pairs:
        return []
    try:
        user_prompt = "\n".join(f"{i} | A: {a} | B: {b}" for i, (a, b) in enumerate(pairs, start=1))
        max_tokens = 80 * len(pairs) + 100
        data = _ask(conn, config, client, "merge", user_prompt, max_tokens=max_tokens, month=month)
        items = data.get("pairs") if isinstance(data, dict) else None
        result: list[MergeSuggestion | None] = [None] * len(pairs)
        if not isinstance(items, list):
            return result
        for item in items:
            index = item.get("id") if isinstance(item, dict) else None
            if not isinstance(index, int) or isinstance(index, bool) or not (1 <= index <= len(pairs)):
                continue
            if result[index - 1] is not None:
                continue  # first item for a given id wins
            result[index - 1] = _valid_merge_item(item, index)
        return result
    except Exception:
        return [None] * len(pairs)
