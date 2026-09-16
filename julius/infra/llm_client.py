from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from julius.config import Config


@dataclass(frozen=True)
class LlmResponse:
    text: str
    input_tokens: int
    output_tokens: int
    error: str | None = None  # set => text is "" and tokens reflect what usage the provider reported (may be > 0)


class LlmClient(Protocol):
    """Chat completion. Never raises and never returns None; failures come back as `error`."""

    def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> LlmResponse: ...


def _tokens_from_usage(usage: object) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    try:
        return int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
    except (TypeError, ValueError):
        return 0, 0


def _parse_payload(payload: object) -> LlmResponse:
    if not isinstance(payload, dict):
        return LlmResponse("", 0, 0, error="invalid json body")
    choices = payload.get("choices")
    usage = payload.get("usage")
    if not choices:
        input_tokens, output_tokens = _tokens_from_usage(usage)
        return LlmResponse("", input_tokens, output_tokens, error="no choices")
    if not isinstance(usage, dict):
        return LlmResponse("", 0, 0, error="no usage")
    input_tokens, output_tokens = _tokens_from_usage(usage)
    choice = choices[0] if isinstance(choices[0], dict) else {}
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and finish_reason != "stop":
        return LlmResponse("", input_tokens, output_tokens, error=f"finish_reason {finish_reason}")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        return LlmResponse("", input_tokens, output_tokens, error="empty content")
    return LlmResponse(content, input_tokens, output_tokens)


class HttpLlmClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        request_extras: Mapping[str, object] | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._request_extras = dict(request_extras or {})

    @classmethod
    def from_config(cls, config: Config) -> HttpLlmClient | None:
        if not config.ai_configured:
            return None
        return cls(
            config.ai_base_url,  # type: ignore[arg-type]
            config.ai_api_key,  # type: ignore[arg-type]
            config.ai_model,  # type: ignore[arg-type]
            request_extras=config.ai_request_extras,
        )

    def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> LlmResponse:
        """Extras (JULIUS_AI_REQUEST_EXTRAS) are merged last and may override any body key."""
        body: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        body.update(self._request_extras)
        request = Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                status = response.status
                raw = response.read()
            if not 200 <= status < 300:
                return LlmResponse("", 0, 0, error=f"HTTP {status}")
            try:
                payload = json.loads(raw)
            except ValueError:
                return LlmResponse("", 0, 0, error="invalid json body")
            return _parse_payload(payload)
        except HTTPError as exc:
            return LlmResponse("", 0, 0, error=f"HTTP {exc.code}")
        except TimeoutError:
            return LlmResponse("", 0, 0, error="timeout")
        except URLError as exc:
            return LlmResponse("", 0, 0, error=f"network: {exc.reason}")
        except Exception as exc:  # never raise: a missing suggestion is fine, a crash mid-import is not
            return LlmResponse("", 0, 0, error=f"{type(exc).__name__}: {exc}"[:200])
