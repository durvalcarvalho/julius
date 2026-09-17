from __future__ import annotations

import sqlite3
from datetime import date
from typing import NoReturn

import typer
from rich.console import Console
from rich.text import Text

from julius import config
from julius.infra import db

console = Console()
error_console = Console(stderr=True)

HIGHLIGHT_STYLE = {"lowest": "green", "highest": "red"}


def money(value: float) -> str:
    return f"R$ {value:.2f}".replace(".", ",")


def br_date(purchased_at: str) -> str:
    if len(purchased_at) < 10:
        return ""
    return f"{purchased_at[8:10]}/{purchased_at[5:7]}/{purchased_at[:4]}"


def relative_age(purchased_at: str, *, today: date | None = None) -> str:
    """How long ago a date was, in the bands the user asked for. `today` is injected so that band
    tests do not depend on the day they run on."""
    try:
        days = ((today or date.today()) - date.fromisoformat(purchased_at[:10])).days
    except ValueError:
        return ""
    if days <= 0:
        # <= 0, not == 0: a date ahead of the clock reads as "hoje", never as "há -1 dias".
        return "hoje"
    if days == 1:
        return "ontem"
    if days <= 15:
        return f"há {days} dias"
    if days <= 29:
        return f"há {days // 7} semanas"
    # ponytail: a month is 30 days and a year is 12 of those, so the year starts on day 360. The
    # band is the information here, and deriving years from months is what keeps every band
    # rounding down -- with days // 365, day 364 would read "há 12 meses" next to "há 1 ano".
    months = days // 30
    if months < 12:
        return f"há {months} {'mês' if months == 1 else 'meses'}"
    years, rest = months // 12, months % 12
    label = f"há {years} {'ano' if years == 1 else 'anos'}"
    return label if rest == 0 else f"{label} e {rest} {'mês' if rest == 1 else 'meses'}"


def date_cell(purchased_at: str, *, today: date | None = None) -> Text:
    """Absolute date over its age, stacked in one cell: no table grows a column for it."""
    age = relative_age(purchased_at, today=today)
    absolute = br_date(purchased_at)
    return Text(absolute) if not age else Text.assemble(absolute, "\n", (age, "dim"))


def content_text(quantity: float, unit: str) -> str:
    return f"{quantity:g}".replace(".", ",") + f" {unit}"


def open_db() -> sqlite3.Connection:
    return db.connect(config.load().db_path)


def fail(message: str) -> NoReturn:
    error_console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=1)
