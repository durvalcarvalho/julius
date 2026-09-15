from __future__ import annotations

import sqlite3
from typing import NoReturn

import typer
from rich.console import Console

from julius import config
from julius.infra import db

console = Console()
error_console = Console(stderr=True)


def open_db() -> sqlite3.Connection:
    return db.connect(config.load().db_path)


def fail(message: str) -> NoReturn:
    error_console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=1)
