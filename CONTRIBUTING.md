# Contributing

Thank you for your interest in improving petitioner. This document explains how to report issues,
propose changes, and set up a development environment.

## Reporting bugs and requesting features

Open an issue on the [issue tracker](https://github.com/nniiicc/petitioner/issues). For bugs,
include the command you ran, the expected and actual behavior, and the relevant log output (logs are
structured JSON). For feature requests, describe the use case rather than a specific implementation.

## Development setup

You need Python >= 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/nniiicc/petitioner.git
cd petitioner
uv sync --extra dev
```

## Before you open a pull request

Run the full local gate and make sure it passes:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest tests/
```

The live contract tests are opt-in because they hit the real site; run them when you change
`adapter.py`:

```bash
PETITIONER_LIVE=1 uv run pytest tests/contract/
```

## Pull request guidelines

- Keep changes focused; one logical change per pull request.
- All site-specific knowledge (endpoints, GraphQL, field paths) belongs in `adapter.py`. When it
  changes, bump `ADAPTER_VERSION`.
- Add or update tests for any behavior change.
- Update `CHANGELOG.md` under the `Unreleased` section.
- Ensure `ruff`, `mypy`, and `pytest` all pass.

By contributing, you agree that your contributions are licensed under the MIT License, and you agree
to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).
