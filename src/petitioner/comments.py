"""Full comment retrieval — cursor walk with completeness and resume (spec §5.4).

The comments connection serves 20 nodes/page (adapter.COMMENT_PAGE_SIZE), paged by an
opaque cursor (`after`). Cursors decode to ``arrayconnection:<offset>``, so a run can
resume from a stored cursor (FR-4.4). The optional ``on_batch`` callback lets callers
persist each page as it arrives — both the comments and the cursor — so an interruption
mid-walk resumes from the last persisted page rather than restarting (§9.10).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import structlog

from . import client
from .transport import Transport

log = structlog.get_logger(__name__)


@dataclass
class CommentBatch:
    """One page of comments plus the cursor needed to resume after it."""

    comments: list[dict[str, Any]]
    raw_payload: dict[str, Any]
    end_cursor: str | None
    has_next: bool
    reported_total: int


@dataclass
class CommentResult:
    """Outcome of a full comment pull for one petition (this run's walk)."""

    comments: list[dict[str, Any]] = field(default_factory=list)
    raw_pages: list[dict[str, Any]] = field(default_factory=list)
    reported_total: int = 0
    last_cursor: str | None = None
    completed: bool = False

    @property
    def completeness(self) -> float:
        """This-run unique comments / reported total; 1.0 when total is 0.

        Callers that resume across runs should reconcile against the *stored* unique
        count instead (see orchestrator), since this counts only the current walk.
        """
        if self.reported_total <= 0:
            return 1.0
        return min(1.0, len(self.comments) / self.reported_total)


def iter_comment_pages(
    tx: Transport, slug_or_id: str, start_cursor: str | None = None
) -> Iterator[CommentBatch]:
    """Yield comment pages, walking the connection until exhausted.

    Begins after ``start_cursor`` (None = from the first page) so an interrupted pull
    resumes where it stopped.
    """
    cursor = start_cursor
    while True:
        page, raw = client.fetch_comment_page(tx, slug_or_id, cursor)
        yield CommentBatch(
            comments=page["comments"],
            raw_payload=raw,
            end_cursor=page["end_cursor"],
            has_next=page["has_next"],
            reported_total=page["total"],
        )
        if not page["has_next"] or not page["comments"]:
            return
        cursor = page["end_cursor"]


def collect_comments(
    tx: Transport,
    slug_or_id: str,
    start_cursor: str | None = None,
    on_batch: Callable[[CommentBatch], None] | None = None,
) -> CommentResult:
    """Retrieve comments for a petition, de-duplicating by comment_id.

    Walks from ``start_cursor`` (None = first page). For each page, invokes ``on_batch``
    (if given) so the caller can persist comments + cursor incrementally. ``completed``
    is True only when the server reports the connection exhausted (so a short/odd walk
    is left resumable). Zero-comment petitions return cleanly (spec §9.3).
    """
    result = CommentResult()
    seen: set[str] = set()
    last_has_next = False
    for batch in iter_comment_pages(tx, slug_or_id, start_cursor):
        result.reported_total = batch.reported_total
        result.last_cursor = batch.end_cursor or result.last_cursor
        result.raw_pages.append(batch.raw_payload)
        last_has_next = batch.has_next
        for c in batch.comments:
            if c["comment_id"] not in seen:
                seen.add(c["comment_id"])
                result.comments.append(c)
        if on_batch is not None:
            on_batch(batch)
        log.debug(
            "comment_page",
            slug=slug_or_id,
            collected=len(result.comments),
            total=result.reported_total,
        )
        if not batch.has_next:
            break
    result.completed = not last_has_next
    return result
