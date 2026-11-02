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

## Data and content

This repository contains no real survey data and no questionnaire texts. Tests use
synthetic datasets only. Report texts, labels and reference values live in a separate,
private content pack; a demo content pack with placeholder texts will be provided in
`examples/content-demo/`.

## License

[GNU Affero General Public License v3.0](LICENSE) or later.
