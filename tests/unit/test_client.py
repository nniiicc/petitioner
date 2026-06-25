"""Unit tests for the client layer's fail-loud behavior (FR-7.4, acceptance 17.2.4)."""

from __future__ import annotations

from typing import Any

import pytest

from petitioner import client


class _Tx:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def post_graphql(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._response


def test_graphql_errors_raise_not_silent():
    """A drifted query yields a GraphQL errors array -> distinct, actionable failure."""
    tx = _Tx(
        {
            "errors": [
                {
                    "message": "[Redacted]",
                    "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"},
                }
            ]
        }
    )
    with pytest.raises(client.GraphQLError):
        client.fetch_petition(tx, "slug")  # type: ignore[arg-type]


def test_null_petition_raises_not_found():
    tx = _Tx({"data": {"petition": None}})
    with pytest.raises(client.PetitionNotFoundError):
        client.fetch_petition(tx, "slug")  # type: ignore[arg-type]
