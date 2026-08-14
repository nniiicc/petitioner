"""Live end-to-end smoke (spec §14.2) — the full pipeline against one real petition.

Opt-in: set PETITIONER_LIVE=1 to run (it makes real low-volume requests). Where
``test_live_contract`` probes the adapter's field paths in isolation, this drives the
real orchestrator — discovery-supplied identifier -> metadata fetch -> streamed raw
capture -> comment walk with checkpointing -> observation -> export — against the live
site, verifying the layers compose outside of fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path

import orjson
import pytest

from petitioner.config import Settings
from petitioner.orchestrator import Orchestrator
from petitioner.store import Store
from petitioner.transport import Transport

pytestmark = pytest.mark.skipif(
    os.environ.get("PETITIONER_LIVE") != "1",
    reason="set PETITIONER_LIVE=1 to run live contract tests",
)

# A small, stable petition with a modest comment set (also used as the pagination
# probe in test_live_contract), keeping the full walk to a handful of requests.
PROBE_SLUG = "renewmonkiekid"


def test_full_pipeline_against_live_site(tmp_path: Path) -> None:
    """Collect one real petition end-to-end and verify every persisted artifact."""
    settings = Settings(
        db_path=tmp_path / "db.sqlite",
        raw_payload_dir=tmp_path / "raw",
        export_dir=tmp_path / "exports",
        manifest_dir=tmp_path / "manifests",
        requests_per_second=2.0,
        per_domain_request_ceiling=200,
        exclude_non_allowed_languages=False,
    )
    with (
        Transport(settings) as tx,
        Store(settings.db_path, settings.raw_payload_dir) as store,
    ):
        metrics = Orchestrator(tx, store, settings).run([PROBE_SLUG], "live-smoke")

        assert metrics.collected == 1
        assert metrics.parse_errors == 0
        assert metrics.comments_collected > 0

        snap = store.snapshot()
        assert len(snap) == 1
        pid = snap[0]["petition_id"]
        assert snap[0]["slug"] == PROBE_SLUG

        # Comment walk ran to completion and checkpointed as done.
        _, done = store.get_comment_progress(pid)
        assert done is True
        assert store.count_comments(pid) == metrics.comments_collected

        # An observation references the streamed raw capture on disk.
        series = store.longitudinal(pid)
        assert len(series) == 1
        assert metrics.outcomes[0].completeness > 0.0

        written = store.export(settings.export_dir, "both")
        assert {p.name for p in written} >= {"petitions.parquet", "comments.csv"}

    # Raw capture is JSON lines: petition payload first, then >=1 comment page.
    raw_files = list((tmp_path / "raw").glob("*.jsonl"))
    assert len(raw_files) == 1
    lines = raw_files[0].read_bytes().splitlines()
    assert len(lines) >= 2
    assert orjson.loads(lines[0])["data"]["petition"]["slug"] == PROBE_SLUG
    page = orjson.loads(lines[1])
    assert page["data"]["petition"]["commentsConnection"]["nodes"]

    # The run manifest was written and is parseable.
    manifests = list((tmp_path / "manifests").glob("*.json"))
    assert len(manifests) == 1
    manifest = orjson.loads(manifests[0].read_bytes())
    assert manifest["counts"]["collected"] == 1
