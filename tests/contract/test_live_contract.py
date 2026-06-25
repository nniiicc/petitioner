"""Contract test (spec §14.2) — asserts the adapter still matches the live site.

Opt-in: set PETITIONER_LIVE=1 to run (it makes real low-volume requests). This is the
early-warning mechanism for platform drift (NFR-1): if Change.org changes a field path,
endpoint, or the client-header contract, these assertions fail loudly and distinctly.
"""

from __future__ import annotations

import os

import pytest

from petitioner import adapter, client
from petitioner.config import Settings
from petitioner.transport import Transport

pytestmark = pytest.mark.skipif(
    os.environ.get("PETITIONER_LIVE") != "1",
    reason="set PETITIONER_LIVE=1 to run live contract tests",
)

# A stable, high-victory petition used purely as a probe.
PROBE_SLUG = "amazon-com-get-amazon-to-offer-plastic-free-packaging-options"


@pytest.fixture(scope="module")
def tx():
    settings = Settings(requests_per_second=2.0)
    with Transport(settings) as t:
        yield t


def test_client_header_contract(tx):
    """The x-requested-with value must still unlock the proxy (no 'Invalid client')."""
    fields, _ = client.fetch_petition(tx, PROBE_SLUG)
    assert fields["petition_id"]


def test_petition_field_paths_resolve(tx):
    fields, _ = client.fetch_petition(tx, PROBE_SLUG)
    for key in (
        "slug",
        "title",
        "signatures_displayed",
        "goal",
        "status",
        "comment_total",
        "tags",
    ):
        assert key in fields
    assert fields["slug"] == PROBE_SLUG


def test_comment_connection_paginates(tx):
    """Comment connection still returns <=PAGE_SIZE nodes with a usable cursor."""
    page, _ = client.fetch_comment_page(tx, "renewmonkiekid", after=None)
    assert page["total"] > 0
    assert len(page["comments"]) <= adapter.COMMENT_PAGE_SIZE
    if page["has_next"]:
        assert page["end_cursor"]
        page2, _ = client.fetch_comment_page(
            tx, "renewmonkiekid", after=page["end_cursor"]
        )
        assert page2["comments"]
