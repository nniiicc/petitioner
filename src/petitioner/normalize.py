"""Normalization — raw adapter dicts -> schema models (spec §5.5).

Isolated from fetching and parsing: it only transforms already-parsed field dicts into
validated domain models, so the mapping is independently testable with golden files.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import Comment, Petition, Tag


def _ts(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (``…Z`` UTC) to a datetime, or None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_petition(fields: dict[str, Any], language: str | None) -> Petition:
    """Build a Petition model from parsed fields plus a detected language code."""
    return Petition(
        petition_id=str(fields["petition_id"]),
        slug=fields["slug"],
        url=fields["url"],
        title=fields.get("title"),
        description=fields.get("description"),
        signatures_total=fields.get("signatures_total"),
        signatures_displayed=fields.get("signatures_displayed"),
        signatures_displayed_localized=fields.get("signatures_displayed_localized"),
        goal=fields.get("goal"),
        created_at=_ts(fields.get("created_at")),
        creator_name=fields.get("creator_name"),
        creator_location=fields.get("creator_location"),
        organization=fields.get("organization"),
        is_verified_victory=fields.get("is_verified_victory"),
        status=fields.get("status"),
        # comment_total can be null on some petition states; treat as 0, don't crash.
        comment_total=int(fields["comment_total"] or 0),
        language=language,
        tags=[
            Tag(tag_id=str(t["tag_id"]), name=t.get("name"), slug=t.get("slug"))
            for t in fields.get("tags", [])
        ],
    )


def normalize_comment(raw: dict[str, Any], petition_id: str, run_id: str) -> Comment:
    """Build a Comment model from a parsed comment node."""
    return Comment(
        comment_id=str(raw["comment_id"]),
        petition_id=str(petition_id),
        text=raw.get("text"),
        role=raw.get("role"),
        likes=raw.get("likes"),
        city=raw.get("city"),
        created_at=_ts(raw.get("created_at")),
        observed_in_run=run_id,
    )
