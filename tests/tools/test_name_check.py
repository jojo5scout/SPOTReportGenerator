from __future__ import annotations

from pathlib import Path

import pytest

from tools.name_check import commit_message_lines, load_denylist, main

# Made-up terms; the real denylist never appears in the repository.
DENYLIST = "  # comment\n  Foo-Bar\n\n  Bäz Qux\n"


@pytest.fixture
def denylist(tmp_path: Path) -> Path:
    path = tmp_path / ".denylist.txt"
    path.write_text(DENYLIST, encoding="utf-8")
    return path


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_denylist_skips_blanks_and_comments(denylist: Path) -> None:
    assert load_denylist(denylist) == ["foo-bar", "bäz qux"]


def test_clean_file_passes(tmp_path: Path, denylist: Path) -> None:
    clean = write(tmp_path / "clean.md", "Resilience scale RES, alias only.\n")
    assert main(["--denylist", str(denylist), str(clean)]) == 0


@pytest.mark.parametrize(
    "text",
    [
        "uses foo-bar here",
        "FOO-BAR",
        "BÄZ QUX",
        # decomposed umlaut (NFD) must match the composed denylist entry
        "Bäz qux",
    ],
)
def test_denylisted_term_in_file_is_rejected(
    tmp_path: Path, denylist: Path, text: str
) -> None:
    bad = write(tmp_path / "bad.py", f"x = 1\n# {text}\n")
    assert main(["--denylist", str(denylist), str(bad)]) == 1


def test_denylisted_term_in_file_name_is_rejected(
    tmp_path: Path, denylist: Path
) -> None:
    bad = write(tmp_path / "foo-bar_notes.md", "nothing here\n")
    assert main(["--denylist", str(denylist), str(bad)]) == 1


def test_output_names_entry_not_term(
    tmp_path: Path, denylist: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = write(tmp_path / "bad.md", "line one\nsee Foo-Bar\n")
    main(["--denylist", str(denylist), str(bad)])
    out = capsys.readouterr().out
    assert f"{bad}:2: line matches denylist entry 1" in out
    assert "foo-bar" not in out.casefold()


def test_missing_denylist_fails(tmp_path: Path) -> None:
    clean = write(tmp_path / "clean.md", "fine\n")
    missing = tmp_path / "missing.txt"
    assert main(["--denylist", str(missing), str(clean)]) == 1


def test_empty_denylist_fails(tmp_path: Path) -> None:
    empty = write(tmp_path / ".denylist.txt", "\n# only a comment\n")
    assert main(["--denylist", str(empty)]) == 1


def test_commit_message_is_checked(tmp_path: Path, denylist: Path) -> None:
    good = write(tmp_path / "good", "feat: add RES metrics\n")
    bad = write(tmp_path / "bad", "feat: add foo-bar metrics\n")
    assert main(["--denylist", str(denylist), "--commit-msg", str(good)]) == 0
    assert main(["--denylist", str(denylist), "--commit-msg", str(bad)]) == 1


def test_commit_message_ignores_comments_and_verbose_diff() -> None:
    message = (
        "fix: remove old name\n"
        "# Please enter the commit message\n"
        "# ------------------------ >8 ------------------------\n"
        "-old Foo-Bar line\n"
    )
    assert commit_message_lines(message) == ["fix: remove old name", ""]
