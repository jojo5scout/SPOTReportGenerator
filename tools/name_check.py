"""Reject files and commit messages that contain a denylisted term.

The terms are read from the untracked `.denylist.txt` in the repository root (one
term per line, blank lines and lines starting with `#` are ignored). Matching is
case-insensitive and Unicode-normalised. The check fails if the denylist is missing,
so it cannot be skipped by accident; CI does not run it because it has no denylist.

Findings name the file, the line and the number of the denylist entry, never the term
itself, so that the output can be pasted into an issue without leaking it.

Usage as pre-commit hooks:
    name_check.py FILE...                 # stage pre-commit, staged files
    name_check.py --commit-msg MSG_FILE   # stage commit-msg
"""

from __future__ import annotations

import argparse
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DENYLIST = Path(".denylist.txt")
SCISSORS = "# ------------------------ >8 ------------------------"


@dataclass(frozen=True)
class Finding:
    source: str
    line: int  # 0 means the file path itself
    entry: int  # 1-based position in the denylist


def normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def load_denylist(path: Path) -> list[str]:
    """Return the normalised terms, in file order."""
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        term = line.strip()
        if term and not term.startswith("#"):
            terms.append(normalise(term))
    return terms


def scan_lines(
    source: str, lines: Iterable[str], terms: Sequence[str]
) -> list[Finding]:
    findings = []
    for line_no, line in enumerate(lines, start=1):
        text = normalise(line)
        for entry, term in enumerate(terms, start=1):
            if term in text:
                findings.append(Finding(source, line_no, entry))
    return findings


def scan_file(path: Path, terms: Sequence[str]) -> list[Finding]:
    findings = [
        Finding(str(path), 0, entry)
        for entry, term in enumerate(terms, start=1)
        if term in normalise(str(path))
    ]
    text = path.read_bytes().decode("utf-8", errors="replace")
    return findings + scan_lines(str(path), text.splitlines(), terms)


def commit_message_lines(text: str) -> list[str]:
    """Lines git keeps in the message: drop comments and the verbose diff."""
    lines = text.split(SCISSORS, 1)[0].splitlines()
    return ["" if line.startswith("#") else line for line in lines]


def scan_commit_message(path: Path, terms: Sequence[str]) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return scan_lines("commit message", commit_message_lines(text), terms)


def format_finding(finding: Finding) -> str:
    where = finding.source if finding.line == 0 else f"{finding.source}:{finding.line}"
    what = "file name" if finding.line == 0 else "line"
    return f"{where}: {what} matches denylist entry {finding.entry}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--commit-msg", type=Path, metavar="MSG_FILE")
    parser.add_argument("--denylist", type=Path, default=DEFAULT_DENYLIST)
    args = parser.parse_args(argv)

    if not args.denylist.is_file():
        print(
            f"{args.denylist} not found. The name check needs the local denylist "
            "(see CLAUDE.local.md); create it before committing."
        )
        return 1
    terms = load_denylist(args.denylist)
    if not terms:
        print(f"{args.denylist} contains no terms.")
        return 1

    findings: list[Finding] = []
    if args.commit_msg is not None:
        findings += scan_commit_message(args.commit_msg, terms)
    for path in args.paths:
        findings += scan_file(path, terms)

    for finding in findings:
        print(format_finding(finding))
    if findings:
        print("Use the neutral instrument aliases instead (see CLAUDE.md).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
