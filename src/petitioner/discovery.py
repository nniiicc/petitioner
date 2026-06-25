"""Petition discovery + language gating (spec §5.1).

Three input channels, all yielding petition identifiers (slug or numeric id):
  * sitemaps  — bulk, exhaustive enumeration; the primary channel;
  * keyword   — keyword filter over sitemap slugs (FR-1.1, see note below);
  * targets   — a caller-supplied list of URLs/ids (FR-1.4).

On search (FR-1.1): Change.org's on-site search is an Algolia InstantSearch integration
with runtime-injected credentials, and its result requests are gated by PerimeterX bot
protection — unreachable from an automated client. Keyword discovery is
therefore a substring filter over sitemap-enumerated slugs: honest and working, though
coarser than full-text search. The sitemap remains the complete channel.

Language is NOT a payload field, so FR-1.5 is satisfied by detecting the
language of the petition text after metadata is fetched (see ``detect_language``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from functools import lru_cache

import structlog

from . import adapter
from .transport import Transport

log = structlog.get_logger(__name__)

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_PETITION_PATH = re.compile(r"/p/([A-Za-z0-9-]+)")


def _locs(xml_text: str) -> list[str]:
    """Extract <loc> values from a sitemap or sitemap index."""
    root = ET.fromstring(xml_text)
    return [el.text.strip() for el in root.findall(".//sm:loc", _SITEMAP_NS) if el.text]


def discover_from_sitemap(tx: Transport, limit: int | None = None) -> Iterator[str]:
    """Yield petition slugs from the sitemap index and its monthly shards."""
    index = _locs(tx.get_text(adapter.SITEMAP_INDEX_URL))
    yielded = 0
    for shard_url in index:
        for loc in _locs(tx.get_text(shard_url)):
            m = _PETITION_PATH.search(loc)
            if not m:
                continue
            yield m.group(1)
            yielded += 1
            if limit is not None and yielded >= limit:
                return


def _keyword_terms(query: str) -> list[str]:
    """Split a query into lowercase alphanumeric terms for slug matching."""
    return [t for t in re.split(r"[^A-Za-z0-9]+", query.lower()) if t]


def discover_by_keyword(
    tx: Transport, query: str, max_results: int | None = None
) -> Iterator[str]:
    """Yield slugs whose text contains every query term, scanning the sitemap (FR-1.1).

    A working stand-in for the unavailable Algolia search: slugs derive from petition
    titles, so a term filter surfaces relevant petitions. Coarser than full-text; use
    ``discover_from_sitemap`` for exhaustive discovery. Logs truncation if a max is hit.
    """
    terms = _keyword_terms(query)
    if not terms:
        return
    count = 0
    for slug in discover_from_sitemap(tx):
        haystack = slug.lower()
        if all(term in haystack for term in terms):
            yield slug
            count += 1
            if max_results is not None and count >= max_results:
                log.info("keyword_truncated", query=query, at=count)
                return


def discover_from_targets(targets: Iterable[str]) -> Iterator[str]:
    """Yield identifiers from caller-supplied URLs / slugs / ids (FR-1.4)."""
    for t in targets:
        t = t.strip()
        if not t:
            continue
        m = _PETITION_PATH.search(t)
        yield m.group(1) if m else t


def dedupe(identifiers: Iterable[str]) -> list[str]:
    """De-duplicate identifiers, preserving first-seen order (FR-1.3)."""
    seen: set[str] = set()
    out: list[str] = []
    for i in identifiers:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


@lru_cache(maxsize=1)
def _detector():  # type: ignore[no-untyped-def]
    from lingua import LanguageDetectorBuilder

    return (
        LanguageDetectorBuilder.from_all_languages()
        .with_preloaded_language_models()
        .build()
    )


def detect_language(text: str | None) -> str | None:
    """Best-effort ISO 639-1 language code for petition text; None if undetermined."""
    if not text or len(text.strip()) < 20:
        return None
    lang = _detector().detect_language_of(text)
    if lang is None:
        return None
    return str(lang.iso_code_639_1.name).lower()
