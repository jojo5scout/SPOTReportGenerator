"""Bundle archive: sequence numbers, never overwriting, only the declared files.

Acceptance (R10): a run produces the archive copy; a second run for the same school and
wave adds ``002`` and leaves ``001`` unchanged; nothing is written inside the repository
(every path below lies under ``tmp_path``, which the tests assert).
"""

from __future__ import annotations

import errno
import json
import shutil
from pathlib import Path

import pytest

from spot_report.config import archive_dir
from spot_report.ingest import ArchiveError, archive_bundle, load_manifest
from spot_report.ingest import archive as archive_module
from tests.conftest import FIXTURE_CSV, manifest_dict

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_bundle(
    base: Path, *, school: str = "demo", wave: str = "2026", name: str = "bundle"
) -> Path:
    bundle = base / name
    bundle.mkdir()
    manifest = manifest_dict(
        school={"id": school, "name": "Demo School"},
        wave={"label": wave, "fieldwork_end": "2026-05-15"},
    )
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    shutil.copyfile(FIXTURE_CSV, bundle / "responses.csv")
    return bundle


def archive(bundle: Path, root: Path) -> Path:
    return archive_bundle(bundle, load_manifest(bundle / "manifest.json"), root)


def snapshot(directory: Path) -> dict[str, tuple[bytes, int]]:
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "archive"


def test_first_run_creates_001_with_identical_bytes(tmp_path: Path, root: Path) -> None:
    bundle = make_bundle(tmp_path)
    copy = archive(bundle, root)
    assert copy == root / "demo" / "2026" / "001"
    assert REPO_ROOT not in copy.resolve().parents
    assert tmp_path in copy.parents
    assert sorted(p.name for p in copy.iterdir()) == ["manifest.json", "responses.csv"]
    for name in ("manifest.json", "responses.csv"):
        assert (copy / name).read_bytes() == (bundle / name).read_bytes()


def test_second_run_adds_002_and_leaves_001_unchanged(
    tmp_path: Path, root: Path
) -> None:
    bundle = make_bundle(tmp_path)
    first = archive(bundle, root)
    before = snapshot(first)
    dir_mtime = first.stat().st_mtime_ns

    second = archive(bundle, root)

    assert second == root / "demo" / "2026" / "002"
    assert snapshot(first) == before
    assert first.stat().st_mtime_ns == dir_mtime
    assert snapshot(second).keys() == before.keys()


def test_other_school_or_wave_starts_at_001(tmp_path: Path, root: Path) -> None:
    archive(make_bundle(tmp_path), root)
    other_wave = make_bundle(tmp_path, wave="2027", name="b2")
    other_school = make_bundle(tmp_path, school="other", name="b3")
    assert archive(other_wave, root).name == "001"
    assert archive(other_school, root).name == "001"


def test_gaps_and_non_numeric_entries_do_not_break_numbering(
    tmp_path: Path, root: Path
) -> None:
    wave_dir = root / "demo" / "2026"
    for name in ("001", "004"):
        (wave_dir / name).mkdir(parents=True)
    (wave_dir / "notes").mkdir()
    (wave_dir / "007.bak").mkdir()
    (wave_dir / "009").write_text("a file, not a copy")
    copy = archive(make_bundle(tmp_path), root)
    assert copy.name == "005"
    assert not list(wave_dir.glob(".incoming-*"))


def test_numbering_continues_beyond_999(tmp_path: Path, root: Path) -> None:
    (root / "demo" / "2026" / "999").mkdir(parents=True)
    assert archive(make_bundle(tmp_path), root).name == "1000"


def test_preexisting_copy_is_never_modified(tmp_path: Path, root: Path) -> None:
    existing = root / "demo" / "2026" / "001"
    existing.mkdir(parents=True)
    (existing / "responses.csv").write_bytes(b"older bundle")
    (existing / "manifest.json").write_bytes(b"{}")
    before = snapshot(existing)

    copy = archive(make_bundle(tmp_path), root)

    assert copy.name == "002"
    assert snapshot(existing) == before


def test_lost_race_retries_with_next_number(
    tmp_path: Path, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another run takes the number between choosing it and the rename."""
    wave_dir = root / "demo" / "2026"
    real_next = archive_module._next_number
    calls = 0

    def racing_next(directory: Path) -> int:
        nonlocal calls
        number = real_next(directory)
        calls += 1
        if calls == 1:  # a concurrent run completes number `number` just now
            taken = directory / f"{number:03d}"
            taken.mkdir()
            (taken / "responses.csv").write_bytes(b"concurrent")
        return number

    monkeypatch.setattr(archive_module, "_next_number", racing_next)
    copy = archive(make_bundle(tmp_path), root)

    assert copy == wave_dir / "002"
    assert (wave_dir / "001" / "responses.csv").read_bytes() == b"concurrent"
    assert not list(wave_dir.glob(".incoming-*"))


def test_unexpected_rename_error_propagates_and_cleans_up(
    tmp_path: Path, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_next(_: Path) -> int:
        raise OSError(errno.EIO, "disk error")

    monkeypatch.setattr(archive_module, "_next_number", failing_next)
    with pytest.raises(OSError, match="disk error"):
        archive(make_bundle(tmp_path), root)
    wave_dir = root / "demo" / "2026"
    assert list(wave_dir.iterdir()) == []


def test_only_manifest_and_responses_file_are_copied(
    tmp_path: Path, root: Path
) -> None:
    bundle = make_bundle(tmp_path)
    (bundle / "freetext.csv").write_text("free text answers")
    (bundle / "notes.txt").write_text("notes")
    (bundle / "responses.xlsx").write_bytes(b"not the declared file")
    (bundle / "sub").mkdir()
    copy = archive(bundle, root)
    assert sorted(p.name for p in copy.iterdir()) == ["manifest.json", "responses.csv"]


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "..",
        "a/b",
        "a\\b",
        "../x",
        "/abs",
        ".hidden",
        "-lead",
        "has space",
        "tab\there",
        "new\nline",
        "trailing\n",
        "nul\x00",
        "ümlaut",
        "x" * 101,
    ],
)
@pytest.mark.parametrize("field", ["school", "wave"])
def test_unsafe_segments_are_rejected_without_echoing_the_value(
    tmp_path: Path, root: Path, field: str, value: str
) -> None:
    bundle = make_bundle(tmp_path)
    manifest = load_manifest(bundle / "manifest.json")
    if field == "school":
        unsafe = type(manifest)(
            school=type(manifest.school)(id=value, name="n"),
            wave=manifest.wave,
            survey=manifest.survey,
            responses=manifest.responses,
        )
        expected = "school.id"
    else:
        unsafe = type(manifest)(
            school=manifest.school,
            wave=type(manifest.wave)(
                label=value, fieldwork_end=manifest.wave.fieldwork_end
            ),
            survey=manifest.survey,
            responses=manifest.responses,
        )
        expected = "wave.label"
    with pytest.raises(ArchiveError, match=expected) as info:
        archive_bundle(bundle, unsafe, root)
    if len(value.strip()) > 3:  # shorter values may occur in the rule text
        assert value not in str(info.value)
    assert not root.exists()


@pytest.mark.parametrize("value", ["demo", "gym-example", "2026", "2026.1", "A_b-c.9"])
def test_ordinary_segments_are_accepted(tmp_path: Path, root: Path, value: str) -> None:
    bundle = make_bundle(tmp_path, school=value, wave=value)
    assert archive(bundle, root) == root / value / value / "001"


def test_missing_responses_file_is_an_error_and_writes_nothing(
    tmp_path: Path, root: Path
) -> None:
    bundle = make_bundle(tmp_path)
    (bundle / "responses.csv").unlink()
    with pytest.raises(ArchiveError, match=r"responses\.file"):
        archive(bundle, root)
    assert not root.exists()


def test_archive_dir_setting() -> None:
    assert archive_dir({"SPOT_ARCHIVE_DIR": "/some/where"}) == Path("/some/where")
    assert archive_dir({}) is None
    assert archive_dir({"SPOT_ARCHIVE_DIR": "  "}) is None
