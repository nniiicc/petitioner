"""Per-run manifest (spec §13) — a machine-readable record of one run.

Captures the run's inputs, adapter version, attempted/collected counts, completeness
metrics, exclusions, and final status, written to disk as JSON so every run is auditable
independently of the structured logs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import orjson

from .models import Run, RunStatus


@dataclass
class PetitionOutcome:
    """Per-petition completeness record for the manifest."""

    petition_id: str
    identifier: str
    comments_collected: int
    comment_total: int
    completeness: float


def build_manifest(
    run: Run,
    *,
    status: RunStatus,
    finished_at: datetime,
    counts: dict[str, int],
    outcomes: list[PetitionOutcome],
    exclusions: list[dict[str, str]],
) -> dict[str, object]:
    """Assemble the manifest dict for a finished run."""
    completes = [o.completeness for o in outcomes]
    mean_completeness = sum(completes) / len(completes) if completes else 1.0
    return {
        "run_id": run.run_id,
        "status": status.value,
        "started_at": run.started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "adapter_version": run.adapter_version,
        "query_or_targets": run.query_or_targets,
        "counts": counts,
        "completeness": {
            "mean": round(mean_completeness, 4),
            "incomplete": [asdict(o) for o in outcomes if o.completeness < 1.0],
        },
        "exclusions": exclusions,
    }


def write_manifest(manifest_dir: Path, manifest: dict[str, object]) -> Path:
    """Write the manifest to ``<manifest_dir>/<run_id>.json`` and return the path."""
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / f"{manifest['run_id']}.json"
    path.write_bytes(orjson.dumps(manifest, option=orjson.OPT_INDENT_2))
    return path
