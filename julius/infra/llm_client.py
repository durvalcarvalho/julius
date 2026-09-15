from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.request import Request, urlopen

from julius.config import Config


@dataclass(frozen=True)
class LlmResponse:
    text: str
    input_tokens: int
    output_tokens: int


class LlmClient(Protocol):
    """Raw chat completion. Implementations must never raise: any failure returns None."""

    def complete(self, system_prompt: str, user_prompt: str) -> LlmResponse | None: ...


class HttpLlmClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float = 30.0) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds

    @classmethod
    def from_config(cls, config: Config) -> HttpLlmClient | None:
        if not config.ai_configured:
            return None
        return cls(config.ai_base_url, config.ai_api_key, config.ai_model)  # type: ignore[arg-type]

    def complete(self, system_prompt: str, user_prompt: str) -> LlmResponse | None:
        body = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0,
            }
        ).encode("utf-8")
        request = Request(
            self._url,
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                if not 200 <= response.status < 300:
                    return None
                payload = json.loads(response.read())
            text = payload["choices"][0]["message"]["content"]
            usage = payload["usage"]
            if not isinstance(text, str):
                return None
            return LlmResponse(text, int(usage["prompt_tokens"]), int(usage["completion_tokens"]))
        except Exception:
            # Never raise: a missing suggestion is always acceptable, a crash mid-import is not.
            return None
