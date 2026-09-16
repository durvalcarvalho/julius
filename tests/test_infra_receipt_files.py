from pathlib import Path

import pytest

from julius.infra import receipt_files

KEY_A = "1" * 44
KEY_B = "2" * 44


def _html(directory: Path, name: str = "qrcode.html") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("<html>nota</html>", encoding="utf-8")
    return path


def _sidecar(html_path: Path) -> Path:
    sidecar = html_path.parent / f"{html_path.stem}_files"
    sidecar.mkdir()
    (sidecar / "jquery.js").write_text("// peso morto", encoding="utf-8")
    return sidecar


def test_archive_renames_with_date_and_key(tmp_path):
    source = _html(tmp_path / "entrada")
    destination = tmp_path / "entrada" / "importados"

    archived = receipt_files.archive(source, destination, purchased_at="2026-09-16T18:53:00", access_key=KEY_A)

    assert archived == destination / f"2026-09-16_{KEY_A}.html"
    assert archived.read_text(encoding="utf-8") == "<html>nota</html>"
    assert not source.exists()


def test_archive_creates_destination_dir(tmp_path):
    source = _html(tmp_path / "entrada")
    destination = tmp_path / "entrada" / "importados"
    assert not destination.exists()

    receipt_files.archive(source, destination, purchased_at="2026-09-16T18:53:00", access_key=KEY_A)

    assert destination.is_dir()


def test_archive_overwrites_same_receipt(tmp_path):
    destination = tmp_path / "importados"
    for _ in range(2):
        source = _html(tmp_path / "entrada")
        receipt_files.archive(source, destination, purchased_at="2026-09-16T18:53:00", access_key=KEY_A)

    assert [path.name for path in destination.iterdir()] == [f"2026-09-16_{KEY_A}.html"]


def test_archive_two_receipts_named_qrcode_do_not_collide(tmp_path):
    destination = tmp_path / "importados"
    first = _html(tmp_path / "a")
    second = _html(tmp_path / "b")

    receipt_files.archive(first, destination, purchased_at="2026-09-12T13:09:16", access_key=KEY_A)
    receipt_files.archive(second, destination, purchased_at="2026-09-16T18:53:00", access_key=KEY_B)

    assert sorted(path.name for path in destination.iterdir()) == [
        f"2026-09-12_{KEY_A}.html",
        f"2026-09-16_{KEY_B}.html",
    ]


@pytest.mark.parametrize(
    ("purchased_at", "access_key"),
    [("", KEY_A), ("2026-09-16T18:53:00", ""), ("", "")],
)
def test_archive_requires_key_and_date(tmp_path, purchased_at, access_key):
    source = _html(tmp_path / "entrada")
    with pytest.raises(ValueError):
        receipt_files.archive(source, tmp_path / "importados", purchased_at=purchased_at, access_key=access_key)
    assert source.exists()


def test_discard_sidecar_removes_directory(tmp_path):
    source = _html(tmp_path / "entrada")
    sidecar = _sidecar(source)

    assert receipt_files.discard_sidecar(source) is True
    assert not sidecar.exists()


def test_discard_sidecar_works_after_html_moved(tmp_path):
    source = _html(tmp_path / "entrada")
    sidecar = _sidecar(source)
    receipt_files.archive(source, tmp_path / "importados", purchased_at="2026-09-16T00:00:00", access_key=KEY_A)

    assert receipt_files.discard_sidecar(source) is True
    assert not sidecar.exists()


def test_discard_sidecar_absent_returns_false(tmp_path):
    source = _html(tmp_path / "entrada")
    assert receipt_files.discard_sidecar(source) is False


def test_discard_sidecar_refuses_symlink(tmp_path):
    source = _html(tmp_path / "entrada")
    real = tmp_path / "preciosa"
    real.mkdir()
    (real / "dado.txt").write_text("não apagar", encoding="utf-8")
    (source.parent / "qrcode_files").symlink_to(real, target_is_directory=True)

    assert receipt_files.discard_sidecar(source) is False
    assert (real / "dado.txt").exists()
    assert (source.parent / "qrcode_files").is_symlink()


def test_discard_sidecar_never_raises(tmp_path, monkeypatch):
    source = _html(tmp_path / "entrada")
    _sidecar(source)
    monkeypatch.setattr(
        receipt_files.shutil, "rmtree", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("nope"))
    )

    assert receipt_files.discard_sidecar(source) is False
    assert (source.parent / "qrcode_files").is_dir()


def test_discard_sidecar_ignores_a_file_with_that_name(tmp_path):
    source = _html(tmp_path / "entrada")
    impostor = source.parent / "qrcode_files"
    impostor.write_text("não é diretório", encoding="utf-8")

    assert receipt_files.discard_sidecar(source) is False
    assert impostor.exists()
