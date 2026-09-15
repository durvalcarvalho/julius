from __future__ import annotations

import html as html_lib
import re

from julius.domain.models import Receipt, ReceiptItem
from julius.domain.normalization import digits_only, normalize_sale_unit, parse_decimal_br
from julius.parsers import ReceiptParseError

# Items are anchored on content markers ("(Cód:", "Qtde.:", ...), never on <ul> position:
# summary blocks (totals, payment, taxes) share the same li.list-group-item markup.
_ITEM = re.compile(
    r'<p class="h6">(?P<description>.*?)<small>\s*\(Cód:\s*(?P<code>\d+)\)\s*</small></p>'
    r".*?Qtde\.:\s*</strong>\s*(?P<quantity>[\d.,]+)\s*"
    r"<strong>\s*UN:\s*</strong>\s*(?P<unit>[A-Za-z0-9]+)\s*"
    r"<strong>\s*Vl\. Unit\.:\s*</strong>\s*(?P<unit_price>[\d.,]+)\s*</span></div>\s*"
    r'<div class="col-3"[^>]*><span[^>]*>(?P<total_price>[\d.,]+)</span>',
    re.DOTALL,
)
_LEGAL_NAME = re.compile(r'id="heading1".*?<div class="col" style="font-weight: bold;">(.*?)</div>', re.DOTALL)
_CNPJ = re.compile(r"CNPJ:\s*([\d./-]+)")
_ACCESS_KEY = re.compile(r'Chave de acesso:.*?<p class="h6">([\d ]+)</p>', re.DOTALL)
_ISSUED_AT = re.compile(r"Emissão:\s*</strong>\s*(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2}:\d{2})")
_ITEM_TOTAL = re.compile(r"Qtd\. total de itens:.*?<strong>(\d+)</strong>", re.DOTALL)


def _clean(text: str) -> str:
    return " ".join(html_lib.unescape(text).split())


class DFReceiptParser:
    def parse(self, html: str, source: str = "") -> Receipt:
        legal_name = _clean(self._header(_LEGAL_NAME, html, "store legal name", source))
        cnpj = digits_only(self._header(_CNPJ, html, "CNPJ", source))
        if len(cnpj) != 14:
            raise ReceiptParseError(f"CNPJ must have 14 digits, got {cnpj!r} ({source})")
        access_key = digits_only(self._header(_ACCESS_KEY, html, "access key", source))
        if len(access_key) != 44:
            raise ReceiptParseError(f"access key must have 44 digits, got {access_key!r} ({source})")
        issued = _ISSUED_AT.search(html)
        if not issued:
            raise ReceiptParseError(f"missing issue date ({source})")
        day, month, year, time = issued.groups()

        items = tuple(self._item(index, match, source) for index, match in enumerate(_ITEM.finditer(html), start=1))
        if not items:
            raise ReceiptParseError(f"no items found ({source})")
        declared = _ITEM_TOTAL.search(html)
        if declared and int(declared.group(1)) != len(items):
            raise ReceiptParseError(
                f"receipt declares {declared.group(1)} items but {len(items)} were parsed ({source})"
            )
        return Receipt(
            access_key=access_key,
            issued_at=f"{year}-{month}-{day}T{time}",
            store_cnpj=cnpj,
            store_legal_name=legal_name,
            items=items,
        )

    @staticmethod
    def _header(pattern: re.Pattern[str], html: str, field: str, source: str) -> str:
        match = pattern.search(html)
        if not match:
            raise ReceiptParseError(f"missing {field} ({source})")
        return match.group(1)

    @staticmethod
    def _item(index: int, match: re.Match[str], source: str) -> ReceiptItem:
        description = _clean(match["description"])
        return ReceiptItem(
            index=index,
            product_code=match["code"],
            description=description,
            quantity=parse_decimal_br(match["quantity"]),
            unit=normalize_sale_unit(match["unit"], description=description, source=source),
            unit_price=parse_decimal_br(match["unit_price"]),
            total_price=parse_decimal_br(match["total_price"]),
        )
