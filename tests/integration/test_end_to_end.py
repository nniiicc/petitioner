"""End-to-end integration over a mocked transport (spec §14.3).

Drives the orchestrator through discovery → comment retrieval → normalize → persist →
query views, with no network, using fixture payloads.
"""

from __future__ import annotations

from typing import Any

from petitioner.config import Settings
from petitioner.orchestrator import Orchestrator
from petitioner.store import Store


class FakeTransport:
    def __init__(self, petition: dict[str, Any], pages: list[dict[str, Any]]) -> None:
        self._petition = petition
        self._pages = list(pages)

    def post_graphql(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["operationName"] == "PetitionMetadata":
            return self._petition
        return self._pages.pop(0)


def test_full_run(tmp_path, petition_payload, comment_pages):
    settings = Settings(
        db_path=tmp_path / "db.sqlite",
        raw_payload_dir=tmp_path / "raw",
        export_dir=tmp_path / "exports",
        manifest_dir=tmp_path / "manifests",
    )
    tx = FakeTransport(petition_payload, comment_pages)
    with Store(settings.db_path, settings.raw_payload_dir) as store:
        metrics = Orchestrator(tx, store, settings).run(  # type: ignore[arg-type]
            ["example-petition"], "integration"
        )
        assert metrics.collected == 1
        assert metrics.comments_collected == 3
        assert metrics.incomplete_petitions == 0

        snap = store.snapshot()
        assert len(snap) == 1
        assert snap[0]["comment_total"] == 3
        assert snap[0]["language"] == "en"

        written = store.export(settings.export_dir, "csv")
        assert any(p.name == "comments.csv" for p in written)
