"""Guarda da camada bot: a suíte nunca fala com um modelo de verdade."""

from pydantic_ai import models


def test_model_requests_are_blocked_in_the_suite():
    assert models.ALLOW_MODEL_REQUESTS is False
