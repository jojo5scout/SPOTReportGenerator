# Synthetic test fixtures

All datasets in this folder are **generated synthetic data**. They contain no real
responses, no question texts and no answer texts: headings are question codes, cells
are numbers or short answer codes. `tests/test_fixtures.py` loads every file here and
checks this (headings match the code pattern, no cell holds whitespace or a long
string, response ids are unique). Add new fixtures here only after they pass that test.

Only the spreadsheet layout of a LimeSurvey export (`export_responses`, headings
`code`, responses `short`) is imitated, see `docs/architecture.md` §3.

## Datasets

| File | Responses | Columns | Format |
|---|---|---|---|
| `synthetic_300.xlsx` | 300 | 75 | XLSX, one sheet, header in row 1 |
| `synthetic_500.xlsx` | 500 | 75 | XLSX, one sheet, header in row 1 |
| `synthetic_800.xlsx` | 800 | 75 | XLSX, one sheet, header in row 1 |

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

- Readers (R08) and validation (R09): loading XLSX into a DataFrame, mapping
  columns to codes, the codes-only heading check, id uniqueness.
- Multi-select handling: option column empty means not selected (decision D12).
- Questions that are partly filled (`FEHLTAGQ1`) and empty-by-design columns,
  to exercise the denominator rules of D12.
- Size independence: the same pipeline on 300, 500 and 800 responses.
- Smoke and end-to-end runs of the CLI (`spot-report build --responses ...`).

These datasets are **not** a source of expected numbers: the legacy parity values
belong in `expected/` and must be generated from a documented run, not from this file.
