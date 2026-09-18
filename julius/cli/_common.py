from __future__ import annotations

import sqlite3
from datetime import date
from typing import NoReturn

import typer
from rich.console import Console
from rich.text import Text

from julius import config

# Reexport: money and content_text are unused here but imported from the rest of the CLI
# through this module, which is where they lived until the bot needed them too.
from julius.domain.formatting import br_date, content_text, money, relative_age
from julius.infra import db

console = Console()
error_console = Console(stderr=True)

HIGHLIGHT_STYLE = {"lowest": "green", "highest": "red"}


def date_cell(purchased_at: str, *, today: date | None = None) -> Text:
    """Absolute date over its age, stacked in one cell: no table grows a column for it."""
    age = relative_age(purchased_at, today=today)
    absolute = br_date(purchased_at)
    return Text(absolute) if not age else Text.assemble(absolute, "\n", (age, "dim"))


def open_db() -> sqlite3.Connection:
    return db.connect(config.load().db_path)


def fail(message: str) -> NoReturn:
    error_console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=1)
