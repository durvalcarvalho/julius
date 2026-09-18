"""Telegram interface over the same services as the CLI: a second composition root, not a layer the CLI knows about."""

from julius.bot.app import main

__all__ = ["main"]
