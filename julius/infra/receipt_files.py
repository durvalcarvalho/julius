"""Filing of imported receipt HTML. Archive, never delete: the store address was only recovered
in v2 by reparsing old HTML files, so the reparseable source is what must survive."""

from __future__ import annotations

import shutil
from pathlib import Path


def archive(html_path: Path, destination_dir: Path, *, purchased_at: str, access_key: str) -> Path:
    """Moves the HTML to <destination_dir>/<YYYY-MM-DD>_<access_key>.html and returns the path.

    The rename is required, not cosmetic: the browser always saves the page as 'qrcode.html',
    so a flat archive would collide on the second import.
    """
    if not purchased_at or not access_key:
        raise ValueError("purchased_at and access_key are required to name the archived file")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{purchased_at[:10]}_{access_key}.html"
    destination.unlink(missing_ok=True)
    shutil.move(str(html_path), destination)
    return destination


def discard_sidecar(html_path: Path) -> bool:
    """Removes the '<stem>_files' directory next to the HTML, if it exists.

    The only destructive step in the system, so it is fenced: the name is derived exactly from
    the HTML's own stem, the target must be a real directory, and a symlink is never followed.
    Works from the original path, so it can run after the HTML has already been archived.
    """
    sidecar = html_path.parent / f"{html_path.stem}_files"
    if sidecar.is_symlink() or not sidecar.is_dir():
        return False
    try:
        shutil.rmtree(sidecar)
    except OSError:
        return False
    return True
