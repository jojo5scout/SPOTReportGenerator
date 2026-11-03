"""Archive of processed input bundles (architecture section 3, "Archive", D13).

A bundle is copied to ``<archive_root>/<school>/<wave>/<seq>/``. Only ``manifest.json``
and the responses file named in the manifest are copied (byte for byte); anything else
lying next to them, such as a free-text file (D14), is never archived.

An existing copy is never touched. The copy is first written to a hidden temporary
directory next to the target and then renamed to the next free sequence number, so a
crashed run leaves no half-written ``<seq>/`` and two concurrent runs cannot take the
same number: the loser of the rename retries with the next one.

``<seq>`` is the highest existing all-digit directory name plus one, zero-padded to
three digits (``001``, ``002``, ...). Gaps and other entries do not matter. After
``999`` the number simply gets more digits (``1000``).

``school.id`` and ``wave.label`` become path segments and must match
``[A-Za-z0-9][A-Za-z0-9._-]*`` (at most 100 characters). Error messages name the field
but never its value.
"""

from __future__ import annotations

import errno
import re
import shutil
import tempfile
from pathlib import Path

from spot_report.ingest.manifest import Manifest

MANIFEST_FILE = "manifest.json"

_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_MAX_SEGMENT_LENGTH = 100
_SEQUENCE = re.compile(r"[0-9]+")
_TARGET_TAKEN = {errno.EEXIST, errno.ENOTEMPTY}


class ArchiveError(ValueError):
    """The bundle cannot be archived. Messages never contain manifest values."""


def archive_bundle(bundle_dir: Path, manifest: Manifest, archive_root: Path) -> Path:
    """Copy the bundle to the next free sequence directory and return that directory."""
    school = _segment(manifest.school.id, "school.id")
    wave = _segment(manifest.wave.label, "wave.label")
    sources = [
        (bundle_dir / MANIFEST_FILE, MANIFEST_FILE),
        (bundle_dir / manifest.responses.file, "responses.file"),
    ]
    for source, field in sources:
        if not source.is_file():
            raise ArchiveError(f"Cannot archive: {field} is not a file in the bundle")

    wave_dir = archive_root / school / wave
    wave_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".incoming-", dir=wave_dir))
    try:
        for source, _ in sources:
            shutil.copyfile(source, staging / source.name)
        number = _next_number(wave_dir)
        while True:
            target = wave_dir / f"{number:03d}"
            try:
                staging.rename(target)
            except OSError as exc:
                if exc.errno not in _TARGET_TAKEN:
                    raise
                number = max(number + 1, _next_number(wave_dir))
            else:
                return target
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _next_number(wave_dir: Path) -> int:
    numbers = [
        int(entry.name)
        for entry in wave_dir.iterdir()
        if _SEQUENCE.fullmatch(entry.name) and entry.is_dir()
    ]
    return max(numbers, default=0) + 1


def _segment(value: str, field: str) -> str:
    if len(value) > _MAX_SEGMENT_LENGTH or not _SAFE_SEGMENT.fullmatch(value):
        raise ArchiveError(
            f"{field} is not usable as an archive directory name "
            "(allowed: letters, digits, '.', '_', '-', starting with a letter or digit)"
        )
    return value
