"""Unit tests for the per-run manifest (spec §13)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from petitioner import manifest
from petitioner.manifest import PetitionOutcome
from petitioner.models import Run, RunStatus


def _run() -> Run:
    return Run(
        run_id="run123",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=None,
        query_or_targets="sitemap",
        adapter_version="changeorg-corgi-5.2153.0",
        status=RunStatus.RUNNING,
    )


def test_build_manifest_summarizes_completeness():
    outcomes = [
        PetitionOutcome("p1", "p1", 100, 100, 1.0),
        PetitionOutcome("p2", "p2", 5, 10, 0.5),
    ]
    m = manifest.build_manifest(
        _run(),
        status=RunStatus.COMPLETE,
        finished_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
        counts={"discovered": 2, "collected": 2},
        outcomes=outcomes,
        exclusions=[{"identifier": "x", "language": "fr"}],
    )
    assert m["run_id"] == "run123"
    assert m["status"] == "complete"
    assert m["adapter_version"] == "changeorg-corgi-5.2153.0"
    assert m["completeness"]["mean"] == 0.75
    # Only incomplete petitions are itemized.
    incomplete = m["completeness"]["incomplete"]
    assert [o["petition_id"] for o in incomplete] == ["p2"]
    assert m["exclusions"] == [{"identifier": "x", "language": "fr"}]


def test_write_manifest_roundtrips(tmp_path):
    m = manifest.build_manifest(
        _run(),
        status=RunStatus.COMPLETE,
        finished_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
        counts={"collected": 0},
        outcomes=[],
        exclusions=[],
    )
    path = manifest.write_manifest(tmp_path / "manifests", m)
    assert path.name == "run123.json"
    loaded = json.loads(path.read_text())
    assert loaded["run_id"] == "run123"
    assert loaded["completeness"]["mean"] == 1.0  # empty -> 1.0
