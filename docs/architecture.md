# Architecture

This document describes how SPOT-SchoolReportGenerator is built and why. It is the
reference for all implementation work. If code and this document disagree, either the
code is wrong or this document must be updated in the same pull request.

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

- **Talking to LimeSurvey.** The program never calls the LimeSurvey API. An external
  script on the server (run by cron) detects completed surveys, exports the responses
  and calls this program with an input bundle (see section 3).
- **Delivering reports** (e-mail, upload). The program writes files; delivery is
  handled elsewhere.
- **The web dashboard.** It is a separate project that will read the same SQLite
  store (section 6).

## 2. System context

```
 LimeSurvey ──API──▶ cron script (not in this repo)
                         │  writes input bundle, then calls:
                         ▼
              spot-report build <bundle>
                         │
        ┌────────────────┼──────────────────┐
        ▼                ▼                  ▼
   report PDF(s)   snapshot in SQLite   run log
```

The program is a command-line tool. It runs on a developer laptop during development
and on the SPOT server in production. It must behave identically in both places.

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

Rules for the responses file:

- Column headings are **question codes** (e.g. `PHQ9[PHQQ1]`), never question texts.
- Cell values are **answer codes** (e.g. `0`–`3`, `M`, `Gym1`, `Y`), never answer texts.
- Only complete responses are included, unless the manifest says otherwise.
- Supported formats: CSV as produced by the LimeSurvey RemoteControl `export_responses`
  call (headings `code`, responses `short`), and XLSX with the same structure (used by
  the existing synthetic datasets).

For local development, `spot-report build` also accepts a single responses file plus
`--school`, `--wave` and `--questionnaire-version` options instead of a bundle.

## 4. Pipeline

```
ingest ─▶ validate ─▶ features ─▶ metrics ─▶ store ─▶ compare ─▶ present ─▶ render
                                                       (follow-up only)
```

| Stage | Input | Output | Notes |
|---|---|---|---|
| ingest | bundle | `Dataset` (DataFrame + manifest) | No interpretation, only reading and type normalisation |
| validate | `Dataset` | `Dataset` + list of findings | Checks columns and answer codes against the questionnaire spec |
| features | `Dataset` | per-person derived table | Sum scores, severity buckets, "burdened" flag, … |
| metrics | features + dataset | `MetricSet` | Aggregates only, **numbers only**, no formatting, no I/O |
| store | `MetricSet` + wave meta | snapshot in SQLite | Upsert per (school, wave) |
| compare | current + earlier snapshots | `Comparison` | Follow-up report only |
| present | `MetricSet` (+ `Comparison`) | template context + SVG charts | Formatting, small-group suppression, charts |
| render | template context | HTML → PDF | Jinja2 + WeasyPrint |

Each stage only depends on the stages to its left. In particular:

- `metrics` never formats numbers as strings and never writes files.
- Charts are created only in `present`, never in `metrics`.
- Only `render` knows about HTML and WeasyPrint.

## 5. Package layout

```
SPOT-SchoolReportGenerator/
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
│   │   └── validate.py
│   ├── questionnaire/
│   │   ├── spec.py                 # typed access to the questionnaire definition
│   │   └── questionnaire.yaml      # codes and scales only, no item texts
│   ├── metrics/
│   │   ├── types.py                # Proportion, Summary, Distribution, …
│   │   ├── features.py             # per-person derived variables
│   │   ├── registry.py             # metric ids + metadata
│   │   └── <domain>.py             # demography, diagnoses, absences, symptoms,
│   │                               # association, stigma, burnout, resilience
│   ├── store/
│   │   ├── schema.sql
│   │   └── sqlite_store.py
│   ├── compare/                    # follow-up comparisons
│   ├── present/
│   │   ├── formatting.py           # Jinja filters: pct, number, delta, …
│   │   ├── privacy.py              # small-group suppression
│   │   ├── context.py              # MetricSet → template context
│   │   └── charts/                 # matplotlib → SVG, shared style
│   ├── render/
│   │   ├── environment.py          # Jinja2 loaders (public base + content pack)
│   │   └── pdf.py                  # WeasyPrint
│   └── reports/
│       ├── base.py                 # ReportDefinition
│       ├── initial.py
│       └── followup.py
├── templates/                      # PUBLIC: layout, macros, CSS design system, fonts
├── examples/content-demo/          # PUBLIC: demo content pack with placeholder texts
├── tests/
│   ├── fixtures/                   # synthetic datasets only (code headings)
│   └── …
└── content/                        # PRIVATE content pack, gitignored (section 8)
```

## 6. Data contracts

### 6.1 Metric types

All metrics are immutable dataclasses holding raw numbers. Derived values (shares,
percentages) are computed properties, never stored separately.

```python
@dataclass(frozen=True)
class Proportion:          # "k of n"
    k: int
    n: int                 # valid answers (denominator)

@dataclass(frozen=True)
class Summary:             # numeric scale or score
    n: int
    mean: float | None
    sd: float | None
    median: float | None
    q1: float | None
    q3: float | None
    min: float | None
    max: float | None

@dataclass(frozen=True)
class Distribution:        # counts per category, in a defined order
    categories: tuple[str, ...]
    counts: tuple[int, ...]
```

The set of types may grow (e.g. for multi-select patterns), but every type must be
JSON-serialisable and must contain enough information for statistical comparison
(counts and denominators, or mean, SD and n).

### 6.2 Metric ids

Every metric has a stable dotted id, e.g.

```
symptoms.phq9.severity              Distribution
symptoms.phq9.cutoff10              Proportion
symptoms.burdened                   Proportion
resilience.res.total                Summary
resilience.res.total.burdened       Summary
association.burdened_by_diagnosis   Distribution
```

Ids are part of the snapshot format. Renaming an id is a breaking change and needs a
migration. The registry (`metrics/registry.py`) records for every id: type, domain,
questionnaire items it depends on, and since which questionnaire version it exists.

### 6.3 MetricSet and snapshot

A `MetricSet` maps metric ids to metric values. A **snapshot** is a `MetricSet` plus
wave metadata (school, wave label, fieldwork dates, questionnaire version, program
version, metrics version).

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
    fieldwork_end         TEXT,
    limesurvey_id         INTEGER,
    questionnaire_version TEXT NOT NULL,
    program_version       TEXT NOT NULL,
    metrics_version       INTEGER NOT NULL,
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

The store holds **unsuppressed** aggregates. Suppression is applied wherever data leaves
the system (report, dashboard), see section 9.

## 7. Report types and selection

A `ReportDefinition` lists the sections of a report, the template for each section and
the metrics each section needs. `initial.py` and `followup.py` each define one.

Report type selection (`--report-type auto|initial|followup`, default `auto`):

- `auto` → `followup` if the store contains an earlier wave of the same school,
  otherwise `initial`.
- A follow-up report compares with the most recent earlier wave. Trend views over more
  than two waves are added later.
- If a metric is missing in the earlier wave (e.g. new question), the follow-up report
  shows it without comparison and says so.

The content and the statistical method of the follow-up report are not decided yet
(see section 12).

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

Some instruments used in the survey are referred to inside this repository only by
neutral aliases, e.g. **RES** for the resilience scale (`resilience.res.*`). Their real
names, item texts and reference values appear only in the private content pack. No item texts of any instrument are stored in this
repository; `questionnaire.yaml` contains codes and scoring rules only.

## 9. Privacy

The data are anonymous survey responses of minors about their mental health.

1. **No real data in the repository.** Only synthetic datasets in `tests/fixtures/`,
   exported with code headings. A pre-commit hook rejects data files elsewhere.
2. **Minimum group size.** Any figure based on a group with fewer than
   `min_group_size` valid answers (default 10, configurable) is not shown. This applies
   to the whole school as well: below the threshold, no report is produced.
   Suppression is implemented once in `present/privacy.py` and used by every section.
3. **Logs** contain counts, warnings and file names, never response values or free
   text.
4. **Free-text answers** are not part of the main report. They go into a separate
   appendix document.
5. **Secrets** (paths on the server, credentials of the cron script) are never in the
   repository.

Whether individual cells of a table (not just whole groups) must be suppressed below a
threshold is an open question (section 12).

## 10. Presentation and rendering

- **Formatting** is done by Jinja filters (`pct`, `number`, `delta`, …) so templates
  receive numbers and decide how to show them. Decimal separator is `.`, percentages
  are rounded half-up.
- **Design tokens** (colours, font sizes, spacing) are defined once in
  `templates/design.toml`. They are rendered into CSS custom properties and also read
  by the chart style, so text and charts always match.
- **Charts**: complex charts (box plots, histograms, scatter plots, UpSet-style
  pattern charts) are matplotlib figures exported as SVG with the shared style. Simple
  elements (stacked percentage bars, key-figure boxes, change indicators) are built
  directly in HTML/CSS via macros.
- Charts that need person-level values (e.g. a scatter plot of two scores) receive
  read-only access to the derived feature table of the current wave. These values are
  never persisted.
- **Figure and table numbers** are assigned in the template, not in chart titles.
- **PDF**: WeasyPrint with CSS Paged Media for page numbers, running headers, table of
  contents with page numbers and controlled page breaks.
- Fonts are bundled (open licence) so that the laptop and the server produce identical
  output.

## 11. Command-line interface (draft)

```
spot-report build <bundle> [--report-type auto|initial|followup]
                           [--out DIR] [--store PATH] [--content-dir DIR]
spot-report build --responses FILE --school ID --wave LABEL
                  --questionnaire-version V [...]
spot-report snapshot list   [--school ID]
spot-report snapshot export --school ID --wave LABEL
spot-report validate <bundle>
```

Outputs per run in `out/<school>/<wave>/`: `report.pdf`, `report.html` (for
debugging), `appendix-freetext.pdf`, `run.log`.

Exit codes for the cron script: `0` success, `1` invalid input, `2` privacy threshold
not met, `3` rendering error.

## 12. Testing

- **Unit tests** per metric on small hand-made DataFrames with known results.
- **Fixture tests** on the synthetic datasets in `tests/fixtures/`.
- **Legacy parity tests**: for every fixture, the numbers of the previous program are
  stored once as JSON in `tests/fixtures/expected/`. The new metrics must reproduce
  them (or deviations must be documented as intentional fixes).
- **Render smoke test**: the demo content pack renders a PDF from a fixture without
  warnings.
- CI (GitHub Actions) runs linting and all tests on every pull request.

## 13. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | HTML/CSS → PDF with WeasyPrint | Full design freedom, print features via CSS Paged Media, no browser dependency |
| D2 | Two report types on a shared core | Different structure and texts, no duplicated computation |
| D3 | Metrics are numbers; formatting only in presentation | Comparisons between waves need numbers |
| D4 | Snapshots in SQLite, JSON export | Follow-up reports without old raw data; same store for the dashboard |
| D5 | No LimeSurvey dependency; input bundle from external script | Program stays independent of LimeSurvey updates |
| D6 | Private content pack; neutral aliases for instruments | No instrument content in the public repository |
| D7 | AGPL-3.0 | Improvements by others stay open |
| D8 | Python 3.12, uv, ruff, pytest, Conventional Commits | Current standard tooling, clean history |

Larger future decisions get their own ADR in `docs/decisions/`.

## 14. Open questions

- Manifest details: how does the cron script know school id and wave label for a survey?
- Cell-level suppression rule for small counts inside tables.
- Content and structure of the follow-up report.
- Statistical method for "relevant change" between waves (e.g. confidence intervals
  for differences of proportions, Welch test for means).
- Raw data archive: who stores the input bundles long term (cron script or this
  program), and is a `recompute` command needed when metric definitions change?
- AI summary of free-text answers: privacy assessment needed before any implementation.
