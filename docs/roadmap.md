# Roadmap

Milestones are worked on in order. Each item below is meant to become one GitHub issue
and one pull request. Acceptance criteria are the definition of done.

Legend: **[M]** = milestone, **#n** = suggested issue number.

---

## [M0] Foundation

### #1 Repository skeleton
- `pyproject.toml` (uv, Python 3.12, package `spot_report` under `src/`, console script
  `spot-report`), `README.md`, `LICENSE` (AGPL-3.0), `CLAUDE.md`, `docs/`.
- **Done when:** `uv sync` works on a fresh clone; `uv run spot-report --help` prints
  usage.

### #2 Ignore rules and data guard
- `.gitignore` covering `content/`, `out/`, `data/`, `*.sqlite`, `.venv/`,
  `CLAUDE.local.md`, and data files (`*.xlsx`, `*.xls`, `*.csv`, `*.json` outside
  allowed folders).
- pre-commit hook that rejects data files outside `tests/fixtures/` and
  `examples/content-demo/`, plus a check that no name from a local denylist
  (untracked file, so the names themselves are never committed) appears in tracked
  files.
- **Done when:** committing a dummy `.xlsx` in `src/` is rejected; committing a fixture
  in `tests/fixtures/` is allowed.

### #3 Lint, format and tests
- ruff (lint + format) and pytest configured in `pyproject.toml`; one trivial test.
- **Done when:** `uv run ruff check .` and `uv run pytest` pass.

### #4 Continuous integration
- GitHub Actions workflow: install uv and Pango, run ruff and pytest on every push and
  pull request.
- **Done when:** a pull request shows green checks.

### #5 Contribution basics
- Issue templates (bug, feature), pull request template with checklist (tests, docs,
  privacy rules), `CONTRIBUTING.md` summarising the conventions from `CLAUDE.md`.
- **Done when:** templates appear when opening an issue or pull request.

---

## [M1] Ingest and validation

### #6 Synthetic fixtures
- Add a selection of the existing synthetic datasets to `tests/fixtures/` (code headings
  and answer codes only; check that no question texts are contained).
- `tests/fixtures/README.md` describes each dataset and what it is meant to test.
- **Done when:** fixtures are committed and a test loads each of them.

### #7 Questionnaire spec
- `questionnaire.yaml`: for every item its column code, answer codes, scale range and
  which score it belongs to; versioned (`2026.1`). No item texts.
- `spec.py` gives typed access (e.g. `spec.scale("PHQ9").columns`).
- **Done when:** all column codes used by the previous program are covered; a test
  checks the spec against every fixture.

### #8 Manifest and readers
- Manifest model (schema version 1, see architecture §3) with validation.
- Readers for LimeSurvey CSV (`code`/`short`) and XLSX, both returning the same
  normalised DataFrame (string codes stripped, numeric scales as numbers, empty → NA).
- **Done when:** the same dataset as CSV and XLSX produces identical DataFrames in a
  test.

### #9 Validation
- Checks: required columns present, answer codes within the allowed set, numeric values
  within range, duplicate response ids. Returns structured findings (error / warning).
- `spot-report validate <bundle>` prints the findings and sets the exit code.
- **Done when:** a fixture with injected errors produces the expected findings.

---

## [M2] Metrics

### #10 Metric types and registry
- `Proportion`, `Summary`, `Distribution` (architecture §6.1), JSON round trip,
  `MetricSet`, registry with metadata per metric id.
- **Done when:** round-trip tests pass for every type.

### #11 Derived features
- Per-person table: PHQ-9 and GAD-7 sum scores and severity buckets, cut-off flags,
  "burdened" flag, diagnosis yes/no, any treatment, RES sum score, burnout subscale
  sums. Missing-data rules documented in docstrings.
- **Done when:** unit tests cover edge cases (all items missing, some items missing).

### #12 Legacy parity baseline
- Run the previous program locally on every fixture and store its numbers as
  `tests/fixtures/expected/<dataset>.json` (numbers only).
- **Done when:** the expected files exist and a helper loads them in tests.

### #13 – #20 Domain metrics (one issue each)
- #13 demography · #14 diagnoses, help sources and treatment (incl. pattern counts for
  the help-source chart) · #15 absences · #16 symptoms (PHQ-9, GAD-7, combined,
  item 9, impairment) · #17 association (symptoms × diagnosis, by school level) ·
  #18 stigma · #19 burnout · #20 resilience (RES)
- **Done when (each):** unit tests pass and the legacy parity test for that domain
  passes, or every deviation is documented as an intentional fix in the pull request.

---

## [M3] Snapshot store

### #21 SQLite store
- Schema from architecture §6.4, `save_snapshot`, `load_snapshot`,
  `list_waves(school)`, upsert behaviour, schema version table for future migrations.
- **Done when:** save → load round trip is lossless; running twice for the same wave
  keeps one snapshot.

### #22 Snapshot CLI
- `spot-report snapshot list` and `spot-report snapshot export`.
- **Done when:** export of a stored fixture snapshot produces readable JSON.

---

## [M4] Presentation and rendering foundation

### #23 Design tokens and CSS design system
- `templates/design.toml`, base CSS (typography, colours, tables, figures), `@page`
  rules (A4, margins, page numbers, running header), bundled open-licence font.
- **Done when:** a test page with all elements renders to PDF and looks consistent.

### #24 Jinja environment, filters and macros
- Loader with content-pack-first lookup, filters (`pct`, `number`, `delta`), macros
  (table, figure with automatic numbering, key-figure box, stacked percentage bar).
- **Done when:** filters have unit tests; macros render in the test page.

### #25 Privacy layer
- `present/privacy.py` with `min_group_size` from config; suppressed values render as a
  defined placeholder with a footnote; report generation stops below the threshold for
  the whole school.
- **Done when:** tests cover suppressed and non-suppressed cases.

### #26 Chart style and first charts
- Shared matplotlib style from design tokens, SVG export; port the age bar chart and the
  PHQ-9 severity chart.
- **Done when:** charts render inside the test page with matching fonts and colours.

### #27 PDF pipeline and demo content pack
- `render/pdf.py`, `examples/content-demo/` with one placeholder section,
  `spot-report build` end to end.
- **Done when:** CI renders the demo report from a fixture without warnings.

---

## [M5] Initial report

### #28 Report definition and structure
- `reports/initial.py`: section list, title page, table of contents, methods section.

### #29 – #36 Sections (one issue each, same order as M2)
- Each section: content-pack template, context building, charts, demo placeholder.
- **Done when (each):** the section renders with real content locally and with
  placeholder content in CI.

### #37 Design pass
- Review of the complete report: spacing, page breaks, table and figure placement.
- **Done when:** the report has been reviewed against the previous Word report and
  approved.

---

## [M6] Appendices

### #38 Free-text appendix
- Separate PDF with the free-text answers (cleaned, ordered), clear header that it
  contains unedited student statements.

### #39 References appendix
- Generated from `references.yaml` in the content pack; reference values used in the
  report are cited automatically.

---

## [M7] Production on the server

### #40 Input bundle contract with the cron script
- Final manifest fields; adapt the existing cron script to write bundles and call
  `spot-report build`; exit codes handled.

### #41 Server installation
- Installation guide (uv, Pango, fonts), configuration via environment variables, log
  location, store location, backup of the SQLite file.
- **Done when:** a report for a test survey is produced on the server by the cron job.

---

## [M8] Follow-up report

Starts once the content of the follow-up report has been defined with SPOT.

### #42 Content definition (document, not code)
- Which comparisons, which wording, how to handle new or changed questions.

### #43 Comparison engine
- `compare/`: differences between waves for every comparable metric, statistical
  assessment (method decided in an ADR), handling of missing metrics.

### #44 Follow-up report definition and sections
- `reports/followup.py` and content-pack templates.

---

## Later

- AI summary of free-text answers (requires privacy assessment first).
- `recompute` command for archived input bundles.
- Trend charts over three or more waves.
- Dashboard (separate project) reading the SQLite store.
