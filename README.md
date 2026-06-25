\Collects Change.org petitions and their complete comment sets into a SQLite store with Parquet/CSV export. No login or API key required.

## Install

```bash
pip install petitioner
```

## Use

```bash
petitioner collect --sitemap --limit 50          # discover + collect from the sitemap
petitioner collect --urls petitions.txt          # collect specific URLs/ids
petitioner collect --query "climate"             # keyword filter over sitemap slugs
petitioner export --format both                  # write Parquet + CSV
petitioner show [--petition-id 18514354]         # snapshot, or longitudinal series
```

Config is env-overridable (`PETITIONER_*` or a `.env`). The collector does no
authentication or CAPTCHA circumvention; on a hard block it halts. You are responsible for
ensuring your use is authorized under Change.org's terms.

## Develop

```bash
uv sync --extra dev
uv run ruff check . && uv run mypy src && uv run pytest tests/
PETITIONER_LIVE=1 uv run pytest tests/contract/   # opt-in live tests
```

## License

MIT
