# Contributing

Thanks for helping with SPOTReportGenerator. The program produces reports on the mental
health of minors from anonymous survey data, so a few rules are stricter than in most
projects. Please read [docs/architecture.md](docs/architecture.md) before changes that
touch more than one module, and [docs/roadmap.md](docs/roadmap.md) to see where a task
fits.

## Setup

```bash
uv sync                    # Python 3.12 and all dependencies
uv run pre-commit install  # data guard and name check hooks
uv run pytest
```

PDF rendering needs Pango (Ubuntu: `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`).
The name check hooks need a local, untracked `.denylist.txt`; ask a maintainer for its
contents. Commits fail while it is missing.

## Hard rules

These protect real people and third-party instruments. If a task seems to require
breaking one, stop and ask in the issue.

- **No real survey data in the repository.** Only synthetic datasets with code headings
  in `tests/fixtures/`. The data guard rejects data files elsewhere, locally and in CI.
- **No item texts of any questionnaire.** Questionnaire specs hold codes and scoring
  rules only; labels and texts belong in the private content pack.
- **Aliased instruments** are referred to only as `RES` and `STIG`, everywhere: code,
  comments, tests, docs, issues, commit messages. Never write their real names,
  abbreviations, items or published reference values. PHQ-9, GAD-7 and the School
  Burnout Inventory (SBI) may be named normally.
- **No secrets**: passwords, tokens and server paths stay out of tracked files.
- **Never log response values or free-text answers**, not even in validation messages.
  Counts and column codes are fine.
- **Privacy rules are fixed** (architecture §9). They match a report reviewed by the
  responsible authority and are implemented only in `present/privacy.py`. Do not add,
  remove or propose suppression rules.

## Code conventions

- Python 3.12, type hints everywhere, `from __future__ import annotations` (enforced
  by ruff).
- Code, comments, docstrings, docs and commit messages in English. Report text is
  German and lives in the content pack.
- Metrics return numbers (`Proportion`, `Summary`, `Distribution`, …), never formatted
  strings. No file I/O and no plotting in `metrics/` or `features.py`.
- Number formatting only in `present/formatting.py`; charts only in `present/charts/`,
  using `matplotlib.rc_context`, never global style changes.
- Computation conventions: SD with `ddof=1`, NumPy/pandas default quantiles, half-up
  rounding via `decimal.Decimal`.
- Column codes come from the questionnaire spec, never hard-coded in metric modules.
- Small pure functions and frozen dataclasses; no global state.
- Metric ids follow `domain.instrument.measure[.subgroup]` and are a stored contract.
  Renaming one needs a migration and a note in the pull request.
- If a statistical question is ambiguous, ask instead of guessing.

## Tests

- Every new metric gets a unit test with a small hand-made DataFrame and, where the
  previous program computed the same number, a legacy parity check against
  `tests/fixtures/expected/`.
- Before every commit:

  ```bash
  uv run ruff check .
  uv run ruff format --check .
  uv run pytest
  ```

  CI runs the same checks and the data guard on every pull request.

## Workflow

- Tasks have roadmap ids (`R01`, `R02`, …). Issue titles start with the roadmap id;
  GitHub issue numbers are independent of it.
- Branch name `<type>/<roadmap-id>-<slug>`, e.g. `feat/r16-absence-metrics`.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`): imperative mood,
  subject at most 72 characters, a body that explains why when it is not obvious, and
  a reference to the issue (`Refs #12`, `Closes #12`).
- Plan before coding when a task touches more than one module, and share the plan in
  the issue.
- Keep pull requests small and focused on one task. The pull request template contains
  the checklist for tests, docs and the hard rules.
- Architecture changes update `docs/architecture.md` in the same pull request.
  Significant decisions get a short ADR in `docs/decisions/`.
