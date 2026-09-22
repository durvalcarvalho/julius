from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from julius.config import Config

_QUESTION_KEY = "q"


@dataclass(frozen=True)
class NoulResult:
    value: float | None  # 0.0-1.0; None when error is set
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


@dataclass(frozen=True)
class ChoiceResult:
    choice: str | None
    confidence: float | None
    probabilities: dict[str, float] | None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


class DecisionClient(Protocol):
    """Typed decisions (Choice/Noul) evaluated against a state — never text. Never raises and
    never returns None; failures come back as `error`, same idiom as LlmClient."""

    def ask_noul(self, state: str, instructions: str) -> NoulResult: ...

    def ask_choice(self, state: str, instructions: str, criteria: Mapping[str, str]) -> ChoiceResult: ...


def _tokens_from_usage(usage: object) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    try:
        return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    except (TypeError, ValueError):
        return 0, 0


def _answer(payload: object, key: str) -> dict | None:
    if not isinstance(payload, dict):
        return None
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return None
    answer = answers.get(key)
    return answer if isinstance(answer, dict) else None


def _post(url: str, api_key: str, body: dict[str, object], timeout: float) -> tuple[dict, str | None]:
    """Returns (payload, None) on success, ({}, error) otherwise. Never raises."""
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
        if not 200 <= status < 300:
            return {}, f"HTTP {status}"
        try:
            payload = json.loads(raw)
        except ValueError:
            return {}, "invalid json body"
        if not isinstance(payload, dict):
            return {}, "invalid json body"
        return payload, None
    except HTTPError as exc:
        return {}, f"HTTP {exc.code}"
    except TimeoutError:
        return {}, "timeout"
    except URLError as exc:
        return {}, f"network: {exc.reason}"
    except Exception as exc:  # never raise: a missing verdict is fine, a crash mid-review is not
        return {}, f"{type(exc).__name__}: {exc}"[:200]


class TypeSafeDecisionClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float = 30.0) -> None:
        self._url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds

    @classmethod
    def from_config(cls, config: Config) -> TypeSafeDecisionClient | None:
        if not config.typesafe_configured:
            return None
        return cls(config.typesafe_base_url, config.typesafe_api_key, config.typesafe_model)  # type: ignore[arg-type]

    def ask_noul(self, state: str, instructions: str) -> NoulResult:
        body = {
            "state": state,
            "model": self._model,
            "questions": {_QUESTION_KEY: {"type": "noul", "instructions": instructions}},
        }
        payload, error = _post(self._url, self._api_key, body, self._timeout)
        if error is not None:
            return NoulResult(None, error=error)
        input_tokens, output_tokens = _tokens_from_usage(payload.get("usage"))
        answer = _answer(payload, _QUESTION_KEY)
        value = answer.get("noul") if answer is not None else None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return NoulResult(None, input_tokens, output_tokens, error="invalid response shape")
        return NoulResult(float(value), input_tokens, output_tokens)

    def ask_choice(self, state: str, instructions: str, criteria: Mapping[str, str]) -> ChoiceResult:
        body = {
            "state": state,
            "model": self._model,
            "questions": {
                _QUESTION_KEY: {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}
            },
        }
        payload, error = _post(self._url, self._api_key, body, self._timeout)
        if error is not None:
            return ChoiceResult(None, None, None, error=error)
        input_tokens, output_tokens = _tokens_from_usage(payload.get("usage"))
        answer = _answer(payload, _QUESTION_KEY)
        choice = answer.get("choice") if answer is not None else None
        if not isinstance(choice, str):
            return ChoiceResult(None, None, None, input_tokens, output_tokens, error="invalid response shape")
        confidence = answer.get("confidence")
        probabilities = answer.get("probabilities")
        return ChoiceResult(
            choice=choice,
            confidence=float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None,
            probabilities=probabilities if isinstance(probabilities, dict) else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
