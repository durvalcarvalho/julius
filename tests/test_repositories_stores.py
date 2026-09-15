import pytest

from julius.domain.models import Store
from julius.repositories import stores

CNPJ = "27289076001379"
LEGAL_NAME = "FL 3 COSTA MULTICANAL S A"


def test_ensure_store_creates_with_nickname_equal_to_legal_name(conn):
    stores.ensure_store(conn, CNPJ, LEGAL_NAME)
    assert stores.get_store(conn, CNPJ) == Store(cnpj=CNPJ, legal_name=LEGAL_NAME, nickname=LEGAL_NAME)


def test_ensure_store_twice_is_idempotent(conn):
    stores.ensure_store(conn, CNPJ, LEGAL_NAME)
    stores.ensure_store(conn, CNPJ, LEGAL_NAME)
    assert conn.execute("SELECT count(*) FROM stores").fetchone()[0] == 1


def test_ensure_store_never_overwrites_edited_nickname(conn):
    stores.ensure_store(conn, CNPJ, LEGAL_NAME)
    stores.rename_store(conn, CNPJ, "FL 3 Costa")
    stores.ensure_store(conn, CNPJ, "OUTRA RAZAO SOCIAL")
    assert stores.get_store(conn, CNPJ) == Store(cnpj=CNPJ, legal_name=LEGAL_NAME, nickname="FL 3 Costa")


def test_list_stores_orders_by_nickname(conn):
    stores.ensure_store(conn, "1", "Zebra")
    stores.ensure_store(conn, "2", "Alpha")
    stores.ensure_store(conn, "3", "Mid")
    assert [store.nickname for store in stores.list_stores(conn)] == ["Alpha", "Mid", "Zebra"]


def test_list_stores_empty_returns_empty_list(conn):
    assert stores.list_stores(conn) == []


def test_rename_store_updates_nickname(conn):
    stores.ensure_store(conn, CNPJ, LEGAL_NAME)
    stores.rename_store(conn, CNPJ, "Atacadão Águas Claras")
    assert stores.get_store(conn, CNPJ).nickname == "Atacadão Águas Claras"


def test_rename_store_unknown_cnpj_raises_lookup_error(conn):
    with pytest.raises(LookupError, match="00000000000000"):
        stores.rename_store(conn, "00000000000000", "x")


def test_get_store_returns_none_when_missing(conn):
    assert stores.get_store(conn, "00000000000000") is None
