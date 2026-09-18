from datetime import date

import pytest

from julius.bot import render
from julius.domain.models import KindComparison, PriceRecord, Product, Store, StoreComparison, StorePrice

TODAY = date(2026, 9, 17)


def _record(**overrides) -> PriceRecord:
    base = {
        "product_id": 1,
        "canonical_name": "Picanha bovina",
        "store_nickname": "Dona de Casa",
        "unit": "KG",
        "unit_price": 89.9,
        "purchased_at": "2026-09-12T13:09:16",
    }
    return PriceRecord(**{**base, **overrides})


def _egg(product_id: int, price: float, per_content: float) -> PriceRecord:
    return _record(
        product_id=product_id,
        canonical_name=f"Ovos {product_id}",
        unit="UN",
        unit_price=price,
        price_per_content=per_content,
        content_unit="UN",
    )


def _comparison(*groups: KindComparison, total: int = 0, single: int = 0) -> StoreComparison:
    return StoreComparison(
        comparisons=groups,
        first_purchase="2026-09-05",
        last_purchase="2026-09-12",
        kinds_total=total,
        kinds_single_store=single,
    )


def _group(kind: str, *entries: StorePrice, basis: str = "unit_price", unit: str = "KG", content_unit=None) -> KindComparison:
    return KindComparison(kind=kind, unit=unit, basis=basis, content_unit=content_unit, entries=entries)


def _entry(nickname: str, cnpj: str, price: float, name: str = "Tomate") -> StorePrice:
    return StorePrice(
        store_nickname=nickname, price=price, purchased_at="2026-09-12", product_name=name, store_cnpj=cnpj
    )


def test_render_records_empty():
    assert render.render_records([]) == "Nenhum resultado."


def test_render_records_one_block_per_unit_in_input_order():
    text = render.render_records([_record(unit="UN"), _record(unit="KG")], today=TODAY)

    assert text.index("<b>Preços por UN</b>") < text.index("<b>Preços por KG</b>")
    assert text.count("<pre>") == 2


def test_records_facts_one_line_per_record_no_html():
    text = render.records_facts(
        [_record(highlight="lowest", unit_price=3.79, store_nickname="Costa Atacadao")], today=TODAY
    )

    assert text == "Picanha bovina · R$ 3,79 o quilo (mais barato) · sábado · Costa Atacadao"
    assert "<" not in text and ">" not in text


def test_records_facts_marks_highest_and_carries_content_price():
    text = render.records_facts([_egg(1, 12.0, 0.60), _egg(2, 16.5, 0.55)], today=TODAY)
    lines = text.split("\n")

    assert "R$ 12,00 a unidade · R$ 0,60/UN" in lines[0]
    assert "R$ 16,50 a unidade · R$ 0,55/UN" in lines[1]
    assert "(mais barato)" not in text and "(mais caro)" not in text  # neither record carries `highlight` here


def test_records_facts_states_the_difference_when_there_are_two_or_more():
    records = [
        _record(highlight="lowest", unit_price=3.79),
        _record(highlight="highest", unit_price=5.99),
    ]

    text = render.records_facts(records, today=TODAY)

    assert text.splitlines()[-1] == "diferença entre o mais barato e o mais caro: R$ 2,20"


def test_records_facts_no_difference_line_without_a_highlighted_pair():
    text = render.records_facts([_record(), _record()], today=TODAY)

    assert "diferença" not in text


def test_records_facts_empty_is_empty_string():
    assert render.records_facts([]) == ""


def test_records_facts_uses_weekday_phrase_not_the_calendar_date():
    text = render.records_facts([_record()], today=TODAY)

    assert "2026" not in text
    assert "sábado" in text


def test_records_facts_collapses_repeated_price_before_narration():
    """The real screenshot that started this ticket: the same store, the same price, only the
    date differing -- must collapse to one line, keeping the most recent date."""
    records = [
        _record(store_nickname="Costa Atacadao", unit_price=7.89, purchased_at="2026-09-12T10:00:00"),
        _record(store_nickname="Costa Atacadao", unit_price=7.89, purchased_at="2026-09-16T10:00:00"),
    ]

    text = render.records_facts(records, today=TODAY)

    assert text.count("Costa Atacadao") == 1
    assert "ontem" in text  # kept the more recent of the two (2026-09-16, one day before TODAY)


def test_collapse_repeated_prices_merges_same_store_and_price_keeping_latest_date():
    older = _record(store_nickname="Costa Atacadao", unit_price=7.89, purchased_at="2026-09-12T10:00:00")
    newer = _record(store_nickname="Costa Atacadao", unit_price=7.89, purchased_at="2026-09-16T10:00:00")

    collapsed = render._collapse_repeated_prices([older, newer])

    assert collapsed == [newer]


def test_collapse_repeated_prices_keeps_different_stores_or_prices_separate():
    a = _record(store_nickname="Costa Atacadao", unit_price=7.89)
    b = _record(store_nickname="Dona de Casa", unit_price=7.89)
    c = _record(store_nickname="Costa Atacadao", unit_price=9.99)

    collapsed = render._collapse_repeated_prices([a, b, c])

    assert collapsed == [a, b, c]


def test_collapse_repeated_prices_empty_list():
    assert render._collapse_repeated_prices([]) == []


def test_comparison_facts_one_line_per_entry_with_markers():
    comparison = _comparison(
        _group("tomate", _entry("Assaí", "1", 11.89), _entry("Dona de Casa", "2", 14.99)),
    )

    text = render.comparison_facts(comparison, today=TODAY)
    lines = text.split("\n")

    assert lines[0] == "tomate · Assaí · R$ 11,89 o quilo (mais barato) · sábado"
    assert lines[1] == "tomate · Dona de Casa · R$ 14,99 o quilo (mais caro) · sábado"
    assert lines[2] == "tomate: diferença entre o mais barato e o mais caro: R$ 3,10"


def test_comparison_facts_empty_is_empty_string():
    assert render.comparison_facts(_comparison()) == ""


def test_comparison_facts_uses_weekday_phrase_not_the_calendar_date():
    comparison = _comparison(_group("tomate", _entry("Assaí", "1", 11.89)))

    text = render.comparison_facts(comparison, today=TODAY)

    assert "2026" not in text
    assert "sábado" in text


def test_products_facts_counts():
    products = [Product(id=3, canonical_name="Ovos"), Product(id=4, canonical_name="Alho")]

    assert render.products_facts(products) == "2 produtos no catálogo"
    assert render.products_facts([]) == ""


def test_stores_facts_counts():
    stores = [Store(cnpj="11832478000285", legal_name="DONA DE CASA S/A", nickname="Dona de Casa")]

    assert render.stores_facts(stores) == "1 mercados importados"
    assert render.stores_facts([]) == ""


def test_search_fallback_line_one_record():
    text = render.search_fallback_line([_record(store_nickname="Costa Atacadao")], today=TODAY)

    assert text == "Só uma compra registrada: Picanha bovina a R$ 89,90 o quilo em Costa Atacadao, há 5 dias."


def test_search_fallback_line_marks_cheapest_and_dearest():
    records = [
        _record(highlight="lowest", unit_price=3.79, store_nickname="Costa Atacadao"),
        _record(highlight="highest", unit_price=5.99, store_nickname="Assaí Guará"),
    ]

    text = render.search_fallback_line(records, today=TODAY)

    assert "R$ 3,79 o quilo, em Costa Atacadao" in text
    assert "R$ 5,99, em Assaí Guará" in text
    assert "diferença de R$ 2,20" in text


def test_search_fallback_line_without_highlight_falls_back_to_a_count():
    text = render.search_fallback_line([_record(), _record()], today=TODAY)

    assert text == "2 compras registradas de Picanha bovina. Fica de olho nos preços."


def test_search_fallback_line_empty():
    assert render.search_fallback_line([]) == "Nenhum resultado."


def test_search_fallback_line_never_has_html():
    text = render.search_fallback_line(
        [
            _record(highlight="lowest", canonical_name="AÇÚCAR & CIA"),
            _record(highlight="highest", unit_price=9.0),
        ],
        today=TODAY,
    )
    assert "<" not in text and ">" not in text


def test_compare_fallback_line_one_line_per_group():
    comparison = _comparison(
        _group("tomate", _entry("Assaí", "1", 11.89), _entry("Dona de Casa", "2", 14.99)),
        _group("cebola", _entry("Assaí", "1", 3.99), _entry("Dona de Casa", "2", 5.49)),
    )

    text = render.compare_fallback_line(comparison)

    assert "tomate: Assaí sai mais em conta, a R$ 11,89 o quilo." in text
    assert "cebola: Assaí sai mais em conta, a R$ 3,99 o quilo." in text


def test_compare_fallback_line_no_comparable_groups():
    assert render.compare_fallback_line(_comparison()) == render.render_comparison(_comparison())
    assert render.compare_fallback_line(_comparison(total=3, single=3)) == render.render_comparison(
        _comparison(total=3, single=3)
    ).split("\n")[0]


def test_render_records_markers():
    text = render.render_records(
        [
            _record(highlight="lowest", unit_price=1.0),
            _record(highlight="highest", unit_price=9.0),
            _record(unit_price=5.0),
        ],
        today=TODAY,
    )
    lines = text.split("<pre>")[1].split("</pre>")[0].split("\n")

    assert lines[0].startswith("▼ ")
    assert lines[1].startswith("▲ ")
    assert lines[2].startswith("  ")


def test_render_records_per_content_and_cheapest_line():
    """The user's own case: the bigger pack costs more in total and less per egg."""
    text = render.render_records([_egg(1, 12.00, 0.60), _egg(2, 16.50, 0.55)], today=TODAY)

    assert "R$ 0,60/UN" in text
    assert "R$ 0,55/UN" in text
    assert "Mais barato por unidade: Ovos 2 a R$ 0,55/UN — contra R$ 0,60/UN de Ovos 1." in text


def test_render_records_no_cheapest_line_for_kg_group():
    """R$/kg already is a price per content -- there is nothing to restate."""
    text = render.render_records([_record(unit_price=1.0), _record(product_id=2, unit_price=9.0)], today=TODAY)

    assert "Mais barato por" not in text


def test_render_records_no_cheapest_line_when_the_prices_tie():
    text = render.render_records([_egg(1, 12.0, 0.60), _egg(2, 18.0, 0.60)], today=TODAY)

    assert "Mais barato por" not in text


def test_render_records_escapes_html():
    """Telegram rejects the whole message on bad markup, and says nothing about why."""
    text = render.render_records([_record(canonical_name="AÇÚCAR & CIA <2kg>")], today=TODAY)

    assert "AÇÚCAR &amp; CIA &lt;2kg&gt;" in text
    assert "<2kg>" not in text


def test_render_records_store_place():
    with_address = render.render_records(
        [_record(store_address="QUADRA QE 30, 02/39, LJS 02/39, GUARA II, BRASILIA, DF")], today=TODAY
    )
    without = render.render_records([_record()], today=TODAY)

    assert "Dona de Casa — GUARA II" in with_address
    assert "Dona de Casa —" not in without
    assert "Dona de Casa" in without


def test_render_records_carries_the_date_and_its_age():
    text = render.render_records([_record()], today=TODAY)

    assert "12/09/2026 · há 5 dias" in text


def test_render_comparison_empty_messages():
    assert render.render_comparison(_comparison()) == "Nenhum produto tem tipo ainda. Rode: julius produtos revisar"

    text = render.render_comparison(_comparison(total=3, single=3))
    assert "sem base para comparar" in text
    assert "todos os 3 tipos comprados saíram de um mercado só" in text


def test_render_comparison_groups_wins_and_footer():
    comparison = _comparison(
        _group("tomate", _entry("Assaí", "1", 11.89), _entry("Dona de Casa", "2", 14.99)),
        _group("cebola", _entry("Assaí", "1", 3.99), _entry("Dona de Casa", "2", 5.49)),
        total=3,
        single=1,
    )

    text = render.render_comparison(comparison, today=TODAY)

    assert "<b>tomate · por KG</b>" in text
    assert "▼ Assaí · R$ 11,89" in text
    assert "▲ Dona de Casa · R$ 14,99" in text
    assert "Assaí: mais barato em 2 de 2 grupos" in text
    assert "Dona de Casa: mais barato em 0 de 2 grupos" in text
    assert "base: 2 grupos · 05/09/2026 a 12/09/2026 · 1 dos 3 tipos comprados em um mercado só" in text
    assert "Período largo" in text


def test_render_comparison_uses_the_content_basis_in_the_heading():
    comparison = _comparison(
        _group("ovos", _entry("A", "1", 0.55), _entry("B", "2", 0.60), basis="price_per_content", unit="UN", content_unit="UN")
    )

    assert "<b>ovos · por UN (por conteúdo)</b>" in render.render_comparison(comparison, today=TODAY)


def test_render_comparison_duplicated_nickname_gets_cnpj():
    comparison = _comparison(
        _group(
            "tomate",
            _entry("Dona de Casa", "11832478000285", 11.89),
            _entry("Dona de Casa", "11832478000366", 14.99),
        )
    )

    text = render.render_comparison(comparison, today=TODAY)

    assert "Dona de Casa · 11832478000285" in text
    assert "Dona de Casa · 11832478000366" in text


def test_render_products_and_stores():
    assert render.render_products([]) == "Nenhum produto importado ainda."
    assert render.render_stores([]) == "Nenhum mercado importado ainda."

    products = render.render_products(
        [
            Product(id=3, canonical_name="Ovos", content_quantity=30, content_unit="UN", tags=("mercearia",), kind="ovo"),
            Product(id=4, canonical_name="Alho"),
        ]
    )
    assert "3 · Ovos · ovo · 30 UN · mercearia" in products
    assert "4 · Alho · — · — · —" in products

    stores = render.render_stores(
        [
            Store(cnpj="11832478000285", legal_name="DONA DE CASA S/A", nickname="Dona de Casa", address="R X, 1, , GUARA II, BRASILIA, DF"),
            Store(cnpj="20209736000181", legal_name="HTP LTDA", nickname="HTP"),
        ]
    )
    assert "11832478000285 · Dona de Casa · GUARA II" in stores
    assert "20209736000181 · HTP" in stores


def test_fit_leaves_a_short_message_alone():
    assert render.fit("<pre>uma linha</pre>") == "<pre>uma linha</pre>"


def test_fit_truncates_at_a_line_and_closes_pre():
    text = render.render_records([_record(product_id=i, canonical_name=f"Produto {i}") for i in range(300)], today=TODAY)

    assert len(text) <= render.MAX_MESSAGE_CHARS
    assert text.count("<pre>") == text.count("</pre>")
    assert "linhas não mostradas" in text
    assert not text.endswith("</pre>")


def test_fit_reports_how_many_lines_it_dropped():
    lines = "\n".join(f"linha {i} " + "x" * 80 for i in range(200))

    text = render.fit(f"<pre>{lines}</pre>")

    kept = text.split("</pre>")[0].count("\n") + 1
    assert f"+{200 - kept} linhas não mostradas" in text
    assert len(text) <= render.MAX_MESSAGE_CHARS


@pytest.mark.parametrize("raw", ["", "lixo"])
def test_render_survives_an_unusable_date(raw):
    assert render.render_records([_record(purchased_at=raw)], today=TODAY)
