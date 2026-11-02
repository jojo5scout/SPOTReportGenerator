# SPOTReportGenerator

SPOT is an anonymous survey on the mental health of upper secondary school students.
After a school has completed a survey wave, its school leadership receives a written
report. This command-line tool turns the survey responses of one school and one wave
into that report as a PDF: an initial report for the first wave, a follow-up report for
every later wave.

The project is in an early stage. See [docs/architecture.md](docs/architecture.md) for
the design and [docs/roadmap.md](docs/roadmap.md) for the plan.

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 and all dependencies)
- Pango for PDF rendering with WeasyPrint. On Ubuntu:
  `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`

## Getting started

```bash
uv sync
uv run spot-report --help
uv run pytest
```

Before the first commit, install the Git hooks:

```bash
uv run pre-commit install
```

The hooks reject data files outside `tests/fixtures/` and `examples/content-demo/`, and
reject files and commit messages containing terms from a local, untracked
`.denylist.txt` (one term per line). Commits fail while that file is missing; ask a
maintainer for its contents.

## Data and content

This repository contains no real survey data and no questionnaire texts. Tests use
synthetic datasets only. Report texts, labels and reference values live in a separate,
private content pack; a demo content pack with placeholder texts will be provided in
`examples/content-demo/`.

## License

[GNU Affero General Public License v3.0](LICENSE) or later.
