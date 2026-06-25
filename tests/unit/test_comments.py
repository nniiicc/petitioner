"""Unit tests for full comment retrieval (dedupe, completeness, resume)."""

from __future__ import annotations

from typing import Any

from petitioner import comments


class FakeTransport:
    """Returns queued GraphQL responses by operation name."""

    def __init__(self, petition: dict[str, Any], pages: list[dict[str, Any]]) -> None:
        self._petition = petition
        self._pages = list(pages)
        self.calls = 0

    def post_graphql(self, body: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if body["operationName"] == "PetitionMetadata":
            return self._petition
        return self._pages.pop(0)


def test_collect_comments_walks_pages_and_dedupes(petition_payload, comment_pages):
    tx = FakeTransport(petition_payload, comment_pages)
    result = comments.collect_comments(tx, "example-petition")  # type: ignore[arg-type]
    # c2 appears in both pages; dedupe yields 3 unique comments for totalCount 3.
    assert [c["comment_id"] for c in result.comments] == ["c1", "c2", "c3"]
    assert result.reported_total == 3
    assert result.completeness == 1.0
    assert result.completed is True


def test_completeness_reports_shortfall(petition_payload):
    page = {
        "data": {
            "petition": {
                "id": "1",
                "commentsConnection": {
                    "totalCount": 10,
                    "pageInfo": {"hasNextPage": False, "endCursor": "x"},
                    "nodes": [
                        {
                            "id": "c1",
                            "comment": "x",
                            "role": "SUPPORTER_COMMENT",
                            "likes": 0,
                            "createdAt": None,
                            "user": {"city": None},
                        }
                    ],
                },
            }
        }
    }
    tx = FakeTransport(petition_payload, [page])
    result = comments.collect_comments(tx, "p")  # type: ignore[arg-type]
    assert result.reported_total == 10
    assert result.completeness == 0.1


def test_zero_comments(petition_payload):
    page = {
        "data": {
            "petition": {
                "id": "1",
                "commentsConnection": {
                    "totalCount": 0,
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [],
                },
            }
        }
    }
    tx = FakeTransport(petition_payload, [page])
    result = comments.collect_comments(tx, "p")  # type: ignore[arg-type]
    assert result.comments == []
    assert result.completeness == 1.0
    assert result.completed is True


def test_on_batch_invoked_per_page_and_raw_retained(petition_payload, comment_pages):
    tx = FakeTransport(petition_payload, comment_pages)
    seen_batches = []
    result = comments.collect_comments(
        tx,
        "p",
        on_batch=seen_batches.append,  # type: ignore[arg-type]
    )
    # Callback fired once per page; raw pages retained for provenance.
    assert len(seen_batches) == 2
    assert len(result.raw_pages) == 2
    assert result.completed is True


def test_completed_false_when_server_reports_more(petition_payload):
    # Anomalous: server says hasNextPage but returns an empty page -> leave resumable.
    page = {
        "data": {
            "petition": {
                "id": "1",
                "commentsConnection": {
                    "totalCount": 5,
                    "pageInfo": {"hasNextPage": True, "endCursor": "k"},
                    "nodes": [],
                },
            }
        }
    }
    tx = FakeTransport(petition_payload, [page])
    result = comments.collect_comments(tx, "p")  # type: ignore[arg-type]
    assert result.completed is False
