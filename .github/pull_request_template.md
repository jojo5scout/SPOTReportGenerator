<!-- Title: Conventional Commit subject with roadmap id, e.g. "feat: add absence metrics (R16)" -->

<!-- What this pull request does and why, in one or two sentences. -->

## Changes
-

## Acceptance
<!-- Copy the "Done when" criteria of the roadmap task and say how each was checked. -->
- [ ]

## Checklist

Tests
- [ ] `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass
- [ ] New metrics have a unit test with a hand-made DataFrame and, where the previous
      program computed the same number, a legacy parity check (or the deviation is
      documented below as an intentional fix)

Docs
- [ ] `docs/architecture.md` updated if the architecture changed; ADR in
      `docs/decisions/` for significant decisions
- [ ] Metric ids unchanged, or renamed with a migration and a note below

Hard rules
- [ ] No real survey data; only synthetic datasets in `tests/fixtures/`
- [ ] No questionnaire item texts; specs hold codes and scoring rules only
- [ ] Aliased instruments named only by alias (`RES`, `STIG`), also in commit messages
- [ ] No secrets, passwords, tokens or server paths
- [ ] No response values or free-text answers in logs or validation messages
- [ ] Privacy rules unchanged and applied only through `present/privacy.py`

## Notes
<!-- Deviations, follow-ups, anything reviewers should know. -->

Closes #
