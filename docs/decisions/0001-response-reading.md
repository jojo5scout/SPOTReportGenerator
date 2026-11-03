# 0001 Reading the responses file

Status: accepted (R08)

## Context

The responses file comes as LimeSurvey CSV or as XLSX (architecture section 3). Both
must give the same DataFrame, so that every later stage is independent of the format.
Validation (R09) needs to find values that are not numbers, while empty cells are never
a finding (D12).

## Decision

- **Format.** The CSV format was read off the CSV exports with dummy answers of the
  synthetic data (structure only, nothing copied): UTF-8 without BOM, comma, LF line
  endings, no quoting needed, one heading row of question codes, empty cell = nothing
  between two commas, `submitdate` as `YYYY-MM-DD`, 75 columns like the XLSX fixtures.
  The reader additionally accepts a BOM, CRLF and standard CSV quoting. Other
  delimiters or encodings are a `ReadError`.
- **One normalisation for both formats.** Both readers produce text cells and share
  `_normalise`: strip, empty to `NA`, then types by the questionnaire spec
  (`Int64` for the response id and numeric columns, `string` for everything else).
  XLSX cells are first turned into the text a CSV would show (integral floats without
  decimals, date-times as `YYYY-MM-DD HH:MM:SS`).
- **No silent loss.** If any value of a numeric column is not an integer, the whole
  column stays `string` with the raw text. R09 finds these columns with
  `unconverted_columns(df, spec)` and counts the offending cells with
  `pd.to_numeric(..., errors="coerce")`. The alternative, coercing to `NA`, would hide
  bad data as "question not shown".
- **Errors.** Unreadable or malformed files raise `ReadError` with file name and
  reason; cell values never appear in messages. Parser exceptions are replaced by
  their type name.
- **Manifest** uses the standard library only (frozen dataclasses with explicit checks,
  `ManifestError` names the field). No validation library was added.

## Consequences

- Later stages can rely on dtypes, except for columns reported by
  `unconverted_columns`.
- Dropping fully empty rows and stray unnamed empty columns happens at reading time,
  because spreadsheets produce them; no response is affected.
- Metadata (dates) is text; it is never analysed.
