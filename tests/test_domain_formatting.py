from datetime import date, timedelta

import pytest

from julius.domain.formatting import (
    br_date,
    content_text,
    coverage_text,
    money,
    plural_groups,
    relative_age,
    store_labels,
    weekday_phrase,
)
from julius.domain.models import KindComparison, StoreComparison, StorePrice

TODAY = date(2026, 9, 17)


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _comparison(*entries: StorePrice, kinds_total: int = 0, kinds_single_store: int = 0) -> StoreComparison:
    group = KindComparison(kind="tomate", unit="KG", basis="unit_price", content_unit=None, entries=entries)
    return StoreComparison(
        comparisons=(group,) if entries else (),
        first_purchase="2026-09-05",
        last_purchase="2026-09-17",
        kinds_total=kinds_total,
        kinds_single_store=kinds_single_store,
    )


def _price(nickname: str, cnpj: str) -> StorePrice:
    return StorePrice(
        store_nickname=nickname, price=9.9, purchased_at="2026-09-17", product_name="Tomate", store_cnpj=cnpj
    )


def test_money_uses_comma():
    assert money(12.9) == "R$ 12,90"
    assert money(0) == "R$ 0,00"


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


@pytest.mark.parametrize(
    ("days_ago", "expected"),
    [
        (0, "hoje"),
        (1, "ontem"),
        (2, "terça-feira"),
        (7, "quinta-feira"),
        (8, "quarta-feira passada"),
        (15, "quarta-feira passada"),
    ],
)
def test_weekday_phrase_bands(days_ago, expected):
    """TODAY (2026-09-17) is a Thursday -- the exact weekdays here are real calendar facts, not
    arbitrary strings, checked against `date.strftime('%A')` before writing the test."""
    assert weekday_phrase(_iso(days_ago), today=TODAY) == expected


@pytest.mark.parametrize("days_ago", [16, 30])
def test_weekday_phrase_falls_back_to_relative_age_after_15_days(days_ago):
    assert weekday_phrase(_iso(days_ago), today=TODAY) == relative_age(_iso(days_ago), today=TODAY)


def test_weekday_phrase_all_seven_names():
    expected = ["quinta-feira", "sexta-feira", "sábado", "domingo", "segunda-feira", "terça-feira", "quarta-feira"]
    names = [weekday_phrase(_iso(days), today=TODAY) for days in range(2, 8)] + [
        weekday_phrase(_iso(8), today=TODAY).replace(" passada", "")
    ]
    assert set(names) == set(expected)


@pytest.mark.parametrize("raw", ["", "2026-13-40", "lixo"])
def test_weekday_phrase_of_junk_is_empty(raw):
    assert weekday_phrase(raw, today=TODAY) == ""


def test_weekday_phrase_of_a_date_ahead_of_the_clock_is_today():
    assert weekday_phrase(_iso(-3), today=TODAY) == "hoje"


def test_content_text_drops_trailing_zeros():
    assert content_text(0.5, "KG") == "0,5 KG"
    assert content_text(30, "UN") == "30 UN"
    assert content_text(1.5, "L") == "1,5 L"


def test_plural_groups():
    assert plural_groups(1) == "grupo"
    assert plural_groups(0) == "grupos"
    assert plural_groups(3) == "grupos"


def test_store_labels_append_cnpj_only_when_nickname_repeats():
    """Two branches of one chain share a nickname until renamed, and two identical rows is worse
    than no row at all."""
    comparison = _comparison(
        _price("Dona de Casa", "11832478000285"),
        _price("Dona de Casa", "11832478000366"),
        _price("Assaí", "27289076001379"),
    )

    labels = store_labels(comparison)

    assert labels["11832478000285"] == "Dona de Casa · 11832478000285"
    assert labels["11832478000366"] == "Dona de Casa · 11832478000366"
    assert labels["27289076001379"] == "Assaí"


def test_store_labels_of_nothing_is_empty():
    assert store_labels(_comparison()) == {}


@pytest.mark.parametrize(
    ("total", "single", "expected"),
    [
        (87, 80, "80 dos 87 tipos comprados em um mercado só"),
        (1, 1, "o único tipo comprado saiu de um mercado só"),
        (5, 5, "todos os 5 tipos comprados saíram de um mercado só"),
    ],
)
def test_coverage_text_three_branches(total, single, expected):
    assert coverage_text(_comparison(kinds_total=total, kinds_single_store=single)) == expected
