# 0004 Answers to the open questions after R23

Status: accepted (2026-11-11, Johannes)

## Context

The roadmap run R06–R23 left questions that the code had answered provisionally: values
inferred from the synthetic fixtures, definitions copied from the previous program
although they looked questionable, and CLI behaviour that the architecture had left
open. Johannes answered them on 2026-11-11 and provided the structure of the 2026
LimeSurvey survey (codes, answer codes, display conditions and settings only; it is
kept outside every repository). This record lists every answer and what it changes,
so the changes can be traced from the question to the code.

## Decision

### Questionnaire spec (checked against the 2026 survey)

| # | Question | Answer | Change |
|---|---|---|---|
| 1 | Age range of `DQAGE` | 12 to 20 (a list in the survey) | none |
| 2 | Codes of `DIAGQ0` | `Ja` / `Nein`; `DIAGQ1`–`DIAGQ3` are shown only after `Ja` | none |
| 3 | Range of the `STIG` items | answer codes 1 to 10 | spec range `[0, 9]` → `[1, 10]`; a real 10 failed validation before |
| 4 | Optional columns | `DIAGQ1[BORD]`, `DIAGQ2[KLIN]`, `DIAGQ3[STAT]` and `ANGE2` exist in the survey | stay optional, because the synthetic fixtures lack them |
| 5, 17 | `DIAGQ1[OTHER]`, `DIAGQ3[OTHER]` and the `[other]` columns | there is no `OTHER` option; "other" is the free-text column, and a pupil who chooses "other" must type something | `OTHER` options removed; a filled `[other]` column means "other" was chosen (see D14 below) |
| 6 | `startdate` / `datestamp` | the survey is not date-stamped (a LimeSurvey problem); fieldwork dates come from the survey properties via the LimeSurvey API | none in this program (the columns are present but empty, empty cells are never findings); notes in the spec, architecture §2.1 and roadmap R41 |
| 7 | SBI subscales | two subscales on purpose: merging two of the three published subscales makes no difference according to current research | none; spec comment |
| – | `ANGE1` | not analysed | not in the spec; unknown columns are ignored |

Note on 5/17: in the survey, `DIAGQ1` and `DIAGQ2` require the "other" text when
"other" is ticked, but `DIAGQ3` (treatment) does not have that setting
(`other_comment_mandatory`). A pupil can tick "other treatment" without typing anything,
and that tick does not appear in the export. Setting it in LimeSurvey closes the gap.

### Decision D14 amended

Free-text answers stay out of this program, with one exception: for `DIAGQ1[other]`,
`DIAGQ2[other]` and `DIAGQ3[other]` the program uses **whether the column is filled**,
never its content. A filled column counts as the "other" option of that question. The
text is never interpreted, logged, stored or shown.

### Metric definitions

| # | Question | Answer | Change |
|---|---|---|---|
| 8 | Name of the symptom category 5–9 (`moderate`), which collides with the PHQ-9/GAD-7 band `moderate` (10–14) | rename to `medium` | feature category and the ids `association.moderate.*` become `association.medium.*` |
| 9 | Non-burdened group for RES | only pupils with both scores present and below 10 | `resilience.res.total.nonburdened` uses `burdened == False` |
| 10 | Diagnosis type over all respondents, help and treatment over the diagnosed | intended | none |
| 11 | Pupil with only an "other" help source counted as "no help" | wrong: a filled "other" is a help source | new `diagnoses.help.other.diagnosed`; "other" counts in the number of help sources and in the stored combinations |
| 11a | Does `NIEM` ("nobody") also override a filled "other"? | yes, `NIEM` means no help | none beyond 13 |
| 12 | Pupil with only an "other" treatment counted as untreated | wrong: counts as treated | feature `treatment_any` includes a filled `DIAGQ3[other]`; association metrics follow |
| 13 | `NIEM` overrides the other help sources | yes | none |
| 14 | Diagnosis-type subgroups ignore `DIAGQ0` | cannot happen (display condition) | none |
| 15 | Impairment "elevated" at ≥ 2 | yes | none |
| 16 | `n_missing` of the diagnosed groups = empty `DIAGQ0` | yes | none |
| 18 | `burdened` and symptom category with one score missing | confirmed as implemented | none |
| 19 | Tie-break of help-source combinations by spec option order | fine | none |
| 23 | Number of respondents | a metric of its own, from the number of response rows | new `demography.respondents.count` of a new kind `Count` (an id needs three segments, so the legacy name `demography.all` cannot be used) |

The renamed and changed metrics need no migration and no `METRICS_VERSION` bump: no
snapshot has been written outside tests yet (`spot-report build` does not exist).
Legacy parity keys keep the previous program's names; where a new definition gives a
different number than the previous program, the difference is recorded in
`tests/fixtures/expected/known_deviations.yaml`.

### Command line and operations

| # | Question | Answer | Change |
|---|---|---|---|
| 20 | `build` when `SPOT_ARCHIVE_DIR` is not set | abort with a clear message, because cron does not load the user's environment and skipping would lose every bundle silently; an explicit `--no-archive` option for local tests | architecture §3, roadmap R28 |
| 21 | Location of the snapshot store | environment variable `SPOT_STORE`, overridden by `--store`; no default path; neither given → abort with a clear message. The automation script sets both variables itself | snapshot commands, architecture §11, roadmap R28 and R42 |
| 22 | Wave labels such as `2026-27` | fine, but a label is for display and identification only. Order (e.g. "the wave before this one") always comes from a date, `fieldwork_end`. A second participation in the same school year gets a suffix, e.g. `2026-27-2` | architecture §2.2; the label pattern already allows the suffix, wave order already uses `fieldwork_end` |

### Still open

Content of the follow-up report, the method for "relevant change", how reviewed
free-text answers reach the schools, the response quality rules (architecture §14) and
the design approval for R24.

## Consequences

- Real exports with a `STIG` answer of 10 now pass validation.
- Help, treatment and association numbers change wherever a pupil gave only an "other"
  answer; these are recorded as known deviations from the previous program.
- The program now reads three free-text columns, but only whether they are empty.
