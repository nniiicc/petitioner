# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`petitioner` is a CLI + library that collects Change.org petitions and their complete comment
sets into a SQLite store, with Parquet/CSV export. Collection is authentication-free: it warms a
session cookie from the csrf endpoint and calls the site's GraphQL api-proxy with a client header.
No login, API key, or CAPTCHA circumvention — on a hard bot block the run halts by design.

## Commands

```bash
uv sync --extra dev                                  # install deps + dev tools into .venv
uv run ruff check . && uv run mypy src && uv run pytest tests/   # full local gate
uv run pytest tests/unit/test_store.py               # single test file
uv run pytest tests/unit/test_store.py::test_name    # single test
uv run ruff format .                                 # format (line-length 88)
PETITIONER_LIVE=1 uv run pytest tests/contract/      # opt-in tests that hit the live site
```

mypy runs in `strict` mode with the pydantic plugin; keep `src/` type-clean. Ruff enforces
`E,F,I,N,W,UP,B,SIM`.

Run the CLI with `uv run petitioner <command>` — `collect` (`--sitemap` / `--urls FILE` /
`--query TERM`, `--limit N`), `export` (`--format parquet|csv|both`), `show` (`--petition-id ID`
for a longitudinal series, else a snapshot). Config is env-overridable via `PETITIONER_<FIELD>`
or a `.env` (see `config.py`).

## Architecture

A strict one-directional pipeline; each layer is independently testable and only depends on the
layers below it. The dependency order is:

`cli` → `orchestrator` → {`discovery`, `client`, `comments`, `normalize`, `store`, `manifest`}
→ `adapter` / `transport` → `config` / `models`.

- **`adapter.py` is the ONE volatile module.** Every Change.org-specific detail — endpoints,
  GraphQL queries, headers, enum literals, field paths, page-size cap, cursor format — lives here
  and nowhere else. When the site changes, this is the only file that should need editing. It
  exposes constants, query builders, and *pure* parse functions (raw dict → flat field dict) that
  raise `AdapterParseError` on shape drift. `ADAPTER_VERSION` is bumped on any change and recorded
  on every run. `tests/contract/` verifies it against the live site.
- **`transport.py`** owns ALL network I/O: the session recipe (csrf cookie → GraphQL POST with
  `x-requested-with`), rate limiting with jitter, and tenacity retries. It distinguishes fault
  types — `BotChallengeError` and `InvalidClientError` (systemic → halt) vs retryable/other
  `TransportError`. No other layer issues HTTP.
- **`client.py`** binds transport (I/O) to adapter (shape) and returns both the parsed dict AND the
  raw payload, so callers can retain the raw. Raises `GraphQLError`, `PetitionNotFoundError`,
  `ParseError` (which carries the raw for on-disk diagnosis).
- **`discovery.py`** yields petition identifiers from three channels: sitemap (complete channel),
  keyword (substring filter over sitemap slugs — on-site Algolia search is unreachable), and a
  caller-supplied URL/id list. Also does language gating via `detect_language` (language is not a
  payload field, so it's detected from the petition text after metadata is fetched).
- **`comments.py`** walks the comments connection page-by-page (20/page, opaque cursor). The
  `on_batch` callback lets the orchestrator persist each page + cursor as it arrives, so an
  interruption resumes from the last stored page rather than restarting.
- **`orchestrator.py`** sequences one run over a list of identifiers. Per petition: fetch metadata
  → language gate → upsert petition → walk comments (resuming from stored cursor, checkpointing
  each page) → compute completeness → retain raw payload → insert an Observation. Fault policy:
  `_FATAL` errors (bot challenge, invalid client) halt the whole run as `PARTIAL`; `_PER_PETITION`
  faults are recorded and the run continues.
- **`store.py`** is the system of record (SQLite). **Snapshot-latest semantics (decision D1):**
  petitions/comments/tags upsert by id; each fetch also appends an immutable `Observation` that
  references the raw payload retained on disk. Provides the snapshot view, longitudinal series, and
  Parquet/CSV export (via polars). Comment progress (cursor + completed flag) is stored so runs
  resume across invocations.
- **`manifest.py`** writes a per-run JSON manifest (`<manifest_dir>/<run_id>.json`) with inputs,
  adapter version, counts, completeness, and exclusions — auditable independently of the logs.
- **`models.py`** are the pydantic domain models produced by `normalize.py` and persisted by
  `store.py`. `config.py` is pydantic-settings; no credentials anywhere.

## Conventions specific to this repo

- **When the site's shape drifts, fix `adapter.py` and bump `ADAPTER_VERSION` — do not scatter
  site-specific literals into other modules.** Parse functions must fail loud (`AdapterParseError`)
  rather than returning partial data.
- Completeness is reconciled against *stored* unique comments vs the reported total (correct across
  a resumed multi-run pull), not just the current run's slice.
- Raw payloads are always retained on disk (including on parse failure and partial pulls) so any run
  is diagnosable after the fact.
- Logging is structured (structlog, JSON). Use `log.error`/`log.warning` with keyword fields, not
  `print`.
- The `OWNER` placeholder in `pyproject.toml` URLs is intentional — a real GitHub account has not
  been set yet.
