# Synthetic test fixtures

All datasets in this folder are **generated synthetic data**. They contain no real
responses, no question texts and no answer texts: headings are question codes, cells
are numbers or short answer codes. `tests/test_fixtures.py` loads every file here and
checks this (headings match the code pattern, no cell has surrounding whitespace or
contains whitespace inside or a long string, response ids are unique). The loading
goes through the production readers in `spot_report.ingest`. Add new fixtures here only after they pass that test.

Only the layout of a LimeSurvey export (`export_responses`, headings `code`,
responses `short`) is imitated, see `docs/architecture.md` §3.

## Datasets

| File | Responses | Columns | Format |
|---|---|---|---|
| `synthetic_300.xlsx` | 300 | 75 | XLSX, one sheet, header in row 1 |
| `synthetic_500.xlsx` | 500 | 75 | XLSX, one sheet, header in row 1 |
| `synthetic_800.xlsx` | 800 | 75 | XLSX, one sheet, header in row 1 |
| `synthetic_300.csv` | 300 | 75 | LimeSurvey CSV, generated from the XLSX |
| `synthetic_500.csv` | 500 | 75 | LimeSurvey CSV, generated from the XLSX |
| `synthetic_800.csv` | 800 | 75 | LimeSurvey CSV, generated from the XLSX |

The XLSX files are the source. The CSV files are generated from them in the format of
the LimeSurvey CSV export (UTF-8 without BOM, comma, LF line endings, one heading row
of codes, empty cells empty) and must not be edited by hand. After changing or adding
an XLSX fixture, regenerate them:

```bash
uv run python tools/make_csv_fixtures.py          # write the CSV files
uv run python tools/make_csv_fixtures.py --check  # fail if a CSV is out of date
```

`tests/ingest/test_fixture_parity.py` checks that each CSV and its XLSX read into
identical DataFrames; `tests/tools/test_make_csv_fixtures.py` checks that the committed
CSV files are up to date.

The three files have the same column structure and differ only in the number of
responses (and, as they are random draws, in the individual values). They are
meant to represent a small, a medium and a large school-wave sample.

### Column structure (codes only)

- **Survey metadata** (7 columns): `id` (unique running number), `submitdate`,
  `lastpage`, `startlanguage`, `seed`, `startdate`, `datestamp`. `lastpage`,
  `seed` and `submitdate` are constant, and `startdate` and `datestamp` are empty in
  every row, so tests must not rely on them.
- **Demographics** (3): `DQSEX`, `DQSTUFE` (short codes), `DQAGE` (integer).
- **Diagnosis and help-seeking** (24): `DIAGQ0`, the multi-select blocks
  `DIAGQ1[...]`, `DIAGQ2[...]` and `DIAGQ3[...]` (one column per option, filled with
  a marker code when selected, empty otherwise), `FEHLTAGQ0` and `FEHLTAGQ1`
  (`FEHLTAGQ1` is only partly filled).
- **Symptoms**: `PHQ9[PHQQ1]` to `PHQ9[PHQQ9]` and `GAD7[GADQ1]` to `GAD7[GADQ7]`
  (integers 0 to 3), plus `SIPHQ`.
- **STIG**: five single-item columns, integers on scales of different length.
- **Burnout**: `SBI[SBIQ0]` to `SBI[SBIQ8]` (integers 0 to 5, nine items).
- **RES**: ten items, integers 0 to 4.

Besides the two empty metadata columns, only the 21 multi-select option columns and
`FEHLTAGQ1` contain empty cells; all scale items and the other columns are complete.

## What they are meant to test

- Readers (R08) and validation (R09): loading CSV and XLSX into a DataFrame, mapping
  columns to codes, the codes-only heading check, id uniqueness.
- Multi-select handling: option column empty means not selected (decision D12).
- Questions that are partly filled (`FEHLTAGQ1`) and empty-by-design columns,
  to exercise the denominator rules of D12.
- Size independence: the same pipeline on 300, 500 and 800 responses.
- Smoke and end-to-end runs of the CLI (`spot-report build --responses ...`).

These datasets are **not** a source of expected numbers: the legacy parity values
belong in `expected/` and must be generated from a documented run, not from this file.

## Legacy parity baseline (`expected/`)

`expected/<dataset>.json` holds, for each XLSX fixture, the numbers the previous
program computed from that dataset (roadmap R13, ADR 0002 in `docs/decisions/`). Only
data-derived numbers are stored: no texts, no chart files, no warnings, no free-text
answers and no reference values from literature. Domain tests (R14–R21) compare their
results with these numbers through `tests/parity.py`; `tests/test_parity.py` checks
the files.

### Regenerating

The files are written by `tools/legacy_baseline.py`, which needs a checkout of the
previous program and an environment with its pinned requirements; see the script's
docstring for the commands. It is not run in CI. Regenerate only when a fixture
changes or the previous program is corrected, and say so in the pull request;
`--check` reports files that are out of date. Never edit the JSON by hand.

### Format

```json
{
  "header": {
    "schema_version": 1,
    "dataset": "synthetic_300",
    "source": "synthetic_300.xlsx",
    "generated_by": "previous program, commit <short sha>",
    "generator": "tools/legacy_baseline.py",
    "environment": "Python ..., pandas ..., numpy ..., matplotlib ..., openpyxl ...",
    "rounding": { "...": "how `value` was rounded, per kind" },
    "excluded": { "<key>": "why it is not stored" }
  },
  "values": {
    "demography.gender.count.M": {"kind": "count", "value": 155},
    "demography.gender.pct.M": {"kind": "percent", "value": 52, "decimals": 0,
      "unrounded": 51.666666666666664, "numerator": 155, "denominator": 300},
    "burnout.sbi.mean.total": {"kind": "statistic", "value": 31.2, "decimals": 2,
      "unrounded": 31.196666666666665},
    "stigma.all.chart.box.Q1.median": {"kind": "statistic", "value": 4.0,
      "decimals": null, "unrounded": null}
  }
}
```

Keys are the dotted paths of the previous program's report context (its own key
names, some German), plus a few `chart` groups for numbers that only its charts show.
The segment that names an aliased instrument is replaced by the alias (`res`).

| Kind | Fields | Meaning |
|---|---|---|
| `count` | `value` | exact integer |
| `percent` | `value`, `decimals`, `unrounded`, `numerator`, `denominator` | `value` is the percentage as shown (half-up rounded to `decimals`), `unrounded` the exact percentage `100 * numerator / denominator` (`null` for denominator 0, which the previous program showed as 0 %) |
| `statistic` | `value`, `decimals`, `unrounded` | mean or SD as shown (Python `format` to `decimals`) with the float behind it; `decimals: null` means the number was not shown as text (box plot lines) and `value` is unrounded; `value: null` means undefined |

### Key groups per domain

| Domain (task) | Keys | Notes on the legacy computation |
|---|---|---|
| Demography (R14) | `demography.all`, `.gender.{count,pct}.{M,W,D}`, `.level.{count,pct}.Gym1-4`, `.age_chart.count.<age>` | percentages use all respondents as denominator (an empty answer would not be dropped) |
| Diagnoses, help, treatment (R15) | `diagnoses.top.{n,pct}`; `.count.<type>`, `.pct.<type>`; `.help.{count,pct}.<option>`; `.help_usage.{n0..n3,n4p,p0..p3,p4p}`; `.help_upset.K1-K6.<pattern>`; `.treatment.{count,pct}.<option>` | type percentages use all respondents as denominator, help and treatment percentages the diagnosed; `help_usage` counts selected help sources per diagnosed respondent (`NIEM` counts as none; `KLIN` included); `help_upset` holds the chart's six columns (two most frequent single, pair and triple patterns of help sources, ties by pattern name, padded with `empty`), the key naming the column and its pattern joined by `+` |
| Absences (R16) | `absences.top.{n,pct}`, `.bucket.{count,pct}.FE01/FE05/FE10/FE20` | `top` denominator: all respondents; bucket denominator: respondents with `FEJA` |
| Symptoms (R17) | `symptoms.{phq9,gad7}.top.{n,pct}`, `.sev.{count,pct,diagcount}.<band>`; `.combined.top`; `.suicidal.{top,dist}`; `.impairment.{top,dist}` | `top`: cut-off (sum ≥ 10; item 9 and impairment ≥ 2); `diagcount`: band × depression (PHQ-9) or anxiety (GAD-7) diagnosis option; band `mod_severe` is the new `moderately_severe` |
| Association (R18) | `assoc.overlap.*`, `assoc.table_all.<category>.<status>`, `assoc.by_level.Gym1-4.<category>.<status>` | categories `severe` (PHQ-9 or GAD-7 ≥ 10), `moderate` (either 5–9, not severe; called `medium` in the new metrics, ADR 0004), `mildnone`; status `known_diag`, `treated` (diagnosed and any treatment option), `unknown_diag` (not diagnosed) |
| Stigma (R19) | `stigma.all.stats.{mean,sd}.Q1-Q5`; `stigma.{all,burdened}.chart.box.Q1-Q5.{n,median,q1,q3,whislo,whishi}` | box plots from matplotlib (quartiles linear, whiskers 1.5 IQR); `burdened` = PHQ-9 or GAD-7 cut-off |
| Burnout (R20) | `burnout.sbi.{mean,sd}.{exhaustion,cynicism,total}` | means of per-person sums |
| Resilience (R21) | `resilience.res.{all,burdened,nonburdened}.{n,mean,sd}`, `resilience.res.hist.{n,count.<score>}` | `nonburdened`: at least one symptom score and no cut-off |

### Comparing in tests

```python
from tests.parity import assert_parity, load_expected

expected = load_expected("synthetic_300")  # typed access, e.g. .count(key)
assert_parity("synthetic_300", "demography.gender.pct.M", share)  # share in [0, 1]
```

`assert_parity` takes the new, unrounded value. Counts must be equal. For a
percentage the new value is a share and is compared as a percentage. Where the file
has an unrounded legacy value, the new value must match it within a relative
tolerance of 1e-9; otherwise it is rounded half-up (`decimal.Decimal`) to the legacy
`decimals` and must equal the shown value. `None` matches only `null`.

### Known deviations

A difference found by a domain task is not fixed in that task. It is recorded in
`expected/known_deviations.yaml` (dataset or `*`, key, legacy value as shown, new value
in the units of the entry, task id, reason) and explained in the pull request. For a
recorded key `assert_parity` requires the recorded **new** value, so later changes are
still caught, and fails when the key matches the legacy value again (stale entry: remove
it). The list starts empty.
