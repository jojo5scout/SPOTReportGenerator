# SPOT-SchoolReportGenerator

Command-line tool that turns the survey responses of one school and one survey wave
into a PDF report for the school leadership (initial report or follow-up report).
Pipeline: ingest → validate → features → metrics → store → compare → present → render
(Jinja2 + WeasyPrint).

Read `docs/architecture.md` before any change that touches more than one module, and
`docs/roadmap.md` to see where the current task fits.

## Hard rules

These protect real people and third-party instruments. Never break them, even if a task seems to
require it; stop and ask instead.

- **No real survey data in the repository.** Only synthetic datasets in
  `tests/fixtures/`. Never copy files from `content/`, `out/`, `data/` or any path
  outside the repository into tracked files.
- **No item texts of any questionnaire** in tracked files. `questionnaire.yaml` holds
  codes and scoring rules only. Labels and texts belong in the content pack.
- **Some instruments are referred to only by neutral aliases** (e.g. `RES` for the
  resilience scale) everywhere in tracked files (code, comments, tests, docs, commit
  messages). The mapping to real names is in `CLAUDE.local.md`. Never write the real
  name, abbreviation, items or published reference values of an aliased instrument.
- **No secrets** (passwords, tokens, server paths) in tracked files.
- **Never log response values or free-text answers.** Counts and column names are fine.
- **Small groups are suppressed** only through `present/privacy.py`. Never show a
  figure in a template without going through it.

## Code conventions

- Python 3.12, type hints everywhere, `from __future__ import annotations`.
- Code, comments, docstrings, docs and commit messages in **English**. Text that ends up
  in a report is German and lives in the content pack.
- Metrics return numbers (`Proportion`, `Summary`, `Distribution`, …), never formatted
  strings. No file I/O and no plotting inside `metrics/`.
- Formatting happens only in Jinja filters (`present/formatting.py`). Charts happen only
  in `present/charts/`.
- Column codes are never hard-coded in metric modules; get them from the questionnaire
  spec.
- Prefer small pure functions and frozen dataclasses. No global state.
- Metric ids are a public contract (stored in SQLite). Do not rename them without a
  migration and a note in the pull request.

## Commands

```bash
uv sync                          # install dependencies
uv run pytest                    # all tests
uv run pytest tests/metrics -q   # one area
uv run ruff check . --fix        # lint
uv run ruff format .             # format
uv run spot-report build --responses tests/fixtures/<file> \
    --school demo --wave 2026 --questionnaire-version 2026.1 \
    --content-dir examples/content-demo   # render a demo report
```

WeasyPrint needs system libraries (Pango). On Ubuntu:
`sudo apt install libpango-1.0-0 libpangoft2-1.0-0`.

## Workflow

- One GitHub issue per branch, branch name `<type>/<issue-number>-<slug>`,
  e.g. `feat/12-symptom-metrics`.
- Plan before coding when a task touches more than one module, and show the plan.
- Every new metric gets a unit test with a hand-made DataFrame and, where the previous
  program computed the same number, a legacy parity check against
  `tests/fixtures/expected/`.
- Run `uv run ruff check .` and `uv run pytest` before every commit. Do not commit with
  failing tests.
- Commit messages follow Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`,
  `refactor:`, `chore:`, `ci:`. Imperative mood, subject ≤ 72 characters, body explains
  why when it is not obvious. Reference the issue (`Refs #12` / `Closes #12`).
- Keep pull requests small and focused on one issue.
- When a change affects the architecture, update `docs/architecture.md` in the same pull
  request. Significant decisions get a short ADR in `docs/decisions/`.
- If a statistical or privacy question is ambiguous, ask instead of guessing.

## Local context

Machine-specific notes (location of the previous program used as a read-only reference,
location of the private content pack) are in `CLAUDE.local.md`, which is gitignored.
