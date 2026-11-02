# SPOTReportGenerator

Command-line tool that turns the survey responses of one school and one survey wave
into a PDF report for the school leadership (initial report or follow-up report).
Pipeline: ingest → validate → features → metrics → store → compare → present → render
(Jinja2 + WeasyPrint).

Read `docs/architecture.md` before any change that touches more than one module, and
`docs/roadmap.md` to see where the current task fits.

## Hard rules

These protect real people and third-party instruments. Never break them, even if a task
seems to require it; stop and ask instead.

- **No real survey data in the repository.** Only synthetic datasets in
  `tests/fixtures/`. Never copy files from `content/`, `out/`, `data/`, the archive or
  any path outside the repository into tracked files. Single exception: synthetic
  datasets from the folder named in `CLAUDE.local.md` may be copied into
  `tests/fixtures/` after checking that they contain codes only.
- **No item texts of any questionnaire** in tracked files. Questionnaire specs hold
  codes and scoring rules only. Labels and texts belong in the content pack.
- **Some instruments are referred to only by neutral aliases** (`RES`, `STIG`)
  everywhere in tracked files (code, comments, tests, docs, commit messages). The
  mapping to real names is in `CLAUDE.local.md`; the forbidden terms are in the
  untracked `.denylist.txt`, which the pre-commit hooks check. Never write the real name,
  abbreviation, items or published reference values of an aliased instrument. PHQ-9,
  GAD-7 and the School Burnout Inventory (SBI) may be named normally.
- **No secrets** (passwords, tokens, server paths) in tracked files.
- **Never log response values or free-text answers**, also not in validation messages.
  Counts and column codes are fine.
- **Privacy rules are fixed.** They match the previous report, which was reviewed by the
  responsible authority. Implement them as specified in `docs/architecture.md` §9, only
  through `present/privacy.py`. Do not add, remove or propose additional suppression
  rules.

## Code conventions

- Python 3.12, type hints everywhere, `from __future__ import annotations`.
- Code, comments, docstrings, docs and commit messages in **English**. Text that ends up
  in a report is German and lives in the content pack.
- Metrics return numbers (`Proportion`, `Summary`, `Distribution`, …), never formatted
  strings. No file I/O and no plotting inside `metrics/` or `features.py`.
- All number formatting goes through `present/formatting.py`. Charts happen only in
  `present/charts/` and use `matplotlib.rc_context`, never global style changes.
- Fixed computation conventions: SD with `ddof=1`, quantiles with the NumPy/pandas
  default, half-up rounding via `decimal.Decimal`.
- Column codes are never hard-coded in metric modules; get them from the questionnaire
  spec.
- Prefer small pure functions and frozen dataclasses. No global state.
- Metric ids follow `domain.instrument.measure[.subgroup]` and are a stored contract.
  Do not rename them without a migration and a note in the pull request.

## Commands

```bash
uv sync                          # install dependencies
uv run pre-commit install        # git hooks: data guard, name check
uv run pytest                    # all tests
uv run pytest tests/metrics -q   # one area
uv run ruff check . --fix        # lint
uv run ruff format .             # format
uv run spot-report build --responses tests/fixtures/<file> \
    --school demo --wave 2026 --fieldwork-end 2026-05-15 \
    --questionnaire-version 2026.1 \
    --content-dir examples/content-demo   # render a demo report
```

WeasyPrint needs system libraries (Pango). On Ubuntu:
`sudo apt install libpango-1.0-0 libpangoft2-1.0-0`.

## Workflow

- Tasks are identified by roadmap ids (`R01`, `R02`, …) in `docs/roadmap.md`. GitHub
  issue numbers differ; every issue title starts with its roadmap id.
- Branch name `<type>/<roadmap-id>-<slug>`, e.g. `feat/r16-symptom-metrics`.
- Plan before coding when a task touches more than one module, and show the plan.
- Every new metric gets a unit test with a hand-made DataFrame and, where the previous
  program computed the same number, a legacy parity check against
  `tests/fixtures/expected/`.
- Run `uv run ruff check .` and `uv run pytest` before every commit. Do not commit with
  failing tests.
- Commit messages follow Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`,
  `refactor:`, `chore:`, `ci:`. Imperative mood, subject ≤ 72 characters, body explains
  why when it is not obvious. Reference the issue (`Refs #12` / `Closes #12`).
- Keep pull requests small and focused on one task.
- When a change affects the architecture, update `docs/architecture.md` in the same pull
  request. Significant decisions get a short ADR in `docs/decisions/`.
- If a statistical question is ambiguous, ask instead of guessing.

## Local context

Machine-specific notes (location of the previous program used as a read-only reference,
synthetic datasets, private content pack, instrument alias mapping) are in
`CLAUDE.local.md`, which is gitignored.
