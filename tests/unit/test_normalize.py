"""Unit tests for normalization (spec §14.1)."""

from __future__ import annotations

from datetime import UTC, datetime

from petitioner import adapter, normalize


def test_normalize_petition(petition_payload):
    fields = adapter.parse_petition(petition_payload)
    petition = normalize.normalize_petition(fields, language="en")
    assert petition.petition_id == "18514354"
    assert petition.language == "en"
    assert petition.created_at == datetime(2019, 10, 20, 18, 12, 19, tzinfo=UTC)
    assert petition.comment_total == 3
    assert [t.tag_id for t in petition.tags] == ["7426", "8087"]


def test_normalize_comment():
    raw = {
        "comment_id": "c1",
        "text": "hi",
        "role": "SUPPORTER_COMMENT",
        "likes": 5,
        "city": "Seattle",
        "created_at": "2020-01-01T00:00:00Z",
    }
    c = normalize.normalize_comment(raw, petition_id="p1", run_id="r1")
    assert c.comment_id == "c1"
    assert c.petition_id == "p1"
    assert c.observed_in_run == "r1"
    assert c.created_at == datetime(2020, 1, 1, tzinfo=UTC)


def test_normalize_handles_bad_timestamp():
    raw = {
        "comment_id": "c1",
        "text": None,
        "role": None,
        "likes": None,
        "city": None,
        "created_at": "not-a-date",
    }
    c = normalize.normalize_comment(raw, petition_id="p1", run_id="r1")
    assert c.created_at is None
