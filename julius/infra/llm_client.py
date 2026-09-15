from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LlmResponse:
    text: str
    input_tokens: int
    output_tokens: int


class LlmClient(Protocol):
    """Raw chat completion. Implementations must never raise: any failure returns None."""

    def complete(self, system_prompt: str, user_prompt: str) -> LlmResponse | None: ...
