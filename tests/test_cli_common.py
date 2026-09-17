from datetime import date, timedelta

import pytest

from julius.cli._common import br_date, date_cell, relative_age

TODAY = date(2026, 9, 17)


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def test_br_date_reorders_and_keeps_the_year():
    assert br_date("2026-09-16T10:00:00") == "16/09/2026"
    assert br_date("2026-09-16") == "16/09/2026"


@pytest.mark.parametrize("raw", ["", "2026-09", "lixo"])
def test_br_date_of_junk_is_empty_not_slashes(raw):
    """actions.jsonl may hold a partial record -- ai_log.tail tolerates that by contract."""
    assert br_date(raw) == ""


@pytest.mark.parametrize(
    ("days_ago", "expected"),
    [
        (0, "hoje"),
        (1, "ontem"),
        (2, "há 2 dias"),
        (15, "há 15 dias"),
        (16, "há 2 semanas"),
        (21, "há 3 semanas"),
        (29, "há 4 semanas"),
        (30, "há 1 mês"),
        (59, "há 1 mês"),
        (60, "há 2 meses"),
        (330, "há 11 meses"),
        (359, "há 11 meses"),
        (360, "há 1 ano"),
        (395, "há 1 ano e 1 mês"),
        (456, "há 1 ano e 3 meses"),
        (720, "há 2 anos"),
        (760, "há 2 anos e 1 mês"),
    ],
)
def test_relative_age_bands(days_ago, expected):
    """Every band above "dias" is synthetic on purpose: the real database has only six dates, all
    within 13 days, so nothing above the first band would ever be exercised by real data."""
    assert relative_age(_iso(days_ago), today=TODAY) == expected


def test_months_never_reach_twelve():
    """Deriving years from months is what keeps the rounding down honest: with days // 365, day 364
    would read "há 12 meses" with "há 1 ano" one day away."""
    assert "12 meses" not in {relative_age(_iso(days), today=TODAY) for days in range(330, 400)}


def test_relative_age_of_a_date_ahead_of_the_clock_is_today():
    assert relative_age(_iso(-3), today=TODAY) == "hoje"


@pytest.mark.parametrize("raw", ["", "2026-13-40", "lixo"])
def test_relative_age_of_junk_is_empty(raw):
    assert relative_age(raw, today=TODAY) == ""


def test_date_cell_stacks_the_age_under_the_date():
    cell = date_cell("2026-09-04", today=TODAY)

    assert cell.plain == "04/09/2026\nhá 13 dias"
    assert any(span.style == "dim" for span in cell.spans)


def test_date_cell_without_a_usable_date_is_the_date_alone():
    assert date_cell("lixo", today=TODAY).plain == ""
