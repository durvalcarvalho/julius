from __future__ import annotations

import sqlite3
from pathlib import Path

from julius.domain.models import ImportResult
from julius.parsers import ReceiptParser
from julius.repositories import prices, products, stores


def import_receipt(conn: sqlite3.Connection, path: Path, parser: ReceiptParser) -> ImportResult:
    # Parse everything before touching the database: a bad file must leave it untouched.
    receipt = parser.parse(path.read_text(encoding="utf-8"), source=path.name)
    new_items = 0
    new_product_ids: list[int] = []
    with conn:
        stores.ensure_store(conn, receipt.store_cnpj, receipt.store_legal_name, receipt.store_address)
        for item in receipt.items:
            product_id = products.find_product_id(conn, receipt.store_cnpj, item.product_code)
            if product_id is None:
                product_id = products.resolve_product_id(conn, receipt.store_cnpj, item.product_code, item.description)
                new_product_ids.append(product_id)
            if prices.insert_price(conn, receipt, item, product_id):
                new_items += 1
    return ImportResult(
        new_items=new_items,
        existing_items=len(receipt.items) - new_items,
        new_product_ids=tuple(new_product_ids),
        access_key=receipt.access_key,
        purchased_at=receipt.issued_at,
    )
