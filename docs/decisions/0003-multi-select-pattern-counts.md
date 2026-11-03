# 0003 Multi-select pattern counts

Status: accepted (R15)

## Context

The report shows which help sources students with a diagnosis use, as a chart of the
most frequent combinations of sources (single sources, pairs, triples). The metric
types of architecture section 6.1 cannot hold that: a `Proportion` is one yes/no
count, a `Distribution` has one category per respondent, but a respondent in a
multi-select question belongs to a whole combination of options. Follow-up reports
and the dashboard must also compare combinations between waves, which needs counts
with denominators (architecture section 6.1), not a picture or a ranking. The chart
itself must be drawn from stored numbers, because charts are created only in `present`.

## Decision

- **New type `PatternCounts`** (kind `pattern_counts`, in `METRIC_TYPES`): the ordered
  option codes, the observed combinations (each a tuple of option codes in option
  order), the number of respondents per combination and `n_missing`. `n` is the sum of
  the counts, so the counts always add up to the respondents counted.
- **The empty combination is stored** when it occurs. It is the "none of the options"
  count, it keeps `n` equal to the group size without extra fields, and a metric reader
  never has to compute a remainder.
- **Only observed combinations are stored**, each with a count of at least 1, in a
  canonical order (fewer options first, then option order). The number of possible
  combinations grows exponentially with the options (2^8 for help sources), the observed
  ones are few. Canonical order and strict validation make equal metrics equal values
  and give identical JSON.
- **Strict JSON like the other types:**
  `{"kind": "pattern_counts", "options": [...], "patterns": [[...], ...], "counts":
  [...], "n_missing": 0}`. Existing payloads do not change.
- **Selection for the chart is presentation logic.** `top_patterns(counts, size, k)`
  returns the `k` most frequent combinations with exactly `size` options (count
  descending, ties by option codes as text). The chart takes the two most frequent
  single, pair and triple combinations and pads with empty columns, as the previous
  program did. Nothing is suppressed by it.
- Derived values (respondents per option, shares) are computed, never stored.

## Alternatives

- **Store only the chart's top patterns** (six columns). Rejected: the selection would
  be baked into the snapshot, other combinations could not be compared between waves,
  and a change of the chart (more columns) would make old snapshots incomplete.
- **One `Proportion` per combination.** Rejected: the set of ids would depend on the
  data (a new id whenever a new combination occurs), ids are a stored contract and the
  registry lists them in advance. A metric whose id exists in one wave and not in
  another cannot be compared.
- **A `Distribution` with a category per combination.** Rejected for the same reason:
  the categories would have to be fixed up front, 2^8 of them for the help sources.
- **Per-option `Proportion`s only.** They remain (`diagnoses.help.<option>.diagnosed`),
  but they lose the combinations, which the chart shows.

## Consequences

- Any multi-select question can use the type; domains choose the population and
  whether an option such as "nobody" is part of the options.
- The registry knows the new kind; consumers that dispatch on `kind` (store, compare,
  present) must handle `pattern_counts`. The store keeps the JSON text, so the schema
  does not change.
- Comparing waves means comparing counts per combination with their `n`; combinations
  missing in one wave have count 0 there.
- The metric value is larger than the others (one entry per observed combination), but
  stays small for realistic data.
