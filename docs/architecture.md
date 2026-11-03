# Architecture

This document describes how SPOTReportGenerator is built and why. It is the reference
for all implementation work. If code and this document disagree, either the code is
wrong or this document must be updated in the same pull request.

## 1. Purpose and scope

SPOT is an anonymous survey on the mental health of upper secondary school students.
After a school has completed a survey wave, its school leadership receives a written
report. This program turns the survey responses of one school and one wave into that
report as a PDF.

There are two report types:

- **Initial report** (`initial`): the first wave at a school. Results are put into
  context with published reference values.
- **Follow-up report** (`followup`): every later wave. Results are compared with the
  school's own earlier waves.

Both types share all computation and rendering infrastructure but have their own
structure, templates and texts.

### Out of scope

- **Talking to LimeSurvey.** The program never calls the LimeSurvey API. The
  automation script on the server (section 2) detects finished surveys, exports the
  responses and calls this program with an input bundle (section 3).
- **Delivering reports.** The program writes files. The automation script e-mails the
  finished report to SPOT; SPOT forwards it to the school.
- **Free-text answers.** The program ignores them. The automation script writes them to
  a separate file that SPOT reviews manually (D14). How reviewed answers are passed on
  to schools is not decided yet (section 14).
- **The web dashboard.** It is a separate project that will read the same SQLite
  store (section 6).

## 2. System context

```
 LimeSurvey ──API──▶ automation script (cron, separate repository)
                         │  reads survey registry, writes input bundle, then calls:
                         ▼
              spot-report build <bundle> --out <dir>
                         │
        ┌────────────┬───┴────────────┬────────────────┬─────────────┐
        ▼            ▼                ▼                ▼             ▼
   report PDF   result.json   snapshot in SQLite   archived bundle   run log
                         │
                         ▼
        automation script e-mails the PDF to SPOT
```

The program is a command-line tool. It runs on a developer laptop during development
and on the SPOT server in production. It must behave identically in both places.

### 2.1 The automation script

`spot_automation.py` runs on the server via cron and lives in its own repository (it
contains server-specific configuration). Its current behaviour:

- Lists all surveys (`list_surveys`) and reads their status from `active`, `startdate`
  and `expires` (`get_survey_properties`).
- Processes a survey **once**, when its status is `expired` (end date reached) and no
  report has been generated yet. Progress is kept in `evaluation_state.json`.
- Exports complete responses with question codes and answer codes
  (`export_responses`, headings `code`, responses `short`).
- Writes the free-text answers of the survey to a separate file for manual review by
  SPOT (planned, roadmap R52, D14). They never reach this program.
- Calls the report generator, then e-mails the report to SPOT, and sends an error
  e-mail on failure.
- `TEST_SID=<id>` processes a single survey for testing.

One LimeSurvey survey corresponds to exactly one school and one wave. The changes the
script needs for this program are tracked in milestone M7 of the roadmap.

### 2.2 Survey registry

LimeSurvey does not know which school a survey belongs to. The automation script
therefore reads a **survey registry**, a small file maintained by hand on the server
whenever a new survey is set up:

```yaml
# surveys.yaml next to the automation script (not in any public repository)
515973:
  school_id: gym-example
  school_name: Gymnasium Beispiel
  wave: "2026"
  questionnaire_version: "2026.1"
```

An expired survey without a registry entry is not processed; the script sends one error
e-mail asking for the entry. Test surveys are simply not registered.

## 3. Input bundle

The cron script hands over a directory, the **input bundle**:

```
bundle/
├── manifest.json
└── responses.csv        # or responses.xlsx
```

`manifest.json` (schema version 1, draft):

```json
{
  "schema_version": 1,
  "school": { "id": "gym-example", "name": "Gymnasium Beispiel" },
  "wave": {
    "label": "2026",
    "fieldwork_start": "2026-04-20",
    "fieldwork_end": "2026-05-15"
  },
  "survey": { "limesurvey_id": 123456, "questionnaire_version": "2026.1" },
  "responses": { "file": "responses.csv", "format": "csv" }
}
```

Where the values come from:

| Field | Source |
|---|---|
| `school.*`, `wave.label`, `survey.questionnaire_version` | survey registry (section 2.2) |
| `wave.fieldwork_start`, `wave.fieldwork_end` | LimeSurvey survey properties `startdate` and `expires` (date part) |
| `survey.limesurvey_id` | LimeSurvey survey id |
| `responses.counts` (optional) | LimeSurvey `get_summary`: completed and incomplete responses, for the methods section |

`fieldwork_end` is required: it defines the order of waves (section 7). Optional
`responses.counts`:

```json
"responses": { "file": "responses.csv", "format": "csv",
               "counts": { "completed": 287, "incomplete": 41 } }
```

Rules for the responses file:

- Column headings are **question codes** (e.g. `PHQ9[PHQQ1]`), never question texts.
- Cell values are **answer codes** (e.g. `0`–`3`, `M`, `Gym1`, `Y`), never answer texts.
- The file contains **complete responses only**. Selecting them is the job of the cron
  script (LimeSurvey export with completion status `complete`).
- **Empty cells** are never an error and never a warning (D12). Until the quality stage
  exists (section 4.1), responses are assumed to be clean, and an empty cell has exactly
  two meanings:
  - **multi-select option** (marked in the questionnaire spec): the option was not
    selected; the respondent stays in the denominator;
  - **any other question**: the question was not shown to this respondent because a
    display condition was not met; the respondent is left out of that question's
    denominator.

  The program does not model display conditions anywhere.
- Supported formats: CSV as produced by the LimeSurvey RemoteControl `export_responses`
  call (headings `code`, responses `short`), and XLSX with the same structure (used by
  the existing synthetic datasets).

Reading (`ingest/readers.py`) turns both formats into the same DataFrame. The CSV is
UTF-8 (a BOM is tolerated), comma-separated, with one heading row of question codes
and one row per response. Headings and cells are stripped; empty or whitespace-only
cells become `NA` and nothing else is interpreted (D12). Response id and numeric
columns of the questionnaire spec are `Int64`, all other columns `string`. A numeric
column with a value that is not an integer stays `string` with the raw text, so that
validation can report it by column code and count (`unconverted_columns`); values are
never silently turned into `NA`. Format details: ADR 0001.

Validation (`ingest/validate.py`) checks structure only, against the questionnaire spec.
All findings are errors; each has a rule, a column code and a count of offending cells
(never a value, an id or a row):

| Rule | Meaning |
|---|---|
| `missing_column` | a required column of the spec is absent (optional columns may be) |
| `invalid_code` | single-choice cell not among the allowed codes |
| `invalid_marker` | multi-select option cell not equal to the `selected` code |
| `out_of_range` | numeric cell outside the inclusive range of the spec |
| `not_an_integer` | numeric cell that is not an integer (column left as text by the reader) |
| `duplicate_id`, `empty_id` | response id repeated (rows repeating an earlier id) or missing |
| `unreadable_file`, `invalid_manifest`, `unknown_version` | the bundle cannot be read; the message is the reason from the reader and contains no cell values |

Empty cells are never counted by any rule, not even in a column that is empty for every
respondent (D12). Free-text columns, metadata other than the response id and columns
the spec does not know are not value-checked; an unknown column is not a finding.
`spot-report validate <bundle>` prints one line per finding and exits with code 3 if
there is an error.

For local development, `spot-report build` also accepts a single responses file plus
`--school`, `--wave`, `--fieldwork-end` and `--questionnaire-version` options instead of
a bundle.

### Archive

Every bundle that is processed successfully is copied to an archive directory outside
the repository (`SPOT_ARCHIVE_DIR`), as `<school>/<wave>/<seq>/`, where `<seq>` is a
sequence number starting at `001`. An archived bundle is never overwritten: a new
bundle for the same school and wave (e.g. after a corrected export) is stored next to
the existing ones with the next sequence number (D13). The wave record in the store
points to the latest copy, the one its snapshot was computed from. This makes it
possible to recompute snapshots later when a metric definition changes. There is no
retention limit for archived bundles.

Only `manifest.json` and the responses file named in it are copied, byte for byte;
other files next to them (e.g. the free-text file, D14) are never archived. The copy is
written to a hidden temporary directory and renamed to the next free number, so an
interrupted run leaves no incomplete `<seq>/` and concurrent runs cannot take the same
number. The next number is the highest all-digit directory name plus one (gaps and other
entries are ignored), padded to three digits and simply longer after `999`.
`school.id` and `wave.label` become directory names, so they must match
`[A-Za-z0-9][A-Za-z0-9._-]*` (at most 100 characters); anything else is rejected before
anything is written. This is an input rule, not a privacy rule. Whether `build` requires
`SPOT_ARCHIVE_DIR` or skips archiving when it is unset is decided with the CLI (R28).

## 4. Pipeline

```
ingest ─▶ validate ─▶ (quality) ─▶ features ─▶ metrics ─▶ store ─▶ compare ─▶ present ─▶ render
                       later                                       follow-up
                                                                     only
```

| Stage | Input | Output | Notes |
|---|---|---|---|
| ingest | bundle | `Dataset` (DataFrame + manifest) | Reading and type normalisation only |
| validate | `Dataset` | `Dataset` + findings | Structural checks against the questionnaire spec (columns, answer codes, file format); empty cells are never a finding |
| quality | `Dataset` | `Dataset` + exclusion record | Plausibility checks on responses; planned for the end of the roadmap (section 4.1) |
| features | `Dataset` | per-person derived table | Sum scores, severity buckets, "burdened" flag, … |
| metrics | features + dataset | `MetricSet` | Aggregates only, **numbers only**, no formatting, no I/O |
| store | `MetricSet` + wave meta | snapshot in SQLite | Upsert per (school, wave) |
| compare | current + earlier snapshot | `Comparison` | Follow-up report only |
| present | `MetricSet` (+ `Comparison`) | template context + SVG charts | Formatting, privacy rules, charts |
| render | template context | HTML → PDF | Jinja2 + WeasyPrint |

Each stage only depends on the stages to its left. In particular:

- `metrics` never formats numbers as strings and never writes files.
- Charts are created only in `present`, never in `metrics`.
- Only `render` knows about HTML and WeasyPrint.

### 4.1 Response quality checks (planned)

`validate` checks whether the data are structurally correct (columns present, codes
allowed, file readable). `quality` will check whether individual responses are
plausible, e.g. identical answers across whole scales (straight-lining), contradictory
answers, or implausible combinations of demographic answers. Flagged responses are
excluded from all metrics.

All logic about missing answers, display conditions and response cleaning belongs to
this stage (roadmap R48–R50). Until it exists, the input is assumed to be clean and
empty cells are interpreted as described in section 3 (D12).

Requirements for when this stage is built:

- Rules are defined in a versioned rule set; the version is stored with every wave so
  that comparisons between waves can tell whether the same rules were applied.
- The number of excluded responses (not which ones, not their values) is recorded and
  shown in the methods section of the report.
- Until the stage exists, no responses are excluded and the rule-set version is empty.

## 5. Package layout

```
SPOTReportGenerator/
├── CLAUDE.md
├── LICENSE                         # AGPL-3.0
├── README.md
├── pyproject.toml
├── docs/
│   ├── architecture.md             # this file
│   ├── roadmap.md
│   └── decisions/                  # one short ADR per significant decision
├── src/spot_report/
│   ├── cli.py                      # entry point `spot-report`
│   ├── config.py                   # settings, env vars, paths
│   ├── ingest/
│   │   ├── manifest.py             # manifest model + loading
│   │   ├── readers.py              # csv / xlsx → DataFrame
│   │   ├── validate.py
│   │   └── archive.py
│   ├── questionnaire/
│   │   ├── spec.py                 # typed access to a questionnaire version
│   │   └── specs/
│   │       └── 2026.1.yaml         # codes and scoring rules only, no item texts
│   ├── quality/                    # planned (section 4.1)
│   ├── features.py                 # per-person derived variables
│   ├── metrics/
│   │   ├── types.py                # Proportion, Summary, Distribution, …
│   │   ├── registry.py             # metric ids + metadata
│   │   └── <domain>.py             # demography, diagnoses, absences, symptoms,
│   │                               # association, stigma, burnout, resilience
│   ├── store/
│   │   ├── schema.sql
│   │   └── sqlite_store.py
│   ├── compare/                    # follow-up comparisons
│   ├── present/
│   │   ├── formatting.py           # shared number formatting (filters + charts)
│   │   ├── privacy.py              # minimum group size rule
│   │   ├── context.py              # MetricSet → template context
│   │   └── charts/                 # matplotlib → SVG, shared style
│   ├── render/
│   │   ├── environment.py          # Jinja2 loaders (public base + content pack)
│   │   └── pdf.py                  # WeasyPrint
│   └── reports/
│       ├── base.py                 # ReportDefinition
│       ├── initial.py
│       └── followup.py
├── tools/                          # repository tooling (data guard, name check hooks)
├── templates/                      # PUBLIC: layout, macros, CSS design system, fonts
├── examples/content-demo/          # PUBLIC: demo content pack with placeholder texts
├── tests/
│   ├── fixtures/                   # synthetic datasets only (code headings)
│   │   └── expected/               # legacy parity numbers (data-derived only)
│   └── …
└── content/                        # PRIVATE content pack, gitignored (section 8)
```

## 6. Data contracts

### 6.1 Metric types

All metrics are immutable dataclasses holding raw numbers. Derived values (shares,
percentages) are computed properties, never stored separately. Every type records its
actual `n` (respondents counted for this metric) and `n_missing` (respondents left
out: question not shown, or a scale score that could not be computed), so reports can
show "n of N answered". The valid answers that section 9 counts are this `n`; the
privacy rules themselves are unchanged.

```python
@dataclass(frozen=True)
class Proportion:          # "k of n"
    k: int
    n: int                 # valid answers (denominator)
    n_missing: int

@dataclass(frozen=True)
class Summary:             # numeric scale or score
    n: int
    n_missing: int
    mean: float | None
    sd: float | None       # sample SD, ddof=1
    median: float | None
    q1: float | None       # quantiles: NumPy/pandas default ("linear")
    q3: float | None
    min: float | None
    max: float | None

@dataclass(frozen=True)
class Distribution:        # counts per category, in a defined order
    categories: tuple[str, ...]
    counts: tuple[int, ...]
    n_missing: int
```

Computation conventions are fixed here because legacy parity and comparisons between
waves depend on them: standard deviation with `ddof=1`, quantiles with the NumPy/pandas
default method. The set of types may grow (e.g. for multi-select patterns), but every
type must be JSON-serialisable and must contain enough information for statistical
comparison (counts and denominators, or mean, SD and n).

Details fixed in `metrics/types.py`:

- Invariants are checked on construction (non-negative integer counts, `k <= n`,
  categories unique and as many as counts, floats finite). Violations raise
  `MetricError`.
- `Summary`: with `n == 0` all statistics are `None`; with `n == 1` the sample SD is
  undefined and `None`, the other statistics are defined; from `n == 2` all are numbers.
  Median and quartiles come from `numpy.quantile` (`linear`); no rounding.
- `Proportion.share` is `None` for `n == 0`; `Distribution.n` is the sum of the counts
  and `Distribution.shares` is `None` for `n == 0`.
- Constructors from data live next to the types so that all domains use the same
  conventions: `Summary.from_values(values, n_missing)`,
  `Proportion.from_mask(mask, n_missing)`,
  `Distribution.from_values(values, categories, n_missing)`. They take only the valid
  respondents (no missing values; the left-out respondents are passed as `n_missing`)
  and their errors never contain values.
- JSON: every metric converts to a dict tagged with `"kind"`
  (`proportion | summary | distribution`, the same strings as the store's `kind`
  column), e.g. `{"kind": "proportion", "k": 3, "n": 10, "n_missing": 1}`. `None` is
  written as `null`, there is no NaN, and floats round-trip exactly. Parsing is strict
  (unknown or missing keys raise `MetricFormatError`). A new type is added to
  `METRIC_TYPES` with its own kind tag; existing payloads do not change.

### 6.2 Metric ids

Pattern: `domain.instrument.measure[.subgroup]`, lowercase, `[a-z0-9_]` per segment.

```
symptoms.phq9.severity              Distribution
symptoms.phq9.cutoff10              Proportion
symptoms.combined.burdened          Proportion
resilience.res.total                Summary
resilience.res.total.burdened       Summary
stigma.stig.item1                   Summary
```

Ids are part of the snapshot format. Renaming an id is a breaking change and needs a
migration. The registry (`metrics/registry.py`) records for every id: type, domain,
questionnaire items it depends on, and since which questionnaire version it exists.

`validate_metric_id` (in `metrics/types.py`) enforces the pattern: 3 or 4 segments of
`[a-z0-9_]`, none empty. Anything else raises `MetricIdError`. It is used by `MetricSet`
and by the registry.

The registry is built from `MetricDefinition(id, kind, domain, items, since)` tuples
that each domain module exposes (there is no mutable module-level registry). It rejects
duplicate ids and a `domain` that differs from the first id segment, and
`MetricRegistry.check(metric_set)` verifies that every id is registered with the
registered kind. `METRICS_VERSION` (an integer in `metrics/registry.py`, stored per
wave) is bumped when numbers under an existing id become incomparable with earlier
snapshots.

### 6.3 MetricSet and snapshot

A `MetricSet` is an immutable mapping of metric ids to metric values, validated on
construction and iterated in sorted id order. Its JSON form is one object
`{metric_id: metric}` with sorted keys, so equal sets give identical text. A **snapshot** is a `MetricSet` plus
wave metadata (school, wave label, fieldwork dates, questionnaire version, program
version, metrics version, quality rule-set version, archive path).

### 6.4 SQLite schema (draft)

```sql
CREATE TABLE school (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE wave (
    id                    INTEGER PRIMARY KEY,
    school_id             TEXT NOT NULL REFERENCES school(id),
    label                 TEXT NOT NULL,
    fieldwork_start       TEXT,
    fieldwork_end         TEXT NOT NULL,
    limesurvey_id         INTEGER,
    questionnaire_version TEXT NOT NULL,
    program_version       TEXT NOT NULL,
    metrics_version       INTEGER NOT NULL,
    quality_rules_version TEXT,
    archive_path          TEXT,
    created_at            TEXT NOT NULL,
    UNIQUE (school_id, label)
);

CREATE TABLE metric (
    wave_id   INTEGER NOT NULL REFERENCES wave(id) ON DELETE CASCADE,
    metric_id TEXT NOT NULL,
    kind      TEXT NOT NULL,     -- proportion | summary | distribution | …
    payload   TEXT NOT NULL,     -- JSON
    PRIMARY KEY (wave_id, metric_id)
);
```

Running the program again for the same school and wave replaces that wave's snapshot.
`spot-report snapshot export` writes a snapshot as JSON for inspection.

## 7. Report types and selection

A `ReportDefinition` lists the sections of a report, the template for each section and
the metrics each section needs. `initial.py` and `followup.py` each define one.

Waves of a school are ordered by `fieldwork_end`. Report type selection
(`--report-type auto|initial|followup`, default `auto`):

- `auto` → `followup` if the store contains a wave of the same school with an earlier
  `fieldwork_end`, otherwise `initial`.
- A follow-up report compares with the latest wave *before* the current one. Re-running
  an old wave therefore compares it with its own predecessor, not with newer waves.
- If `auto` selects `initial` but the store contains a school with the same name and a
  different id, the program logs a warning (the school id may have changed).
- If a metric is missing in the earlier wave (e.g. new question), the follow-up report
  shows it without comparison and says so.

The content and the statistical method of the follow-up report are not decided yet
(section 14).

## 8. Templates and content packs

Report text, labels and anything instrument-specific live in a **content pack**, a
directory outside the public repository. The public repository contains only layout and
infrastructure.

| Location | Public | Contents |
|---|---|---|
| `templates/` | yes | base layout, page rules (`@page`), Jinja macros (table, figure, key-figure box, delta badge), CSS design system, bundled open-licence fonts |
| `examples/content-demo/` | yes | minimal content pack with placeholder texts, used by tests, CI and anyone trying the project |
| `content/` (gitignored) | no | real report templates and texts, item and answer labels, reference values with citations |

The content directory is set via `SPOT_CONTENT_DIR` (default `./content`). Jinja looks
up templates in the content pack first and falls back to `templates/`.

The real content pack is a separate private repository. Its first version is built from
the previous Word template and the previous program and is reviewed by Johannes before
any report uses it (D15, roadmap R51).

Content pack structure:

```
content/
├── reports/
│   ├── initial/            # section templates of the initial report
│   └── followup/           # section templates of the follow-up report
├── labels.yaml             # answer and item labels (German)
└── references.yaml         # reference values + citations → also used for the
                            # references appendix
```

### Instrument aliases

Some instruments are referred to inside this repository only by neutral aliases:

| Alias | Instrument |
|---|---|
| `RES` | resilience scale |
| `STIG` | stigma questionnaire |

Their real names, item texts and reference values appear only in the private content
pack; the mapping is kept in the untracked `CLAUDE.local.md`, the forbidden terms in the
untracked `.denylist.txt`. Pre-commit hooks reject these terms in tracked files and in
commit messages. The column codes of the current questionnaire do not contain them; if a
future questionnaire version did, the codes would have to be renamed in LimeSurvey. All other instruments
(PHQ-9, GAD-7, School Burnout Inventory / SBI) may be named normally. No item texts of
any instrument are stored in this repository; questionnaire specs contain codes and
scoring rules only.

## 9. Privacy

The data are anonymous survey responses of minors about their mental health. The
privacy rules of the previous report were reviewed by the responsible authority without
objections. **This program implements exactly those rules.** Additional suppression
rules are not part of the scope; any change to the rules requires approval by SPOT.

1. **Minimum group size.** A subgroup is only shown if it has at least
   `min_group_size` valid answers (10, as in the reviewed report). Values below 10 are
   rejected by the configuration. Below 10 answers for the whole school, no report is
   produced. The rule is implemented once in `present/privacy.py` and used by every
   section.
2. **No real data in the repository.** Only synthetic datasets in `tests/fixtures/`,
   exported with code headings. A data guard rejects data files elsewhere, both as a
   pre-commit hook and in CI.
3. **Logs and validation messages** contain counts, column codes and file names, never
   response values or free text.
4. **Secrets** (server paths, credentials of the cron script) are never in the
   repository.

## 10. Presentation and rendering

- **Formatting**: all number formatting lives in `present/formatting.py`. Jinja filters
  (`pct`, `number`, `delta`, …) and chart axis labels both call these functions.
  Decimal separator is configurable, default `.` (as in previous reports). Rounding is
  half-up, implemented with `decimal.Decimal` (Python's `round()` rounds half to even).
- **Design tokens** (colours, font sizes, spacing) are defined once in
  `templates/design.toml`. They are rendered into CSS custom properties and also read
  by the chart style, so text and charts always match.
- **Charts**: complex charts (box plots, histograms, scatter plots, UpSet-style
  pattern charts) are matplotlib figures exported as SVG. The shared style is applied
  with `matplotlib.rc_context` (no global state) and `svg.hashsalt` is fixed so that SVG
  output is identical on every machine. Simple elements (stacked percentage bars,
  key-figure boxes, change indicators) are built directly in HTML/CSS via macros.
- Charts that need person-level values (e.g. the scatter plot of burnout and
  resilience scores) receive read-only access to the derived feature table of the
  current wave. These values are never persisted.
- **Figure and table numbers** are assigned in the template, not in chart titles.
- **PDF**: WeasyPrint with CSS Paged Media for page numbers, running headers, table of
  contents with page numbers and controlled page breaks.
- Fonts are bundled (open licence) so that the laptop and the server produce identical
  output.

## 11. Command-line interface (draft)

```
spot-report build <bundle> [--report-type auto|initial|followup]
                           [--out DIR] [--store PATH] [--content-dir DIR]
spot-report build --responses FILE --school ID --wave LABEL --fieldwork-end DATE
                  --questionnaire-version V [...]
spot-report validate <bundle>
spot-report snapshot list   [--school ID]
spot-report snapshot export --school ID --wave LABEL
```

Outputs per run in `<out>/<school>/<wave>/`: `report.pdf`, `report.html` (for
debugging), `run.log` and `result.json`. `result.json` is the machine-readable result
for the automation script:

```json
{ "status": "ok", "exit_code": 0, "report_type": "initial",
  "report": "report.pdf", "warnings": 2, "message": "" }
```

Exit codes for the cron script:

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | unexpected internal error (Python's default for uncaught exceptions) |
| 3 | invalid input (manifest, file or validation errors) |
| 4 | too few answers for a report (minimum group size) |
| 5 | rendering error |

Guidance for the automation script: codes 3 and 4 are final (retrying cannot help);
they produce an error e-mail with the message from `result.json`. Only the LimeSurvey
export (network) should be retried, not the report generation.

## 12. Testing

- **Unit tests** per metric on small hand-made DataFrames with known results.
- **Fixture tests** on the synthetic datasets in `tests/fixtures/`.
- **Legacy parity tests**: for every fixture, the numbers computed by the previous
  program are stored once as JSON in `tests/fixtures/expected/`. Only numbers computed
  from the data are stored, never reference values from literature. The new metrics must
  reproduce them, or deviations must be documented as intentional fixes.
- **Render smoke test**: the demo content pack renders a PDF from a fixture without
  WeasyPrint warnings.
- CI (GitHub Actions) runs linting, the data guard and all tests on every pull request.

## 13. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | HTML/CSS → PDF with WeasyPrint | Full design freedom, print features via CSS Paged Media, no browser dependency |
| D2 | Two report types on a shared core | Different structure and texts, no duplicated computation |
| D3 | Metrics are numbers; formatting only in presentation | Comparisons between waves need numbers |
| D4 | Snapshots in SQLite, JSON export | Fast comparisons; same store for the dashboard |
| D5 | No LimeSurvey dependency; input bundle from external script | Program stays independent of LimeSurvey updates |
| D6 | Private content pack; neutral aliases for some instruments | No instrument content in the public repository |
| D7 | AGPL-3.0 | Improvements by others stay open |
| D8 | Python 3.12, uv, ruff, pytest, Conventional Commits | Current standard tooling, clean history |
| D9 | Privacy rules exactly as in the reviewed report | Reviewed by the responsible authority; changes only with SPOT approval |
| D10 | Input bundles are archived by this program | Snapshots can be recomputed when metric definitions change; one owner for the archive |
| D11 | Survey registry maps LimeSurvey surveys to school and wave | LimeSurvey has no notion of schools; follow-up reports need a stable school id |
| D12 | Empty cells are never an error or warning. Multi-select option empty = not selected (respondent stays in the denominator); any other question empty = not shown (respondent left out of that question's denominator). A scale score is computed only if all its items are present, otherwise it is missing for that respondent, silently. Display conditions are not modelled. This clean-data assumption holds until the quality stage exists (R48–R50) | Real exports contain only completed responses and the synthetic data reflect this; follow-up questions can legitimately be empty, even for every respondent. Keeping all handling of missing or inconsistent answers in one later stage avoids ad-hoc rules spread across validation and features |
| D13 | Archived bundles are never overwritten; a new bundle for the same school and wave gets the next sequence number; the snapshot points to the latest | Every input that ever produced a report stays available and traceable |
| D14 | Free-text answers go to a separate file written by the automation script for manual review by SPOT; this program keeps ignoring them; required before the new generator replaces the old one | The previous report contained free-text answers; they may identify students and need a human review before anything reaches a school |
| D15 | The real content pack is a private repository, first filled from the previous Word template and program, reviewed by Johannes before use | Reuses the reviewed wording of the previous report; texts and reference values stay out of the public repository |

Larger future decisions get their own ADR in `docs/decisions/`.

## 14. Open questions

- Content and structure of the follow-up report.
- Statistical method for "relevant change" between waves (e.g. confidence intervals
  for differences of proportions, Welch test for means).
- Free-text answers: how answers reviewed by SPOT are passed on to schools (format,
  delivery). Extraction for the review is decided (D14).
- Response quality rules, including rules for missing or inconsistent answers
  (section 4.1).
