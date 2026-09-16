import json
from pathlib import Path

from julius.infra import ai_log


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_append_creates_parent_and_writes_one_json_line_per_call(tmp_path):
    path = tmp_path / "sub" / "ai_calls.jsonl"
    ai_log.append(path, {"call_kind": "merge", "note": "café"})
    ai_log.append(path, {"call_kind": "enrich", "note": "açúcar"})
    lines = _lines(path)
    assert len(lines) == 2
    assert lines[0]["note"] == "café"
    assert lines[1]["call_kind"] == "enrich"
    assert '"café"' in path.read_text(encoding="utf-8")


def test_append_never_raises_when_path_is_unwritable(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    path = blocker / "ai_calls.jsonl"
    ai_log.append(path, {"a": 1})  # must not raise
    assert not path.exists()


def test_append_serializes_unknown_types_with_str(tmp_path):
    path = tmp_path / "ai_calls.jsonl"
    ai_log.append(path, {"where": Path("/tmp/x")})
    assert _lines(path)[0]["where"] == "/tmp/x"


def test_tail_returns_newest_first(tmp_path):
    path = tmp_path / "actions.jsonl"
    for index in range(3):
        ai_log.append(path, {"i": index})
    assert [record["i"] for record in ai_log.tail(path)] == [2, 1, 0]


def test_tail_respects_limit(tmp_path):
    path = tmp_path / "actions.jsonl"
    for index in range(5):
        ai_log.append(path, {"i": index})
    assert [record["i"] for record in ai_log.tail(path, 2)] == [4, 3]
    assert [record["i"] for record in ai_log.tail(path, 0)] == [4]


def test_tail_skips_invalid_lines(tmp_path):
    path = tmp_path / "actions.jsonl"
    ai_log.append(path, {"i": 1})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"i": 2, "truncad\n\n')
    ai_log.append(path, {"i": 3})
    assert [record["i"] for record in ai_log.tail(path)] == [3, 1]


def test_tail_missing_file_returns_empty(tmp_path):
    assert ai_log.tail(tmp_path / "nao-existe.jsonl") == []
    assert ai_log.tail(tmp_path) == []
