# Roadmap

Milestones are worked on in order. Each task has a roadmap id (`R01`, `R02`, …). When a
task becomes a GitHub issue, the issue title starts with its roadmap id; GitHub's own
issue numbers are independent of these ids. Acceptance criteria are the definition of
done. Ids are never renumbered: a task added later gets the next free id and is placed
where it belongs, so ids are not always in reading order.

---

## M0 Foundation

### R01 Repository skeleton
- `pyproject.toml` (uv, Python 3.12, package `spot_report` under `src/`, console script
  `spot-report`), `README.md`, `LICENSE` (AGPL-3.0).
- **Done when:** `uv sync` works on a fresh clone; `uv run spot-report --help` prints
  usage.

### R02 Ignore rules and data guard
- Extend `.gitignore` (archive directory, SQLite files). JSON files are **not** ignored
  globally, because fixtures and manifests are legitimate JSON.
- Data guard script: rejects data files (`*.xlsx`, `*.xls`, `*.csv`, `*.sqlite`, …)
  outside `tests/fixtures/` and `examples/content-demo/`. Runs as a pre-commit hook.
- Name check (pre-commit only): rejects tracked files containing a name from a local,
  untracked denylist, so the names themselves are never committed.
- **Done when:** committing a dummy `.xlsx` in `src/` is rejected; committing a fixture
  in `tests/fixtures/` is allowed; a denylisted word in a file is rejected.

### R03 Lint, format and tests
- ruff (lint + format) and pytest configured in `pyproject.toml`; one trivial test.
- **Done when:** `uv run ruff check .` and `uv run pytest` pass.

### R04 Continuous integration
- GitHub Actions workflow: install uv and Pango, run ruff, the data guard (without the
  local name check) and pytest on every push and pull request.
- **Done when:** a pull request shows green checks; a pull request adding a data file
  in `src/` fails.

### R05 Contribution basics
- Issue templates (bug, feature), pull request template with checklist (tests, docs,
  hard rules), `CONTRIBUTING.md` summarising the conventions from `CLAUDE.md`.
- **Done when:** templates appear when opening an issue or pull request.

---

## M1 Ingest and validation

### R06 Synthetic fixtures
- Add a selection of the existing synthetic datasets (path in `CLAUDE.local.md`) to
  `tests/fixtures/`. Check that headings are question codes and that no question or
  answer texts are contained.
- `tests/fixtures/README.md` describes each dataset and what it is meant to test.
- **Done when:** fixtures are committed and a test loads each of them.

### R07 Questionnaire spec
- `questionnaire/specs/2026.1.yaml`: for every item its column code, answer codes,
  scale range and the score it belongs to, and which columns are multi-select options
  (empty = not selected, architecture D12). No item texts. Display conditions are not
  modelled.
- `spec.py` loads a spec by version and gives typed access
  (e.g. `spec.scale("PHQ9").columns`).
- **Done when:** all column codes used by the previous program are covered; a test
  checks the spec against every fixture.

### R08 Manifest and readers
- Manifest model (schema version 1, architecture §3) with validation; `fieldwork_end`
  required; optional `responses.counts`.
- Readers for LimeSurvey CSV (`code`/`short`) and XLSX, both returning the same
  normalised DataFrame (codes stripped, numeric scales as numbers, empty → NA).
- The CSV format (delimiter, encoding, BOM, heading format) is taken from the CSV
  exports with dummy answers in the synthetic data folder named in `CLAUDE.local.md`.
  They are used only to read off the format: neither the files nor their headings are
  copied into the repository. CSV test fixtures are generated from the XLSX fixtures in
  that format.
- **Done when:** the same dataset as CSV and XLSX produces identical DataFrames.

### R09 Validation
- Structural checks only: required columns present, answer codes within the allowed set
  (including numeric values within range), duplicate response ids, file readable in the
  expected format. Findings contain column code, rule and count, never response values
  or row contents.
- Empty cells are never a finding, neither error nor warning, including a column that
  is empty for every respondent (architecture D12).
- `spot-report validate <bundle>` prints the findings; exit code 3 on errors.
- **Done when:** a fixture with injected errors produces the expected findings; a
  fixture with empty cells, including a column empty for every respondent, produces no
  findings.

### R10 Bundle archive
- Successful runs copy the bundle to `SPOT_ARCHIVE_DIR/<school>/<wave>/<seq>/`. An
  existing copy is never overwritten; a new bundle for the same school and wave gets the
  next sequence number (architecture D13).
- **Done when:** a test run produces the archive copy; a second run for the same school
  and wave adds `002/` and leaves `001/` unchanged; nothing is written inside the
  repository.

---

## M2 Metrics

### R11 Metric types and registry
- `Proportion`, `Summary`, `Distribution` with `n_missing` (architecture §6.1), JSON
  round trip, `MetricSet`, registry with metadata per id, id pattern validation.
- Fixed conventions: SD `ddof=1`, NumPy/pandas default quantiles.
- **Done when:** round-trip tests pass for every type; invalid ids are rejected.

### R12 Derived features
- `features.py`: PHQ-9 and GAD-7 sum scores and severity buckets, cut-off flags,
  "burdened" flag, diagnosis yes/no, any treatment, RES sum score, SBI subscale sums.
- Empty cells as in architecture D12, without errors, warnings or log messages:
  - multi-select option empty → not selected; the respondent stays in the denominator;
  - any other question empty → not shown; the respondent is left out of that
    question's denominator;
  - a scale score is computed only if all its items are present, otherwise it is
    missing for that respondent.
- No display conditions are modelled.
- **Done when:** unit tests cover complete responses, a scale with one empty item
  (score missing, no error), an empty multi-select option (counted as not selected) and
  an empty follow-up question (excluded from its denominator).

### R13 Legacy parity baseline
- Run the previous program locally (path in `CLAUDE.local.md`) on every fixture and
  store its data-derived numbers as `tests/fixtures/expected/<dataset>.json`. No
  reference values from literature. Keys that contain the real name of an aliased
  instrument (the previous program uses it in variable names) are renamed to the
  alias.
- **Done when:** the expected files exist and a helper loads them in tests.

### R14 – R21 Domain metrics (one task each)
- R14 demography · R15 diagnoses, help sources and treatment (incl. pattern counts for
  the help-source chart) · R16 absences · R17 symptoms (PHQ-9, GAD-7, combined, item 9,
  impairment) · R18 association (symptoms × diagnosis, by school level) · R19 stigma
  (STIG) · R20 burnout (SBI) · R21 resilience (RES)
- **Done when (each):** unit tests pass and the legacy parity test for that domain
  passes, or every deviation is documented as an intentional fix in the pull request.

---

## M3 Snapshot store

### R22 SQLite store
- Schema from architecture §6.4, `save_snapshot`, `load_snapshot`,
  `list_waves(school)` ordered by `fieldwork_end`, upsert behaviour, schema version table
  for future migrations.
- **Done when:** save → load round trip is lossless; running twice for the same wave
  keeps one snapshot; wave order is by `fieldwork_end`.

### R23 Snapshot CLI
- `spot-report snapshot list` and `spot-report snapshot export`.
- **Done when:** export of a stored fixture snapshot produces readable JSON.

---

## M4 Presentation and rendering foundation

### R24 Design tokens and CSS design system
- `templates/design.toml`, base CSS (typography, colours, tables, figures), `@page`
  rules (A4, margins, page numbers, running header), bundled open-licence font.
- **Done when:** a test page with headings, body text, a table, a figure and a
  key-figure box renders without WeasyPrint warnings; fonts are embedded in the PDF;
  Johannes has approved the test page in the pull request.

### R25 Formatting, Jinja environment and macros
- `present/formatting.py` (shared by filters and charts; configurable decimal separator,
  half-up rounding via `Decimal`), Jinja loader with content-pack-first lookup, filters
  (`pct`, `number`, `delta`), macros (table, figure with automatic numbering, key-figure
  box, stacked percentage bar).
- **Done when:** formatting functions have unit tests including rounding edge cases
  (`0.5`, `2.5`); macros render in the test page.

### R26 Privacy layer
- `present/privacy.py` implementing exactly the rules of architecture §9: minimum group
  size 10 for subgroups (configuration rejects lower values), no report below 10
  answers for the whole school (exit code 4).
- **Done when:** tests cover shown and hidden subgroups and the whole-school threshold.

### R27 Chart style and first charts
- Shared matplotlib style from design tokens via `rc_context`, SVG export with fixed
  `svg.hashsalt`; port the age bar chart and the PHQ-9 severity chart.
- **Done when:** charts render inside the test page with matching fonts and colours;
  the same input produces byte-identical SVGs.

### R28 PDF pipeline and demo content pack
- `render/pdf.py`, `examples/content-demo/` with one placeholder section,
  `spot-report build` end to end, exit codes and `result.json` as in architecture §11.
- **Done when:** CI renders the demo report from a fixture without warnings.

---

## M5 Initial report

### R29 Report definition and structure
- `reports/initial.py`: section list, title page, table of contents, methods section.

### R51 Content pack from the previous report
- Work happens in the private content pack repository (path in `CLAUDE.local.md`), not
  in this repository. Fill it from the previous Word template and the previous program:
  section templates with the German texts, `labels.yaml`, `references.yaml`, in the
  structure of architecture §8 and the demo content pack.
- Nothing from the content pack is copied into this repository.
- **Done when:** every section of the previous report has its template, labels and
  references in the content pack, and Johannes has reviewed the content pack. Until
  then no report uses it (architecture D15).

### R30 – R37 Sections (one task each, same order as M2)
- Each section: content-pack template, context building, charts, demo placeholder.
  Charts as in the previous report (including the burnout/resilience scatter plot).
- "Real content" is the content pack from R51, used only after Johannes has reviewed it.
- **Done when (each):** the section renders with real content locally and with
  placeholder content in CI.

### R38 Design pass
- Review of the complete report: spacing, page breaks, table and figure placement.
- **Done when:** the report has been compared with the previous Word report and
  approved by Johannes.

---

## M6 References appendix

### R39 References appendix
- Generated from `references.yaml` in the content pack; reference values used in the
  report are cited automatically.
- **Done when:** every reference value shown in the report has an entry in the appendix.

---

## M7 Production on the server

The automation script lives in its own repository (architecture §2.1). Tasks R40–R42
and R52 are carried out there, not in this repository. The old Word-based generator
stays in use until the new report has been approved (R38) and free-text answers reach
SPOT separately (R52).

### R40 Automation script under version control
- Put `spot_automation.py` into its own private repository. Move hard-coded e-mail
  addresses and paths into the existing secrets/env files.
- **Done when:** the script runs unchanged on the server from the repository checkout.

### R41 Survey registry and bundle creation
- `surveys.yaml` registry (architecture §2.2) with a validation on load.
- Export as CSV instead of XLS; write an input bundle with `manifest.json` (school and
  wave from the registry, fieldwork dates from `startdate`/`expires`, counts from
  `get_summary`).
- Expired survey without registry entry: one error e-mail, then skipped silently
  (state flag), no daily repetition.
- **Done when:** for a registered test survey (`TEST_SID`), the script writes a bundle
  that `spot-report validate` accepts.

### R52 Free-text answers for manual review
- The automation script writes the free-text answers of a survey to a separate file
  for manual review by SPOT (architecture D14). The previous report contained them, so
  this must work before the new generator replaces the old one.
- The file never goes to `spot-report`, into a log or into any repository. Its format
  and how it reaches SPOT are decided in this task.
- **Done when:** for a registered test survey (`TEST_SID`), the script produces the
  free-text file next to the bundle and SPOT receives it.

### R42 Calling the new generator
- Depends on R52: the switch to the new generator happens only once free-text answers
  reach SPOT separately.
- Call `spot-report build <bundle> --out <dir>`; read `result.json`.
- Retry only the LimeSurvey export, not the generator; exit codes 3 and 4 are final and
  produce an error e-mail with the message from `result.json`.
- Attach the PDF with MIME type `application/pdf`.
- Switch between old and new generator with one setting, so the old one can stay
  active until R38 is approved.
- **Done when:** a test survey produces a PDF e-mail via the new generator; switching
  back to the old generator works.

### R43 Script robustness
- Timestamps on every log line.
- Top-level error handling: connection failures (e.g. DNS errors) produce a log entry
  and one error e-mail instead of an unhandled traceback.
- Optional `FORCE_SID=<id>` to regenerate the report of one survey on purpose.
- **Done when:** a simulated connection failure is logged with timestamp and reported.

### R44 Server installation of the generator
- Install this program at a path without spaces with uv; Pango and fonts; environment variables
  for content pack, store and archive; locations of log, store and archive; backup of
  the SQLite file and the archive.
- **Done when:** the cron job produces a report for a registered test survey on the
  server with the new generator.

---

## M8 Follow-up report

Starts once the content of the follow-up report has been defined with SPOT.

### R45 Content definition (document, not code)
- Which comparisons, which wording, how to handle new or changed questions.

### R46 Comparison engine
- `compare/`: differences between a wave and its predecessor for every comparable
  metric, statistical assessment (method decided in an ADR), handling of missing
  metrics, warning on suspected school-id changes.

### R47 Follow-up report definition and sections
- `reports/followup.py` and content-pack templates.

---

## M9 Response quality checks

Last milestone. Design requirements in architecture §4.1. All logic about missing
answers, display conditions and response cleaning belongs here; until then the input is
assumed to be clean (architecture D12).

### R48 Rule definition (document, not code)
- Which patterns count as implausible (e.g. straight-lining across scales,
  contradictory answers, implausible demographic combinations), agreed with SPOT.
- Rules for missing or inconsistent answers.

### R49 Quality stage
- `quality/` with a versioned rule set; flagged responses excluded from all metrics;
  rule-set version stored with the wave; number of exclusions in the methods section.
- **Done when:** fixtures with injected implausible responses are excluded as expected;
  reports show the number of exclusions.

### R50 Recompute
- `spot-report recompute` rebuilds snapshots from archived bundles, e.g. after the
  quality rules or metric definitions change. It uses the latest archived copy of each
  wave, the one the stored snapshot points to (architecture D13).

---

## Later

- Free-text answers to schools: how answers reviewed by SPOT (R52) are passed on to
  schools. Not started until the procedure is decided.
- AI summary of free-text answers (requires privacy assessment first).
- Trend charts over three or more waves.
- Dashboard (separate project) reading the SQLite store.
- Publish the automation script once it contains no server-specific configuration.
