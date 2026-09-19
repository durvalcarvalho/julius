import typing

from julius.cli import _hints
from julius.domain.models import Hint, HintKind


def test_every_hint_kind_has_a_text():
    # FIRST_IMPORT_NAME_STORES/SAME_CHAIN_BRANCHES are worded by _RENAME_HINTS instead (see below).
    assert set(_hints.TEXTS) | set(_hints._RENAME_HINTS) == set(typing.get_args(HintKind))
    assert all(
        "{details}" in text or kind in ("NO_RECEIPTS_IMPORTED", "AI_NOT_CONFIGURED", "PRODUCTS_PENDING_REVIEW")
        for kind, text in _hints.TEXTS.items()
    )


def test_print_hints_formats_details_and_prefix(capsys):
    _hints.print_hints([Hint("NO_MATCH_DID_YOU_MEAN", ("PICANHA", "FRALDINHA"))])
    out = capsys.readouterr().out
    assert out.startswith("Dica: ")
    assert "PICANHA · FRALDINHA" in out
    assert out.count("Dica:") == 1


def test_new_hint_texts_contain_their_commands():
    assert "produtos revisar" in _hints.TEXTS["PRODUCTS_PENDING_REVIEW"]
    assert "produtos renomear" in _hints.TEXTS["FOUND_VIA_AI"]


def test_rename_hints_print_one_ready_command_per_store(capsys):
    _hints.print_hints([Hint("SAME_CHAIN_BRANCHES", ("11832478000285\tDona De Casa — Guará II",))])
    out = capsys.readouterr().out
    assert 'julius mercados renomear 11832478000285 "Dona De Casa — Guará II"' in out
    assert "1 mercado de filiais da mesma rede sem apelido" in out


def test_rename_hints_pluralize_the_intro(capsys):
    _hints.print_hints(
        [Hint("FIRST_IMPORT_NAME_STORES", ("1\tA", "2\tB"))]
    )
    out = capsys.readouterr().out
    assert "2 mercados ainda com a razão social como nome" in out


def test_pending_review_hint_uses_correct_singular_and_plural(capsys):
    _hints.print_hints([Hint("PRODUCTS_PENDING_REVIEW", ("1",))])
    assert "1 produto novo sem categoria" in capsys.readouterr().out
    _hints.print_hints([Hint("PRODUCTS_PENDING_REVIEW", ("3",))])
    assert "3 produtos novos sem categoria" in capsys.readouterr().out


def test_print_hints_to_stderr_and_empty_details_say_none(capsys):
    _hints.print_hints([Hint("UNKNOWN_TAG")], to_stderr=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Tags atuais: nenhuma" in captured.err


def test_print_hints_ignores_kind_without_text(capsys, monkeypatch):
    monkeypatch.delitem(_hints.TEXTS, "AI_NOT_CONFIGURED")
    _hints.print_hints([Hint("AI_NOT_CONFIGURED"), Hint("NO_RECEIPTS_IMPORTED")])
    out = capsys.readouterr().out
    assert out.count("Dica:") == 1 and "julius importar" in out
