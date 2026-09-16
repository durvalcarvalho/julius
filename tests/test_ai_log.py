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
