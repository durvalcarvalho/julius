import typing

from julius.cli import _hints
from julius.domain.models import Hint, HintKind


def test_every_hint_kind_has_a_text():
    assert set(_hints.TEXTS) == set(typing.get_args(HintKind))
    assert all("{details}" in text or kind in ("NO_RECEIPTS_IMPORTED", "AI_NOT_CONFIGURED") for kind, text in _hints.TEXTS.items())


def test_print_hints_formats_details_and_prefix(capsys):
    _hints.print_hints([Hint("NO_MATCH_DID_YOU_MEAN", ("PICANHA", "FRALDINHA"))])
    out = capsys.readouterr().out
    assert out.startswith("Dica: ")
    assert "PICANHA, FRALDINHA" in out
    assert out.count("Dica:") == 1


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
