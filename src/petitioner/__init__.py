"""Change.org petition & comment collector.

Anonymous GraphQL-based collection of petition metadata and complete comment sets.
All site-specific knowledge is isolated in ``petitioner.adapter`` and kept honest by the
live contract tests in ``tests/contract/``.
"""

from __future__ import annotations

__version__ = "0.1.0"
