"""GraphQL call helpers — bind transport (I/O) to adapter (shape) and fail loud.

Returns both the parsed flat dict and the raw payload, so callers can retain the raw for
Observations (NFR-2). Raises distinct, actionable errors on GraphQL faults (FR-7.4).
"""

from __future__ import annotations

from typing import Any

import structlog

from . import adapter
from .transport import Transport

log = structlog.get_logger(__name__)


class GraphQLError(Exception):
    """The api-proxy returned a GraphQL ``errors`` array (e.g. field-path drift)."""


class PetitionNotFoundError(Exception):
    """Petition is closed, deleted, or never existed (spec §9.2)."""


class ParseError(Exception):
    """A payload did not match the expected shape; carries the raw payload (FR-7.4).

    The raw is attached so callers can retain it on disk for diagnosis rather than
    discarding it on exactly the failure case where it is most useful.
    """

    def __init__(self, message: str, raw: dict[str, Any]) -> None:
        super().__init__(message)
        self.raw = raw


def _data_or_raise(payload: dict[str, Any], operation: str) -> dict[str, Any]:
    if isinstance(payload.get("errors"), list) and payload["errors"]:
        # Messages are redacted server-side; surface codes/locations for contract tests.
        raise GraphQLError(f"{operation}: {payload['errors']}")
    return payload


def fetch_petition(
    tx: Transport, slug_or_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch + parse petition metadata. Returns (fields, raw_payload)."""
    raw = tx.post_graphql(adapter.petition_query(slug_or_id))
    _data_or_raise(raw, "PetitionMetadata")
    if (raw.get("data") or {}).get("petition") is None:
        raise PetitionNotFoundError(slug_or_id)
    try:
        return adapter.parse_petition(raw), raw
    except adapter.AdapterParseError as exc:
        raise ParseError(f"PetitionMetadata: {exc}", raw=raw) from exc


def fetch_comment_page(
    tx: Transport, slug_or_id: str, after: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch + parse one comment page. Returns (page, raw_payload)."""
    raw = tx.post_graphql(adapter.comments_query(slug_or_id, after))
    _data_or_raise(raw, "CommentPage")
    if (raw.get("data") or {}).get("petition") is None:
        raise PetitionNotFoundError(slug_or_id)
    try:
        return adapter.parse_comment_page(raw), raw
    except adapter.AdapterParseError as exc:
        raise ParseError(f"CommentPage: {exc}", raw=raw) from exc
