"""Integration tests for the bugs found in review: resume across runs, per-petition
fault isolation, and comment raw-payload retention."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import orjson

from petitioner.config import Settings
from petitioner.orchestrator import Orchestrator
from petitioner.store import Store
from petitioner.transport import TransportError

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _petition() -> dict[str, Any]:
    return json.loads((FIXTURES / "petition_metadata.json").read_text())


def _page(nodes: list[str], end_cursor: str, has_next: bool) -> dict[str, Any]:
    return {
        "data": {
            "petition": {
                "id": "18514354",
                "commentsConnection": {
                    "totalCount": 3,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                    "nodes": [
                        {
                            "id": n,
                            "comment": f"reason {n}",
                            "role": "SUPPORTER_COMMENT",
                            "likes": 0,
                            "createdAt": None,
                            "user": {"city": None},
                        }
                        for n in nodes
                    ],
                },
            }
        }
    }


class CommentBackend:
    """Serves comment pages keyed by the inlined ``after`` cursor, like the real server.

    Pages: after=None -> page0 (cursor k0, hasNext), after=k0 -> page1 (cursor k1, end).
    ``fail_on_after`` raises a TransportError the FIRST time that cursor is requested,
    to simulate an interruption mid-walk.
    """

    def __init__(self, fail_on_after: str | None = None) -> None:
        self._fail_on_after = fail_on_after

    def post_graphql(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["operationName"] == "PetitionMetadata":
            return _petition()
        m = re.search(r'after:\s*"([^"]*)"', body["query"])
        after = m.group(1) if m else None
        if self._fail_on_after is not None and after == self._fail_on_after:
            self._fail_on_after = None  # fail once, then recover on the next run
            raise TransportError("simulated interruption mid-walk")
        if after is None:
            return _page(["c1", "c2"], "k0", has_next=True)
        return _page(["c3"], "k1", has_next=False)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "db.sqlite",
        raw_payload_dir=tmp_path / "raw",
        export_dir=tmp_path / "exports",
        manifest_dir=tmp_path / "manifests",
    )


def test_resume_across_runs(tmp_path):
    settings = _settings(tmp_path)
    backend = CommentBackend(fail_on_after="k0")  # interrupt before page1

    # Run 1: interrupted after page0. Should NOT crash; partial state persisted.
    with Store(settings.db_path, settings.raw_payload_dir) as store:
        m1 = Orchestrator(backend, store, settings).run(["example"], "t")  # type: ignore[arg-type]
        assert m1.collected == 1  # petition collected despite comment fault
        assert store.count_comments("18514354") == 2  # page0 persisted incrementally
        cursor, done = store.get_comment_progress("18514354")
        assert cursor == "k0" and done is False  # checkpointed, not marked complete
        obs = store.longitudinal("18514354")
        assert obs[-1] is not None  # an observation was written for the partial pull

    # Run 2: resumes from k0, fetches page1, completes.
    with Store(settings.db_path, settings.raw_payload_dir) as store:
        m2 = Orchestrator(backend, store, settings).run(["example"], "t")  # type: ignore[arg-type]
        assert m2.comments_collected == 1  # only c3 is new this run
        assert store.count_comments("18514354") == 3  # full set now
        cursor, done = store.get_comment_progress("18514354")
        assert done is True
        # Completeness on the resumed observation reconciles the full stored set.
        assert m2.outcomes[0].completeness == 1.0


def test_comment_raw_payload_retained(tmp_path):
    settings = _settings(tmp_path)
    with Store(settings.db_path, settings.raw_payload_dir) as store:
        Orchestrator(CommentBackend(), store, settings).run(["example"], "t")  # type: ignore[arg-type]
    raw_files = list((tmp_path / "raw").glob("*.json"))
    assert raw_files
    payload = orjson.loads(raw_files[0].read_bytes())
    assert "petition" in payload
    # The comment pages must be retained so comment fields are re-derivable (FR-5.2).
    assert payload["comments"], "comment raw pages were not retained"
    assert payload["comments"][0]["data"]["petition"]["commentsConnection"]["nodes"]


class _FaultyThenFine:
    """Raises a parse-style fault for the first petition, succeeds for the second."""

    def __init__(self) -> None:
        self._calls = 0

    def post_graphql(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["operationName"] == "PetitionMetadata":
            self._calls += 1
            if self._calls == 1:
                # Drifted shape: petition present but missing required fields.
                return {"data": {"petition": {"id": "x", "slug": "x"}}}
            return _petition()
        return _page(["c1", "c2", "c3"], "k1", has_next=False)


def test_per_petition_fault_does_not_abort_run(tmp_path):
    settings = _settings(tmp_path)
    with Store(settings.db_path, settings.raw_payload_dir) as store:
        m = Orchestrator(_FaultyThenFine(), store, settings).run(  # type: ignore[arg-type]
            ["bad-one", "good-one"], "t"
        )
    # First petition fails (parse), second still collected -> run did not abort.
    assert m.parse_errors == 1
    assert m.collected == 1
    # Parse failure retained a raw payload for diagnosis (FR-7.4).
    assert list((tmp_path / "raw").glob("*.json"))
