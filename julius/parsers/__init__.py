from __future__ import annotations

from typing import Protocol

from julius.domain.models import Receipt


class ReceiptParseError(ValueError):
    """The HTML does not look like a receipt this parser understands (missing field, no items, count mismatch)."""


class ReceiptParser(Protocol):
    """One implementation per state's NFC-e HTML layout. Only DF exists today."""

    def parse(self, html: str, source: str = "") -> Receipt: ...
