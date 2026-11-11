# 0002 Legacy parity baseline and known deviations

Status: accepted (R13)

## Context

The new metrics must reproduce the numbers of the previous program on the synthetic
fixtures, or the differences must be documented (architecture section 12). The previous
program puts formatted strings into its report context (percentages rounded half-up,
means and SDs with two decimals), draws some numbers only into charts, and also reads
free-text answers and literature reference values. It cannot run in CI. The domain
tasks R14–R21 will find differences that are intended (decision D12 changes several
denominators, for example) and must not fix them, while CI should keep guarding the
new values.

## Decision

- **Generated once, committed.** `tools/legacy_baseline.py` runs the previous program
  (read-only checkout, its own pinned environment) on every XLSX fixture and writes
  `tests/fixtures/expected/<dataset>.json`. It drives the chapters' context builders
  directly; no previous-program file is changed. It is not run in CI; `--check` shows
  whether the committed files are current.
- **Numbers with their precision.** Each value records its kind (`count`, `percent`,
  `statistic`), the value as shown, the number of decimals shown and, where it can be
  captured without changing the previous program, the unrounded value: the driver wraps
  the percentage formatter (which keeps numerator and denominator) and the mean/SD
  helpers, and reads chart helpers' local variables when they return (age counts,
  help-source patterns, box plot statistics, score histogram).
- **Strictest available comparison.** `tests/parity.py` `assert_parity(dataset, key,
  new)` takes the new unrounded value (a share for percentages). Counts must be equal;
  values with an unrounded legacy counterpart must agree within a relative tolerance
  of 1e-9; values known only as shown are rounded half-up via `decimal.Decimal` to the
  legacy precision and compared. Comparing the unrounded values also catches a wrong
  denominator that happens to round to the same percentage.
- **Known deviations in a tracked file.** `tests/fixtures/expected/known_deviations.yaml`
  lists dataset (or `*`), key, legacy value as shown, new value, task and reason. For a
  listed key `assert_parity` requires the recorded new value instead of the legacy one,
  so the check stays meaningful after the decision to deviate; an entry whose key
  matches the legacy value again fails as stale, and an entry whose legacy value no
  longer matches the expected file fails too. The list starts empty.
- **What is not stored.** Texts, chart files, warnings, the free-text chapter and
  literature reference values. (Until ADR 0004 the counts of filled "other" answers
  were left out too; they are stored since the new metrics use them.) Context keys of the
  previous program that name an aliased instrument are renamed to the alias by
  position, so the driver never contains the real name.

## Consequences

- Domain tests compare with one call per number and need no knowledge of the previous
  program's rounding.
- Every intended difference is visible in one reviewed file with its reason and task,
  and changes to it show up in pull request diffs.
- Rounding differences of the previous program's display (two-decimal means use
  Python's `format`, chart labels `round()`) do not affect the checks, because means
  are compared unrounded.
- If the fixtures change, the expected files must be regenerated with the previous
  program, which needs the local checkout.
