"""Unit tests for the adapter parse functions (golden-style, spec §14.1)."""

from __future__ import annotations

import pytest

from petitioner import adapter


def test_parse_petition_maps_all_fields(petition_payload):
    fields = adapter.parse_petition(petition_payload)
    assert fields["petition_id"] == "18514354"
    assert fields["slug"] == "example-petition"
    assert fields["url"] == "https://www.change.org/p/example-petition"
    assert fields["title"] == "Get Amazon to Offer Plastic-Free Packaging Options"
    assert fields["signatures_total"] == 562515
    assert fields["signatures_displayed"] == 784352
    assert fields["signatures_displayed_localized"] == "784,352"
    assert fields["goal"] == 1000000
    assert fields["status"] == "VICTORY"
    assert fields["is_verified_victory"] is False
    assert fields["creator_name"] == "Nicole Delma"
    assert fields["creator_location"] is None
    assert fields["organization"] is None
    assert fields["comment_total"] == 3
    assert fields["tags"] == [
        {"tag_id": "7426", "name": "Environment", "slug": "environment-12"},
        {"tag_id": "8087", "name": "Amazon", "slug": "amazon-en-us"},
    ]


def test_parse_petition_missing_field_raises():
    with pytest.raises(adapter.AdapterParseError):
        adapter.parse_petition({"data": {"petition": {"id": "1"}}})


def test_parse_petition_null_petition_raises():
    with pytest.raises(adapter.AdapterParseError):
        adapter.parse_petition({"data": {"petition": None}})


def test_parse_comment_page(comment_pages):
    page = adapter.parse_comment_page(comment_pages[0])
    assert page["total"] == 3
    assert page["has_next"] is True
    assert page["end_cursor"] == "YXJyYXljb25uZWN0aW9uOjE="
    assert [c["comment_id"] for c in page["comments"]] == ["c1", "c2"]
    # Multibyte text preserved without corruption (spec §9.5).
    assert page["comments"][1]["text"] == "Second reason — café"
    assert page["comments"][1]["city"] is None


def test_parse_comment_node_missing_id_raises():
    bad = {
        "data": {
            "petition": {
                "commentsConnection": {
                    "totalCount": 1,
                    "pageInfo": {},
                    "nodes": [{"comment": "x"}],
                }
            }
        }
    }
    with pytest.raises(adapter.AdapterParseError):
        adapter.parse_comment_page(bad)


def test_comments_query_inlines_cursor():
    body = adapter.comments_query("slug", after="CURSOR==")
    assert 'after: "CURSOR=="' in body["query"]
    assert f"first: {adapter.COMMENT_PAGE_SIZE}" in body["query"]
    # First page omits the after argument entirely.
    assert "after:" not in adapter.comments_query("slug", after=None)["query"]
