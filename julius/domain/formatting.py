"""Text the user reads, derived from values alone. It lives here because the CLI and the bot both
need it and neither may import the other -- same reason comparison_basis is in domain."""

from __future__ import annotations

from datetime import date

from julius.domain.models import StoreComparison


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


def content_text(quantity: float, unit: str) -> str:
    return f"{quantity:g}".replace(".", ",") + f" {unit}"


def plural_groups(count: int) -> str:
    return "grupo" if count == 1 else "grupos"


def coverage_text(comparison: StoreComparison) -> str:
    """Why the output is this small. Comparing needs the same kind in two stores, and measured on
    the real database 80 of 87 kinds were bought in a single one -- the tables can only ever show
    the rest. Without this the smallness reads as a missing feature."""
    total, single = comparison.kinds_total, comparison.kinds_single_store
    if single < total:
        return f"{single} dos {total} tipos comprados em um mercado só"
    if total == 1:
        return "o único tipo comprado saiu de um mercado só"
    return f"todos os {total} tipos comprados saíram de um mercado só"


def store_labels(comparison: StoreComparison) -> dict[str, str]:
    """A name per CNPJ. Two branches of one chain carry the same nickname until the user renames
    them, and two identical rows in a table is the one thing worse than dropping the group -- so a
    shared nickname gets its CNPJ appended. `julius mercados listar` shows which address is which."""
    by_nickname: dict[str, set[str]] = {}
    for group in comparison.comparisons:
        for entry in group.entries:
            by_nickname.setdefault(entry.store_nickname, set()).add(entry.store_cnpj)
    return {
        entry.store_cnpj: (
            f"{entry.store_nickname} · {entry.store_cnpj}"
            if len(by_nickname[entry.store_nickname]) > 1
            else entry.store_nickname
        )
        for group in comparison.comparisons
        for entry in group.entries
    }
