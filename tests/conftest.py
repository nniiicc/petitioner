"""Shared test fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def petition_payload() -> dict[str, Any]:
    return load_fixture("petition_metadata.json")


@pytest.fixture
def comment_pages() -> list[dict[str, Any]]:
    return [load_fixture("comment_page_1.json"), load_fixture("comment_page_2.json")]
