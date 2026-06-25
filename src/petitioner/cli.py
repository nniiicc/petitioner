"""Command-line interface (spec §17). ``petitioner <command>``."""

from __future__ import annotations

import logging
import sys

import click
import structlog

from . import discovery
from .config import load_settings
from .orchestrator import Orchestrator
from .store import Store
from .transport import Transport


def _configure_logging(level: str) -> None:
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


@click.group()
@click.option("--log-level", default=None, help="Override log level (DEBUG/INFO/...).")
@click.pass_context
def cli(ctx: click.Context, log_level: str | None) -> None:
    """Collect Change.org petitions and complete comment sets."""
    settings = load_settings(**({"log_level": log_level} if log_level else {}))
    _configure_logging(settings.log_level)
    ctx.obj = settings


@cli.command()
@click.option(
    "--query",
    help="Keyword filter over sitemap slugs (on-site full-text search is an Algolia "
    "integration that is not reachable from an automated client).",
)
@click.option("--sitemap", is_flag=True, help="Discover petitions from the sitemap.")
@click.option(
    "--urls", type=click.File("r"), help="File of petition URLs/ids (one per line)."
)
@click.option("--limit", type=int, default=None, help="Cap the number of petitions.")
@click.pass_obj
def collect(settings, query, sitemap, urls, limit) -> None:  # type: ignore[no-untyped-def]
    """Run a collection over discovered petitions."""
    with Transport(settings) as tx:
        if query:
            ids = list(discovery.discover_by_keyword(tx, query, max_results=limit))
            target_desc = f"keyword:{query}"
        elif sitemap:
            ids = list(discovery.discover_from_sitemap(tx, limit=limit))
            target_desc = "sitemap"
        elif urls:
            ids = list(discovery.discover_from_targets(urls.read().splitlines()))
            if limit:
                ids = ids[:limit]
            target_desc = "url-list"
        else:
            raise click.UsageError("Provide one of --query, --sitemap, or --urls.")

        ids = discovery.dedupe(ids)
        if not ids:
            click.echo("No petitions discovered.")
            return
        click.echo(f"Discovered {len(ids)} petitions; collecting...")
        with Store(settings.db_path, settings.raw_payload_dir) as store:
            metrics = Orchestrator(tx, store, settings).run(ids, target_desc)
    click.echo(
        f"Collected {metrics.collected}/{metrics.discovered} petitions, "
        f"{metrics.comments_collected} comments "
        f"({metrics.incomplete_petitions} incomplete, "
        f"{metrics.excluded_language} non-English, {metrics.not_found} not found)."
    )


@cli.command()
@click.option(
    "--format", "fmt", type=click.Choice(["parquet", "csv", "both"]), default="both"
)
@click.pass_obj
def export(settings, fmt) -> None:  # type: ignore[no-untyped-def]
    """Export petitions and comments to Parquet/CSV."""
    with Store(settings.db_path, settings.raw_payload_dir) as store:
        written = store.export(settings.export_dir, fmt)
    for path in written:
        click.echo(f"wrote {path}")


@cli.command()
@click.option("--petition-id", help="Show the longitudinal series for one petition.")
@click.pass_obj
def show(settings, petition_id) -> None:  # type: ignore[no-untyped-def]
    """Show the snapshot view, or a petition's longitudinal time series."""
    import orjson

    with Store(settings.db_path, settings.raw_payload_dir) as store:
        data = store.longitudinal(petition_id) if petition_id else store.snapshot()
    sys.stdout.buffer.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))
    sys.stdout.write("\n")


if __name__ == "__main__":
    cli()
