"""Fakes for julius.infra.llm_client.LlmClient, shared by every services test that needs one."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from julius.infra.decision_client import ChoiceResult, NoulResult
from julius.infra.llm_client import LlmResponse

# Each JSON response format (design doc §6) has one distinctive key: look for it quoted in the
# system prompt to tell which prompt a call belongs to.
_KIND_MARKERS = {
    '"products"': "enrich",
    '"pairs"': "merge",
    '"ids"': "match",
    '"packaging"': "packaging",
    '"stores"': "store",
    '"reply"': "persona",
    '"tag"': "category",
}


def _kind_of(system_prompt: str) -> str:
    for marker, kind in _KIND_MARKERS.items():
        if marker in system_prompt:
            return kind
    return ""


class ScriptedLlmClient:
    """Returns scripted LlmResponses in order, repeating the last one when the script runs out.

    With `by_kind`, the script is chosen per call kind (enrich/merge/match), detected from the
    system prompt; each value can be a single LlmResponse (reused for every call of that kind)
    or a sequence (one per call, also repeating the last).
    """

    def __init__(
        self,
        responses: Sequence[LlmResponse] = (),
        *,
        by_kind: Mapping[str, LlmResponse | Sequence[LlmResponse]] | None = None,
    ) -> None:
        self._responses = list(responses)
        self._by_kind = {kind: script if isinstance(script, Sequence) else [script] for kind, script in (by_kind or {}).items()}
        self._kind_calls: dict[str, int] = {}
        self.calls: list[tuple[str, str, int]] = []

    def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> LlmResponse:
        self.calls.append((system_prompt, user_prompt, max_tokens))
        if self._by_kind:
            kind = _kind_of(system_prompt)
            script = self._by_kind.get(kind)
            if not script:
                return LlmResponse("", 0, 0, error=f"no script for call kind {kind!r}")
            index = self._kind_calls.get(kind, 0)
            self._kind_calls[kind] = index + 1
            return script[min(index, len(script) - 1)]
        if not self._responses:
            return LlmResponse("", 0, 0, error="no scripted response")
        index = len(self.calls) - 1
        return self._responses[min(index, len(self._responses) - 1)]


class RaisingLlmClient:
    def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> LlmResponse:
        raise RuntimeError("boom")


class ScriptedDecisionClient:
    """Fake for julius.infra.decision_client.DecisionClient: scripted results in order, repeating
    the last one when the script runs out. Records every call for assertions."""

    def __init__(
        self,
        noul_responses: Sequence[NoulResult] = (),
        choice_responses: Sequence[ChoiceResult] = (),
    ) -> None:
        self._noul_responses = list(noul_responses)
        self._choice_responses = list(choice_responses)
        self.noul_calls: list[tuple[str, str]] = []
        self.choice_calls: list[tuple[str, str, dict]] = []

    def ask_noul(self, state: str, instructions: str) -> NoulResult:
        self.noul_calls.append((state, instructions))
        if not self._noul_responses:
            return NoulResult(None, error="no scripted response")
        index = len(self.noul_calls) - 1
        return self._noul_responses[min(index, len(self._noul_responses) - 1)]

    def ask_choice(self, state: str, instructions: str, criteria: Mapping[str, str]) -> ChoiceResult:
        self.choice_calls.append((state, instructions, dict(criteria)))
        if not self._choice_responses:
            return ChoiceResult(None, None, None, error="no scripted response")
        index = len(self.choice_calls) - 1
        return self._choice_responses[min(index, len(self._choice_responses) - 1)]


class RaisingDecisionClient:
    def ask_noul(self, state: str, instructions: str) -> NoulResult:
        raise RuntimeError("boom")

    def ask_choice(self, state: str, instructions: str, criteria: Mapping[str, str]) -> ChoiceResult:
        raise RuntimeError("boom")
