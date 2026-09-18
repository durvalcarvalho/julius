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
