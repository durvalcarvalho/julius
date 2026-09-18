from datetime import date

from julius.cli import _common
from julius.domain import formatting

TODAY = date(2026, 9, 17)


def test_cli_common_reexports_the_formatters():
    """The rest of the CLI imports these from here; they only moved to domain so the bot could
    reach them too. A "clean up the unused import" would break four modules."""
    assert _common.money is formatting.money
    assert _common.br_date is formatting.br_date
    assert _common.relative_age is formatting.relative_age
    assert _common.content_text is formatting.content_text


def test_date_cell_stacks_the_age_under_the_date():
    cell = _common.date_cell("2026-09-04", today=TODAY)

    assert cell.plain == "04/09/2026\nhá 13 dias"
    assert any(span.style == "dim" for span in cell.spans)


def test_date_cell_without_a_usable_date_is_the_date_alone():
    assert _common.date_cell("lixo", today=TODAY).plain == ""
