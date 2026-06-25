"""Unit tests for discovery (sitemap parsing, keyword filter, dedupe, targets)."""

from __future__ import annotations

from petitioner import adapter, discovery

_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.change.org/sitemap-2026_06_0.xml</loc></sitemap>
</sitemapindex>"""

_SHARD = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.change.org/p/save-the-climate-now</loc></url>
  <url><loc>https://www.change.org/p/protect-the-climate-action</loc></url>
  <url><loc>https://www.change.org/p/unrelated-petition</loc></url>
  <url><loc>https://www.change.org/about</loc></url>
</urlset>"""


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_text(self, url: str) -> str:
        self.calls.append(url)
        return _INDEX if url == adapter.SITEMAP_INDEX_URL else _SHARD


def test_discover_from_sitemap_extracts_slugs():
    slugs = list(discovery.discover_from_sitemap(FakeTransport()))  # type: ignore[arg-type]
    assert slugs == [
        "save-the-climate-now",
        "protect-the-climate-action",
        "unrelated-petition",
    ]


def test_discover_from_sitemap_respects_limit():
    slugs = list(discovery.discover_from_sitemap(FakeTransport(), limit=2))  # type: ignore[arg-type]
    assert len(slugs) == 2


def test_keyword_filter_matches_all_terms():
    got = list(discovery.discover_by_keyword(FakeTransport(), "climate"))  # type: ignore[arg-type]
    assert got == ["save-the-climate-now", "protect-the-climate-action"]
    # Multi-term requires every term present in the slug.
    got2 = list(discovery.discover_by_keyword(FakeTransport(), "save climate"))  # type: ignore[arg-type]
    assert got2 == ["save-the-climate-now"]


def test_keyword_empty_query_yields_nothing():
    assert list(discovery.discover_by_keyword(FakeTransport(), "   ")) == []  # type: ignore[arg-type]


def test_discover_from_targets_parses_urls_and_ids():
    got = list(
        discovery.discover_from_targets(
            ["https://www.change.org/p/some-slug", "12345", "  ", "raw-slug"]
        )
    )
    assert got == ["some-slug", "12345", "raw-slug"]


def test_dedupe_preserves_order():
    assert discovery.dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_detect_language_english():
    text = "We urge the city council to protect the local park from development plans."
    assert discovery.detect_language(text) == "en"
    assert discovery.detect_language("short") is None
