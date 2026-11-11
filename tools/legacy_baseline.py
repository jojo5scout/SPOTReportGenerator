"""Generate the legacy parity baseline in ``tests/fixtures/expected/`` (roadmap R13).

Runs the previous program on every synthetic fixture and writes the numbers it computed
from the data to ``<output_dir>/<dataset>.json``. ADR 0002 in ``docs/decisions/``
explains the mechanism and ``tests/fixtures/README.md`` the file format;
``tests/parity.py`` reads the files in tests.

This script is **not** run in CI. The test suite imports only its pure helpers, which
need nothing but the standard library; the previous program is imported only by
:func:`main`. Running it needs a checkout of the previous program (read-only: no file
in it is changed or written, not even bytecode caches) and an environment with that
program's pinned requirements. The working directory does not matter. To regenerate,
from the repository root:

.. code-block:: bash

    uv venv --python 3.12 /tmp/legacy-env
    VIRTUAL_ENV=/tmp/legacy-env uv pip install -r <legacy>/requirements.txt
    /tmp/legacy-env/bin/python tools/legacy_baseline.py <legacy> tests/fixtures/expected
    /tmp/legacy-env/bin/python tools/legacy_baseline.py <legacy> \
        tests/fixtures/expected --check     # fail if a committed file is out of date

How the numbers are captured (no legacy file is modified; everything below happens by
replacing names in the imported legacy modules of this process only):

* The program is driven like its ``generate_report`` does: one ``ReportData`` per
  fixture XLSX, then each chapter's ``build_context``; no DOCX is rendered. It runs in
  a temporary working directory, so the chart files it writes are discarded.
* The percentage formatter is wrapped: the wrapper returns the legacy string unchanged,
  tagged with numerator and denominator, so the unrounded percentage is stored too.
* The mean/SD helpers of the burnout, stigma and resilience chapters are wrapped; the
  unrounded mean and SD are taken from the helper's own local variables when it
  returns (or computed with the exact expression the helper formats).
* Chart helpers run unchanged; numbers the charts show and the context does not hold
  (age counts, help-source patterns, box plot statistics, score histogram) are read
  from their local variables when they return. Reference values from literature that
  a chart helper receives are never read.

Excluded: chart paths and objects, warnings, texts, the free-text chapter (its only
number counts non-empty free-text answers, decision D14) and the keys in
``EXCLUDED_KEYS`` (none at present). The counts of filled "other" answers of the
diagnosis questions are kept: the new metrics use whether those columns are filled
(D14 as amended in ADR 0004).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from types import FrameType, ModuleType
from typing import Any

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures"

#: Chapters run, in the order of the previous program. Its ninth chapter only lists
#: free-text answers and is not run at all (decision D14).
CHAPTERS: tuple[str, ...] = (
    "demography",
    "diagnoses",
    "absences",
    "symptoms",
    "assoc",
    "stigma",
    "burnout",
    "resilience",
)

#: Context keys left out, with the reason (written to the file header). Until ADR 0004
#: the counts of filled "other" answers were listed here.
EXCLUDED_KEYS: Mapping[str, str] = {}

#: Top-level context keys whose second segment is the previous program's name for an
#: aliased instrument. That segment is replaced by the alias by position, so the real
#: name never has to be written here (CLAUDE.md, architecture section 8).
ALIASED_SEGMENTS: Mapping[str, str] = {"resilience": "res"}

#: Text the previous program shows instead of a mean or SD it cannot compute.
UNDEFINED_TEXTS = frozenset({"—", "n/a", "nan"})

KIND_COUNT = "count"
KIND_PERCENT = "percent"
KIND_STATISTIC = "statistic"


class BaselineError(RuntimeError):
    """The previous program produced output this script does not know how to store."""


# --------------------------------------------------------------------------------------
# Tagged legacy strings
# --------------------------------------------------------------------------------------


class Tagged(str):
    """A string shown by the previous program, tagged with the number behind it."""

    kind: str
    unrounded: float | None
    numerator: int | None
    denominator: int | None

    def __new__(
        cls,
        text: str,
        *,
        kind: str,
        unrounded: float | None,
        numerator: int | None = None,
        denominator: int | None = None,
    ) -> Tagged:
        obj = super().__new__(cls, text)
        obj.kind = kind
        obj.unrounded = unrounded
        obj.numerator = numerator
        obj.denominator = denominator
        return obj


def parse_display(text: str) -> tuple[int | float | None, int | None]:
    """Parse a legacy number string into ``(value, decimals shown)``.

    ``"34%"`` gives ``(34, 0)``, ``"2.35"`` gives ``(2.35, 2)``; the texts shown for
    an undefined statistic give ``(None, None)``.
    """
    stripped = text.strip().removesuffix("%")
    if stripped in UNDEFINED_TEXTS:
        return None, None
    try:
        number = Decimal(stripped)
    except InvalidOperation as exc:
        raise BaselineError("unexpected number format in the legacy output") from exc
    if not number.is_finite():
        return None, None
    exponent = number.as_tuple().exponent
    assert isinstance(exponent, int)
    decimals = max(0, -exponent)
    return (int(number) if decimals == 0 else float(number)), decimals


def _finite(value: float | None) -> float | None:
    if value is None or value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


# --------------------------------------------------------------------------------------
# Entries
# --------------------------------------------------------------------------------------


def count_entry(value: object) -> dict[str, Any]:
    number = int(value)  # type: ignore[call-overload]
    if number != value:
        raise BaselineError("a count is not an integer")
    return {"kind": KIND_COUNT, "value": number}


def statistic_entry(value: float) -> dict[str, Any]:
    """A number the previous program did not show as text (e.g. a box plot line)."""
    return {
        "kind": KIND_STATISTIC,
        "value": _finite(value),
        "decimals": None,
        "unrounded": None,
    }


def tagged_entry(tagged: Tagged) -> dict[str, Any]:
    value, decimals = parse_display(tagged)
    entry: dict[str, Any] = {
        "kind": tagged.kind,
        "value": value,
        "decimals": decimals,
        "unrounded": _finite(tagged.unrounded),
    }
    if tagged.kind == KIND_PERCENT:
        entry["numerator"] = tagged.numerator
        entry["denominator"] = tagged.denominator
    return entry


def flatten_context(
    context: Mapping[str, Any], prefix: str = ""
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(dotted key, entry)`` for every number in a legacy chapter context.

    ``None`` leaves are image placeholders and skipped; keys in ``EXCLUDED_KEYS`` are
    skipped. Any other leaf that is not a count or a tagged string is an error, so a
    change in the previous program cannot slip text into the baseline.
    """
    for name, value in context.items():
        key = f"{prefix}{name}"
        if key in EXCLUDED_KEYS or value is None:
            continue
        if isinstance(value, Mapping):
            yield from flatten_context(value, f"{key}.")
        elif isinstance(value, Tagged):
            yield key, tagged_entry(value)
        elif isinstance(value, bool) or not _is_integer(value):
            raise BaselineError(f"unexpected {type(value).__name__} at {key}")
        else:
            yield key, count_entry(value)


def _is_integer(value: object) -> bool:
    try:
        return int(value) == value  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return False


def apply_aliases(key: str) -> str:
    """Replace the instrument segment of an aliased chapter by its alias."""
    segments = key.split(".")
    alias = ALIASED_SEGMENTS.get(segments[0])
    if alias is not None and len(segments) > 1:
        segments[1] = alias
    return ".".join(segments)


# --------------------------------------------------------------------------------------
# Capturing local variables of legacy functions
# --------------------------------------------------------------------------------------


def call_capturing_locals(
    func: Callable[..., Any], *args: object, **kwargs: object
) -> tuple[Any, dict[str, Any]]:
    """Call ``func`` and return its result and its local variables at return."""
    code = func.__code__
    captured: dict[str, Any] = {}
    previous = sys.getprofile()

    def profile(frame: FrameType, event: str, _arg: object) -> None:
        if event == "return" and frame.f_code is code:
            captured.clear()
            captured.update(frame.f_locals)

    sys.setprofile(profile)
    try:
        result = func(*args, **kwargs)
    finally:
        sys.setprofile(previous)
    return result, captured


@dataclass
class ChartRecorder:
    """Local variables of the chart helpers, per helper name, in call order."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def wrap(
        self, func: Callable[..., Any], keep: tuple[str, ...]
    ) -> Callable[..., Any]:
        def wrapper(*args: object, **kwargs: object) -> object:
            result, local = call_capturing_locals(func, *args, **kwargs)
            self.calls.append(
                (func.__name__, {k: local[k] for k in keep if k in local})
            )
            return result

        return wrapper

    def take(self) -> list[tuple[str, dict[str, Any]]]:
        calls, self.calls = self.calls, []
        return calls


#: Chart helpers and the local variables read from them. Only these names are read;
#: the resilience histogram also receives a reference value from literature, which is
#: deliberately not among them.
CHART_LOCALS: Mapping[str, tuple[str, ...]] = {
    "save_age_bar_chart": ("x_vals", "y_vals"),
    "save_upset_k6_by_size": ("selected", "cols"),
    "save_horizontal_boxplot": ("clean", "bp", "p"),
    "save_stacked_percentage_bar": (),
    "save_scatter_inverted_x": (),
    "_save_resilience_histogram": ("counts", "n"),
}


def chart_entries(
    chapter: str,
    calls: list[tuple[str, dict[str, Any]]],
    chapter_locals: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Numbers shown by a chapter's charts that its context does not hold."""
    for name, local in calls:
        if name == "save_age_bar_chart":
            for age, count in zip(local["x_vals"], local["y_vals"], strict=True):
                yield f"demography.age_chart.count.{int(age)}", count_entry(count)
        elif name == "save_upset_k6_by_size":
            yield from _upset_entries(local["selected"])
        elif name == "save_horizontal_boxplot":
            yield from _boxplot_entries(local, chapter_locals["order"])
        elif name == "_save_resilience_histogram":
            alias = ALIASED_SEGMENTS[chapter]
            yield f"{chapter}.{alias}.hist.n", count_entry(local["n"])
            for score, count in local["counts"].items():
                yield f"{chapter}.{alias}.hist.count.{int(score)}", count_entry(count)


def _upset_entries(
    selected: list[tuple[tuple[str, ...], int]],
) -> Iterator[tuple[str, dict[str, Any]]]:
    # The chart has six columns K1..K6: the two most frequent single, pair and triple
    # patterns, padded with empty patterns. The key names the column and its pattern.
    for position, (combo, count) in enumerate(selected, start=1):
        pattern = "+".join(combo) if combo else "empty"
        yield f"diagnoses.help_upset.K{position}.{pattern}", count_entry(count)


def _boxplot_entries(
    local: dict[str, Any], order: list[str]
) -> Iterator[tuple[str, dict[str, Any]]]:
    group = Path(str(local["p"])).stem.removeprefix("stigma_").removesuffix("_box")
    bp = local["bp"]
    for index, item in enumerate(order):
        prefix = f"stigma.{group}.chart.box.{item}"
        # Horizontal box plot: x data. Whiskers come in pairs (low, high) per box,
        # each drawn from the quartile to the whisker end.
        q1, whislo = bp["whiskers"][2 * index].get_xdata()
        q3, whishi = bp["whiskers"][2 * index + 1].get_xdata()
        median = bp["medians"][index].get_xdata()[0]
        yield f"{prefix}.n", count_entry(len(local["clean"][index]))
        for stat, value in (
            ("median", median),
            ("q1", q1),
            ("q3", q3),
            ("whislo", whislo),
            ("whishi", whishi),
        ):
            yield f"{prefix}.{stat}", statistic_entry(float(value))


# --------------------------------------------------------------------------------------
# Patching the imported legacy modules
# --------------------------------------------------------------------------------------


def _tagging_pct(original: Callable[..., str]) -> Callable[..., str]:
    def pct(n: int, total: int, *, digits: int = 0, with_sign: bool = True) -> str:
        text = original(n, total, digits=digits, with_sign=with_sign)
        exact = Fraction(int(n), int(total)) * 100 if total else None
        return Tagged(
            text,
            kind=KIND_PERCENT,
            unrounded=None if exact is None else float(exact),
            numerator=int(n),
            denominator=int(total),
        )

    return pct


def _tagging_mean_sd(original: Callable[..., dict[str, Any]]) -> Callable[..., Any]:
    def mean_sd(series: object) -> dict[str, Any]:
        result, local = call_capturing_locals(original, series)
        if "mean" in local:  # the helper kept the unrounded numbers
            mean, sd = local["mean"], local["sd"]
        elif not local["s"].empty:  # the helper formats exactly these expressions
            mean, sd = local["s"].mean(), local["s"].std(ddof=1)
        else:
            mean = sd = None
        tagged = dict(result)
        for name, value in (("mean", mean), ("sd", sd)):
            unrounded = None if value is None else _finite(float(value))
            tagged[name] = Tagged(
                result[name], kind=KIND_STATISTIC, unrounded=unrounded
            )
        return tagged

    return mean_sd


def _replace_everywhere(
    modules: list[ModuleType], original: object, replacement: object
) -> None:
    for module in modules:
        for name, value in list(vars(module).items()):
            if value is original:
                setattr(module, name, replacement)


@dataclass(frozen=True)
class Legacy:
    """The imported, patched previous program."""

    load: Callable[[str], Any]
    report_data: Any
    chapters: Mapping[str, ModuleType]
    recorder: ChartRecorder


def import_legacy(legacy_dir: Path) -> Legacy:
    os.environ.setdefault("MPLBACKEND", "Agg")
    # Read-only: no __pycache__ may be written into the previous program's checkout.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(legacy_dir))
    ls_io = importlib.import_module("src.ls_io")
    report_data = importlib.import_module("src.core.report_data")
    formatting = importlib.import_module("src.core.formatting")
    plot_utils = importlib.import_module("src.plot_utils")
    chapters = {c: importlib.import_module(f"src.chapters.{c}") for c in CHAPTERS}
    modules = [formatting, plot_utils, *chapters.values()]

    _replace_everywhere(modules, formatting.pct, _tagging_pct(formatting.pct))
    for chapter in ("burnout", "stigma", "resilience"):
        module = chapters[chapter]
        module._mean_sd = _tagging_mean_sd(module._mean_sd)  # type: ignore[attr-defined]

    recorder = ChartRecorder()
    for name, keep in CHART_LOCALS.items():
        if name == "_save_resilience_histogram":
            module = chapters["resilience"]
            module._save_resilience_histogram = recorder.wrap(  # type: ignore[attr-defined]
                module._save_resilience_histogram,  # type: ignore[attr-defined]
                keep,
            )
        else:
            original = getattr(plot_utils, name)
            _replace_everywhere(modules, original, recorder.wrap(original, keep))

    return Legacy(
        load=ls_io.load_limesurvey_excel,
        report_data=report_data.ReportData,
        chapters=chapters,
        recorder=recorder,
    )


# --------------------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------------------


def baseline_values(legacy: Legacy, xlsx: Path) -> dict[str, dict[str, Any]]:
    """All stored numbers of one fixture, by dotted key."""
    rd = legacy.report_data.from_raw(legacy.load(str(xlsx)))
    values: dict[str, dict[str, Any]] = {}
    for chapter, module in legacy.chapters.items():
        legacy.recorder.take()
        part, local = call_capturing_locals(module.build_context, rd)
        for key, entry in (
            *flatten_context(part["context"]),
            *chart_entries(chapter, legacy.recorder.take(), local),
        ):
            stored = apply_aliases(key)
            if stored in values:
                raise BaselineError(f"duplicate key {stored}")
            values[stored] = entry
    _check_aliases(values)
    return values


def _check_aliases(values: Mapping[str, Any]) -> None:
    for top, alias in ALIASED_SEGMENTS.items():
        seconds = {k.split(".")[1] for k in values if k.split(".")[0] == top}
        if seconds != {alias}:
            raise BaselineError(f"chapter {top} has segments other than its alias")


def legacy_commit(legacy_dir: Path) -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(legacy_dir), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    try:
        sha = git("rev-parse", "--short", "HEAD")
        dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha} (uncommitted changes)" if dirty else sha


def environment_versions() -> str:
    versions = [f"Python {platform.python_version()}"]
    for package in ("pandas", "numpy", "matplotlib", "openpyxl"):
        module = importlib.import_module(package)
        versions.append(f"{package} {module.__version__}")
    return ", ".join(versions)


def header(dataset: str, source: str, commit: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset": dataset,
        "source": source,
        "generated_by": f"previous program, commit {commit}",
        "generator": "tools/legacy_baseline.py",
        "environment": environment_versions(),
        "rounding": {
            "percent": (
                "value: percentage of numerator/denominator rounded half-up "
                "(decimal.Decimal) to `decimals`; unrounded: exact percentage"
            ),
            "statistic": (
                "value: Python format() to `decimals` (round half to even on the "
                "binary float); unrounded: the float the previous program formatted; "
                "decimals null: not shown as text, value unrounded"
            ),
            "count": "exact integer",
        },
        "excluded": dict(sorted(EXCLUDED_KEYS.items())),
    }


def render(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@contextlib.contextmanager
def scratch_working_directory() -> Iterator[None]:
    """Run in a temporary directory: the previous program writes charts to ./out."""
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="legacy-baseline-") as tmp:
        os.chdir(tmp)
        try:
            yield
        finally:
            os.chdir(previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "legacy_dir", type=Path, help="checkout of the previous program"
    )
    parser.add_argument("output_dir", type=Path, help="usually tests/fixtures/expected")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument(
        "--check", action="store_true", help="compare instead of writing"
    )
    args = parser.parse_args(argv)

    legacy_dir = args.legacy_dir.resolve()
    output_dir = args.output_dir.resolve()
    fixtures = sorted(args.fixtures.resolve().glob("*.xlsx"))
    commit = legacy_commit(legacy_dir)
    legacy = import_legacy(legacy_dir)

    outdated = []
    for xlsx in fixtures:
        with scratch_working_directory():
            values = baseline_values(legacy, xlsx)
        document = {
            "header": header(xlsx.stem, xlsx.name, commit),
            "values": values,
        }
        target = output_dir / f"{xlsx.stem}.json"
        text = render(document)
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != text:
                outdated.append(target.name)
            continue
        output_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"{target.name}: {len(values)} values")

    if outdated:
        print(f"Out of date: {', '.join(outdated)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
